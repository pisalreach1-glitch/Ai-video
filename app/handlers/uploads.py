"""Telegram video and document upload handlers."""
import logging
import asyncio
from pathlib import Path
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from app.config import config
from app.domain.states import WizardStep, JobState
from app.storage.jobs import job_storage
from app.storage.workspaces import workspace
from app.services.media import probe_media
from app.ui import texts_km as texts
from app.handlers.common import safe_edit_message
from app.ui.keyboards import (
    caption_confirm_keyboard,
    narration_confirm_keyboard,
    source_choice_keyboard,
    job_in_progress_keyboard,
)

logger = logging.getLogger(__name__)
router = Router(name="uploads")

_user_upload_locks: dict[tuple[int, int], asyncio.Lock] = {}

def get_user_upload_lock(user_id: int, chat_id: int) -> asyncio.Lock:
    key = (user_id, chat_id)
    if key not in _user_upload_locks:
        _user_upload_locks[key] = asyncio.Lock()
    return _user_upload_locks[key]

@router.callback_query(F.data == "src_upload")
async def cb_source_upload(call: CallbackQuery, state: FSMContext) -> None:
    try:
        await call.answer()
    except Exception:
        pass
    await state.set_state(WizardStep.awaiting_video_source)
    await safe_edit_message(call, texts.UPLOAD_PROMPT, reply_markup=source_choice_keyboard())

@router.message(F.video | F.document)
async def handle_video_upload(message: Message, state: FSMContext, bot: Bot) -> None:
    if hasattr(state, "get_state"):
        current_state = await state.get_state()
        if current_state and "TalkingPhotoSteps" in str(current_state):
            return

    user_id = message.from_user.id
    chat_id = message.chat.id

    # Acquire per-user/chat lock during upload check and job claim to prevent race condition
    lock = get_user_upload_lock(user_id, chat_id)
    async with lock:
        # Protect active rendering or downloading job from being overwritten
        active_job = job_storage.get_user_active_job(user_id, chat_id)
        if active_job and active_job.status in (
            JobState.DOWNLOADING,
            JobState.PREVIEW_QUEUED,
            JobState.PREVIEW_RENDERING,
            JobState.FINAL_QUEUED,
            JobState.RENDERING,
            JobState.UPLOADING,
        ):
            await message.reply(
                "⚠️ លោកអ្នកមានការងារវីដេអូមួយកំពុងដំណើរការ។\n"
                "សូមរង់ចាំឱ្យការងារនេះបញ្ចប់ ឬចុចបោះបង់ (Cancel) សិន មុននឹង Upload វីដេអូថ្មី។",
                reply_markup=job_in_progress_keyboard(active_job.job_id),
            )
            return

        # Determine file_id and size
        file_id = None
        file_size = 0
        file_name = "video.mp4"

        if message.video:
            file_id = message.video.file_id
            file_size = message.video.file_size or 0
            file_name = message.video.file_name or "video.mp4"
        elif message.document:
            mime = (message.document.mime_type or "").lower()
            fname = (message.document.file_name or "").lower()
            if not (mime.startswith("video/") or fname.endswith((".mp4", ".mov", ".mkv", ".webm"))):
                await message.reply("⚠️ សូមផ្ញើឯកសារជាទម្រង់វីដេអូ (MP4, MOV, MKV, WEBM)។")
                return
            file_id = message.document.file_id
            file_size = message.document.file_size or 0
            file_name = message.document.file_name or "video.mp4"

        # Enforce size limit
        max_bytes = config.max_media_mb * 1024 * 1024
        if file_size > max_bytes:
            await message.reply(
                f"❌ វីដេអូមានទំហំធំជាង {config.max_media_mb} MB។ សូមផ្ញើវីដេអូដែលមានទំហំតូចជាងនេះ។"
            )
            return

        # Atomically claim candidate job or create new job directly in DOWNLOADING state
        data = await state.get_data()
        candidate_job_id = data.get("job_id")
        job = job_storage.claim_or_create_upload_job(
            user_id=user_id,
            chat_id=chat_id,
            candidate_job_id=candidate_job_id,
        )
        job_id = job.job_id
        await state.update_data(job_id=job_id)

    status_msg = await message.reply("⏳ កំពុងទាញយកវីដេអូមកកាន់ម៉ាស៊ីន... សូមរង់ចាំ។")
    ext = Path(file_name).suffix or ".mp4"
    dest_path = workspace.get_source_video_path(job_id, ext=ext)

    try:
        from app.services.tg_downloader import download_telegram_media
        await download_telegram_media(
            message=message,
            destination_path=dest_path,
            bot=bot,
            status_msg=status_msg,
        )

        # Validate with probe
        media_info = probe_media(dest_path)
        if media_info.duration > config.max_video_seconds:
            dest_path.unlink(missing_ok=True)
            job_storage.set_job_status(job_id, JobState.FAILED, error_message=f"Duration exceeds {config.max_video_seconds}s")
            await status_msg.edit_text(
                f"❌ វីដេអូមានរយៈពេល {media_info.duration:.1f}s ដែលលើសពីដែនកំណត់ {config.max_video_seconds}s។",
                reply_markup=source_choice_keyboard(),
            )
            return

        job_storage.set_job_source(job_id, str(dest_path), media_info)
        job_storage.set_job_status(job_id, JobState.AWAITING_TEXT)

        # Check caption
        caption = (message.caption or "").strip()
        if caption:
            await state.update_data(caption_text=caption)

        from app.ui.keyboards import mode_choice_keyboard
        await status_msg.edit_text(
            texts.MODE_CHOICE_PROMPT.format(duration=media_info.duration),
            reply_markup=mode_choice_keyboard(job_id, has_caption=bool(caption)),
        )

    except Exception as e:
        logger.exception(f"Failed to process uploaded video for job {job_id}: {e}")
        dest_path.unlink(missing_ok=True)
        job_storage.set_job_status(job_id, JobState.FAILED, error_message=str(e))
        await status_msg.edit_text(
            f"❌ វីដេអូមិនត្រឹមត្រូវ ឬមានបញ្ហាក្នុងការអាន៖ {e}",
            reply_markup=source_choice_keyboard(),
        )

@router.callback_query(F.data == "caption_use")
async def cb_caption_use(call: CallbackQuery, state: FSMContext) -> None:
    try:
        await call.answer()
    except Exception:
        pass
    data = await state.get_data()
    caption = data.get("caption_text", "")
    await state.update_data(narration_text=caption)
    await state.set_state(WizardStep.editing_narration_text)

    await safe_edit_message(
        call,
        texts.NARRATION_CONFIRM.format(
            text=caption,
            chars=len(caption),
            max_chars=config.max_narration_chars,
        ),
        reply_markup=narration_confirm_keyboard(),
    )

@router.callback_query(F.data == "caption_skip")
async def cb_caption_skip(call: CallbackQuery, state: FSMContext) -> None:
    try:
        await call.answer()
    except Exception:
        pass
    await state.set_state(WizardStep.awaiting_narration_text)
    await safe_edit_message(
        call,
        texts.NARRATION_PROMPT.format(max_chars=config.max_narration_chars)
    )
