"""Shared handler utilities for safe editing, ownership verification, and state validation."""
import asyncio
import logging
from aiogram.types import CallbackQuery
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError, TelegramServerError, TelegramRetryAfter
from app.domain.states import JobState
from app.storage.jobs import job_storage
from app.ui import texts_km as texts

logger = logging.getLogger(__name__)

def _temporary_message_error(exc):
    return isinstance(exc, (TelegramNetworkError, TelegramServerError, TelegramRetryAfter, TimeoutError))


async def answer_callback_safely(call, text="", **kwargs):
    try:
        await call.answer(text, **kwargs)
    except TelegramBadRequest as exc:
        if "query is too old" not in str(exc).lower() and "query id is invalid" not in str(exc).lower():
            raise
        logger.info("Expired callback acknowledgement ignored; operation can continue.")
    except (TelegramNetworkError, TelegramServerError, TelegramRetryAfter):
        logger.warning("Callback notification unavailable; continuing the saved operation.")


async def safe_edit_message(call, text, reply_markup=None, prefer_new_for_media=False):
    # Retrying an edit is safe; a status notification must not abort media work.
    message = call.message
    for attempt in range(3):
        try:
            message = await asyncio.wait_for(_safe_edit_message(call, text, reply_markup, prefer_new_for_media), timeout=8)
            break
        except (TelegramNetworkError, TelegramServerError, TelegramRetryAfter, TimeoutError) as exc:
            if attempt == 2 or getattr(exc, "retry_after", 0) > 2:
                logger.warning("Status update deferred; media processing continues.")
                break
            await asyncio.sleep(max(0.5 * (attempt + 1), getattr(exc, "retry_after", 0)))
    if reply_markup:
        from app.services.job_messages import bind
        for row in reply_markup.inline_keyboard:
            for button in row:
                data = button.callback_data or ""
                if data.startswith("job_cancel:"):
                    bind(data.split(":", 1)[1], message or call.message)
    return message


async def _safe_edit_message(
    call: CallbackQuery,
    text: str,
    reply_markup=None,
    prefer_new_for_media: bool = False,
) -> None:
    """
    Safely edit message text or caption, or send a new message if editing fails or if message is media.
    Prevents TelegramBadRequest 'there is no text in the message to edit' and entity parsing errors.
    """
    msg = call.message
    if not msg:
        return

    is_media = bool(
        getattr(msg, "video", None)
        or getattr(msg, "document", None)
        or getattr(msg, "photo", None)
        or getattr(msg, "audio", None)
        or getattr(msg, "voice", None)
        or getattr(msg, "animation", None)
    )

    if is_media and prefer_new_for_media:
        try:
            return await msg.answer(text, reply_markup=reply_markup)
            return
        except Exception as e:
            if _temporary_message_error(e):
                raise
            if "can't parse entities" in str(e).lower():
                return await msg.answer(text, reply_markup=reply_markup, parse_mode=None)
                return
            logger.warning(f"safe_edit_message prefer_new_for_media failed: {e}")

    if is_media:
        try:
            await msg.edit_caption(caption=text, reply_markup=reply_markup)
            return
        except Exception as e:
            if _temporary_message_error(e):
                raise
            if "message is not modified" in str(e).lower():
                return
            if "can't parse entities" in str(e).lower():
                try:
                    await msg.edit_caption(caption=text, reply_markup=reply_markup, parse_mode=None)
                    return
                except Exception as e:
                    if _temporary_message_error(e):
                        raise
                    pass
            try:
                await msg.edit_reply_markup(reply_markup=None)
            except Exception as e:
                if _temporary_message_error(e):
                    raise
                pass
            try:
                return await msg.answer(text, reply_markup=reply_markup)
            except Exception as e:
                if _temporary_message_error(e):
                    raise
                return await msg.answer(text, reply_markup=reply_markup, parse_mode=None)
            return

    try:
        await msg.edit_text(text, reply_markup=reply_markup)
    except Exception as e:
        if _temporary_message_error(e):
            raise
        if "message is not modified" in str(e).lower():
            return
        if "can't parse entities" in str(e).lower():
            try:
                await msg.edit_text(text, reply_markup=reply_markup, parse_mode=None)
                return
            except Exception as e:
                if _temporary_message_error(e):
                    raise
                pass
        try:
            return await msg.answer(text, reply_markup=reply_markup)
        except Exception as e:
            if _temporary_message_error(e):
                raise
            return await msg.answer(text, reply_markup=reply_markup, parse_mode=None)


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
    expected_rev: int | None = None,
    allowed_states: tuple | None = None,
    disallowed_states: tuple = (JobState.FINAL_QUEUED, JobState.RENDERING, JobState.UPLOADING, JobState.COMPLETED),
) -> bool:
    """
    Verify callback ownership, revision freshness, and allowed/disallowed job states.
    Prevents stale settings buttons from overwriting newer revisions and rejects unauthorized actions.
    """
    user_id = call.from_user.id
    chat_id = call.message.chat.id

    if not job_storage.verify_ownership(job_id, user_id, chat_id):
        await answer_callback_safely(call, "Unauthorized.", show_alert=True)
        return False

    job = job_storage.get_job(job_id)
    if not job:
        await answer_callback_safely(call, texts.INVALID_ACTION, show_alert=True)
        return False

    if allowed_states is not None and job.status not in allowed_states:
        await answer_callback_safely(call, "⚠️ មិនអាចកែប្រែបានទេ ស្ថានភាពការងារបច្ចុប្បន្នមិនអនុញ្ញាតឡើយ។", show_alert=True)
        return False

    if disallowed_states and job.status in disallowed_states:
        await answer_callback_safely(call, texts.ALREADY_PROCESSING, show_alert=True)
        return False

    if expected_rev is not None:
        if expected_rev != job.current_revision_id:
            await answer_callback_safely(call, "⚠️ Settings ឬ Revision នេះហួសសម័យហើយ។ សូមប្រើប្រាស់ម៉ឺនុយចុងក្រោយបំផុត។", show_alert=True)
            return False

    return True
