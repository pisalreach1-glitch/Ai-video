import re
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from app.config import config
from app.domain.states import WizardStep, JobState
from app.storage.jobs import job_storage
from app.storage.workspaces import workspace
from app.services.downloader import (
    download_media,
    DownloadSecurityError,
    DownloadLimitError,
)
from app.services.media import probe_media
from app.jobs.worker import worker_pool
from app.ui import texts_km as texts
from app.handlers.common import safe_edit_message
from app.ui.keyboards import (
    source_choice_keyboard,
    link_download_keyboard,
    link_failure_keyboard,
    job_in_progress_keyboard,
)

logger = logging.getLogger(__name__)
router = Router(name="links")

@router.callback_query(F.data == "src_link")
async def cb_source_link(call: CallbackQuery, state: FSMContext) -> None:
    try:
        await call.answer()
    except Exception:
        pass
    await state.set_state(WizardStep.awaiting_url_input)
    await safe_edit_message(call, texts.LINK_PROMPT, reply_markup=source_choice_keyboard())

@router.message(StateFilter(WizardStep.awaiting_url_input, WizardStep.awaiting_video_source, WizardStep.idle, None), F.text)
async def handle_url_input(message: Message, state: FSMContext) -> None:
    raw_text = (message.text or "").strip()
    current_state = await state.get_state()

    # Extract HTTP/HTTPS URL anywhere from the message (supports raw link or Douyin/TikTok share text)
    url_match = re.search(r"https?://[^\s<>\"\'\u4e00-\u9fff\u1780-\u17ff]+", raw_text)
    if not url_match:
        if current_state == WizardStep.awaiting_url_input:
            await message.reply(
                "⚠️ មិនបានរកឃើញ Link ត្រឹមត្រូវនៅក្នុងសាររបស់អ្នកឡើយ。\n\n"
                "សូមផ្ញើ Link វីដេអូដែលមាន `https://...` (ឧទាហរណ៍៖ TikTok, Douyin, YouTube, Facebook, ឬ Link ផ្ទាល់)។\n"
                "💡 ចំពោះ Douyin អ្នកអាច Copy អត្ថបទចែករំលែកពីក្នុង App Douyin មក Paste បាន។",
                reply_markup=source_choice_keyboard(),
            )
        return

    await state.set_state(WizardStep.awaiting_url_input)

    url = url_match.group(0).rstrip("，。；！？）)》>\"'")
    data = await state.get_data()
    user_id = message.from_user.id
    chat_id = message.chat.id

    # Prevent overwriting an active job that is currently rendering or downloading
    existing_job_id = data.get("job_id")
    if existing_job_id:
        existing_job = job_storage.get_job(existing_job_id)
        if existing_job and existing_job.status in (
            JobState.DOWNLOADING,
            JobState.PREVIEW_QUEUED,
            JobState.PREVIEW_RENDERING,
            JobState.FINAL_QUEUED,
            JobState.RENDERING,
            JobState.UPLOADING,
        ):
            await message.reply(
                "⚠️ លោកអ្នកមានការងារមួយកំពុងដំណើរការ។ សូមរង់ចាំឱ្យការងារនោះចប់សិន ឬចុច Cancel មុននឹងផ្ញើ link ថ្មី។",
                reply_markup=job_in_progress_keyboard(existing_job_id),
            )
            return

    # Always create a new clean job instance to prevent overwriting source files
    job = job_storage.create_job(user_id=user_id, chat_id=chat_id, source_type="link", source_url=url)
    job_id = job.job_id
    await state.update_data(job_id=job_id)

    status_msg = await message.reply(texts.LINK_DOWNLOADING, reply_markup=link_download_keyboard(job_id))
    dest_path = workspace.get_source_video_path(job_id)

    def cancel_check() -> bool:
        return worker_pool.is_cancelled(job_id)

    try:
        job_storage.set_job_status(job_id, JobState.DOWNLOADING)
        await download_media(
            url=url,
            destination_path=dest_path,
            max_mb=config.max_media_mb,
            max_seconds=config.max_video_seconds,
            timeout_seconds=config.download_timeout_seconds,
            cancel_check=cancel_check,
        )

        if cancel_check():
            await status_msg.edit_text(texts.JOB_CANCELLED)
            return

        media_info = probe_media(dest_path)
        job_storage.set_job_source(job_id, str(dest_path), media_info, source_url=url)
        job_storage.set_job_status(job_id, JobState.AWAITING_TEXT)

        from app.ui.keyboards import mode_choice_keyboard
        await status_msg.edit_text(
            texts.MODE_CHOICE_PROMPT.format(duration=media_info.duration),
            reply_markup=mode_choice_keyboard(job_id, has_caption=False),
        )

    except DownloadSecurityError as e:
        logger.warning(f"SSRF rejection for URL {url}: {e}")
        await status_msg.edit_text(texts.LINK_INVALID_DESTINATION, reply_markup=link_failure_keyboard())

    except DownloadLimitError as e:
        logger.warning(f"Download limit error for URL {url}: {e}")
        await status_msg.edit_text(f"❌ {e}", reply_markup=link_failure_keyboard())

    except Exception as e:
        logger.exception(f"Download failed for URL {url}: {e}")
        await status_msg.edit_text(
            texts.LINK_DOWNLOAD_FAILED.format(error=str(e)),
            reply_markup=link_failure_keyboard(),
        )
