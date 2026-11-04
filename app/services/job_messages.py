"""Reuse a job's Telegram progress message across handler and worker stages."""
import logging
from aiogram.exceptions import TelegramBadRequest

logger = logging.getLogger(__name__)
_messages = {}


def bind(job_id, message):
    message_id = getattr(message, "message_id", None)
    chat_id = getattr(getattr(message, "chat", None), "id", None)
    if type(message_id) is not int or type(chat_id) is not int:
        return
    media = any(getattr(message, kind, None) for kind in ("video", "document", "photo", "audio", "voice", "animation"))
    _messages[job_id] = (chat_id, message_id, bool(media))


async def update(bot, chat_id, job_id, text, reply_markup=None):
    ref = _messages.get(job_id)
    if ref and ref[0] == chat_id:
        try:
            if ref[2]:
                await bot.edit_message_caption(chat_id=chat_id, message_id=ref[1], caption=text, reply_markup=reply_markup, parse_mode=None)
            else:
                await bot.edit_message_text(chat_id=chat_id, message_id=ref[1], text=text, reply_markup=reply_markup, parse_mode=None)
            return
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower():
                return
            if "message to edit not found" not in str(exc).lower():
                raise
        # Network errors must not produce duplicate messages on each refresh.
    message = await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup, parse_mode=None)
    bind(job_id, message)


async def finish(bot, job_id, text, preserve=False):
    ref = _messages.pop(job_id, None)
    if not ref:
        return
    try:
        if ref[2]:
            await bot.edit_message_caption(chat_id=ref[0], message_id=ref[1], caption=text, reply_markup=None, parse_mode=None)
        elif preserve:
            await bot.edit_message_text(chat_id=ref[0], message_id=ref[1], text=text, reply_markup=None, parse_mode=None)
        else:
            await bot.delete_message(chat_id=ref[0], message_id=ref[1])
    except Exception:
        logger.warning("Could not clear completed job status message.")
