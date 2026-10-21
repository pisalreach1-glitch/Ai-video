"""Shared handler utilities for safe editing, ownership verification, and state validation."""
import logging
from aiogram.types import CallbackQuery
from app.domain.states import JobState
from app.storage.jobs import job_storage
from app.ui import texts_km as texts

logger = logging.getLogger(__name__)

async def safe_edit_message(call: CallbackQuery, text: str, reply_markup=None) -> None:
    """
    Safely edit message text or caption, or send a new message if editing fails.
    Prevents TelegramBadRequest 'there is no text in the message to edit'.
    """
    msg = call.message
    if msg.video or msg.document or msg.photo:
        try:
            await msg.edit_caption(caption=text, reply_markup=reply_markup)
            return
        except Exception as e:
            if "message is not modified" in str(e).lower():
                return
            try:
                await msg.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
            await msg.answer(text, reply_markup=reply_markup)
            return

    try:
        await msg.edit_text(text, reply_markup=reply_markup)
    except Exception as e:
        if "message is not modified" in str(e).lower():
            return
        await msg.answer(text, reply_markup=reply_markup)

async def safe_edit_reply_markup(call: CallbackQuery, reply_markup=None) -> None:
    """Safely edit reply markup and ignore idempotent 'message is not modified' errors."""
    try:
        await call.message.edit_reply_markup(reply_markup=reply_markup)
    except Exception as e:
        if "message is not modified" in str(e).lower():
            return
        logger.warning(f"Could not edit reply markup: {e}")

async def verify_callback_job(
    call: CallbackQuery,
    job_id: str,
    disallowed_states: tuple = (JobState.FINAL_QUEUED, JobState.RENDERING, JobState.UPLOADING)
) -> bool:
    """
    Verify callback ownership and ensure job is not locked in rendering.
    """
    user_id = call.from_user.id
    chat_id = call.message.chat.id

    if not job_storage.verify_ownership(job_id, user_id, chat_id):
        await call.answer("Unauthorized.", show_alert=True)
        return False

    job = job_storage.get_job(job_id)
    if not job:
        await call.answer(texts.INVALID_ACTION, show_alert=True)
        return False

    if job.status in disallowed_states:
        await call.answer(texts.ALREADY_PROCESSING, show_alert=True)
        return False

    return True
