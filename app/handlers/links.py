"""Video URL input and download handlers."""
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
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
from app.ui.keyboards import (
    source_choice_keyboard,
    link_download_keyboard,
    link_failure_keyboard,
)

logger = logging.getLogger(__name__)
router = Router(name="links")

@router.callback_query(F.data == "src_link")
async def cb_source_link(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(WizardStep.awaiting_url_input)
    await call.message.edit_text(texts.LINK_PROMPT, reply_markup=source_choice_keyboard())
    await call.answer()

@router.message(WizardStep.awaiting_url_input, F.text.regexp(r"^https?://\S+"))
async def handle_url_input(message: Message, state: FSMContext) -> None:
    url = message.text.strip()
    data = await state.get_data()
    job_id = data.get("job_id")

    user_id = message.from_user.id
    chat_id = message.chat.id

    if not job_id:
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

        await state.set_state(WizardStep.awaiting_narration_text)
        await status_msg.edit_text(
            f"✅ **ទាញយកវីដេអូបានជោគជ័យ!**\n\n"
            f"• រយៈពេល៖ {media_info.duration:.1f} វិនាទី\n"
            f"• ទំហំ៖ {media_info.width}x{media_info.height}\n\n"
            f"{texts.NARRATION_PROMPT.format(max_chars=config.max_narration_chars)}"
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
