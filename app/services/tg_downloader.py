"""Telegram media downloader supporting large files (>20MB up to 2GB) via MTProto."""
import asyncio
import logging
import os
from pathlib import Path
from typing import Optional, Any
from aiogram import Bot
from aiogram.types import Message
from aiogram.exceptions import TelegramBadRequest
from app.config import config

logger = logging.getLogger(__name__)

_pyro_client: Optional[Any] = None
_pyro_lock = asyncio.Lock()


class MediaWrapper:
    """Wrapper to supply file_id, file_size, and file_name to Pyrogram Client.download_media."""
    def __init__(self, file_id: str, file_size: int = 0, file_name: str = "video.mp4", mime_type: str = ""):
        self.file_id = file_id
        self.file_size = file_size
        self.file_name = file_name
        self.mime_type = mime_type


async def get_pyrogram_client() -> Optional[Any]:
    """Retrieve or initialize the singleton in-memory Pyrogram client."""
    global _pyro_client
    if _pyro_client is not None and getattr(_pyro_client, "is_connected", False) is True:
        return _pyro_client

    async with _pyro_lock:
        if _pyro_client is not None and getattr(_pyro_client, "is_connected", False) is True:
            return _pyro_client

        api_id = config.telegram_api_id or os.getenv("TELEGRAM_API_ID")
        api_hash = config.telegram_api_hash or os.getenv("TELEGRAM_API_HASH")
        bot_token = config.telegram_bot_token or os.getenv("TELEGRAM_BOT_TOKEN")

        if not (api_id and api_hash and bot_token):
            logger.warning("Telegram API credentials missing. MTProto downloader is unavailable.")
            return None

        try:
            from pyrogram import Client
            client = Client(
                name="tg_mtproto_downloader",
                api_id=int(api_id),
                api_hash=str(api_hash).strip(),
                bot_token=str(bot_token).strip(),
                in_memory=True,
                no_updates=True,
                workdir=str(config.runtime_dir),
            )
            await client.start()
            _pyro_client = client
            logger.info("Pyrogram MTProto client started successfully for large downloads.")
            return _pyro_client
        except Exception as e:
            logger.exception(f"Failed to start Pyrogram MTProto client: {e}")
            return None


async def stop_pyrogram_client() -> None:
    """Gracefully stop the Pyrogram client if active."""
    global _pyro_client
    async with _pyro_lock:
        if _pyro_client is not None:
            try:
                if getattr(_pyro_client, "is_connected", False) is True:
                    await _pyro_client.stop()
            except Exception as e:
                logger.warning(f"Error while stopping Pyrogram client: {e}")
            finally:
                _pyro_client = None


async def download_telegram_media(
    message: Message,
    destination_path: Path,
    bot: Optional[Bot] = None,
    status_msg: Optional[Message] = None,
) -> Path:
    """Download video or document media from Telegram message.
    
    If media <= 20MB, attempts standard Bot API download.
    If > 20MB or Bot API reports 'file is too big', falls back to MTProto Pyrogram client
    which supports files up to 2GB.
    """
    file_id = None
    file_size = 0
    file_name = "video.mp4"
    mime_type = ""

    if message.video:
        file_id = getattr(message.video, "file_id", None)
        file_size = getattr(message.video, "file_size", 0) or 0
        file_name = getattr(message.video, "file_name", None) or "video.mp4"
        mime_type = getattr(message.video, "mime_type", None) or "video/mp4"
    elif message.document:
        file_id = getattr(message.document, "file_id", None)
        file_size = getattr(message.document, "file_size", 0) or 0
        file_name = getattr(message.document, "file_name", None) or "video.mp4"
        mime_type = getattr(message.document, "mime_type", None) or ""

    if not file_id:
        raise ValueError("សារនេះមិនមានឯកសារវីដេអូសម្រាប់ទាញយកទេ។")

    destination_path = Path(destination_path)
    destination_path.parent.mkdir(parents=True, exist_ok=True)

    http_limit = 20 * 1024 * 1024  # 20 MB Telegram HTTP Bot API limit

    # Attempt standard HTTP download if size is within 20 MB limit
    if file_size <= http_limit and bot is not None:
        try:
            file_obj = await bot.get_file(file_id)
            await bot.download_file(file_obj.file_path, destination=destination_path)
            if destination_path.exists() and destination_path.stat().st_size > 0:
                return destination_path
        except (TelegramBadRequest, Exception) as ex:
            err_str = str(ex).lower()
            if "file is too big" in err_str or "toobig" in err_str or isinstance(ex, TelegramBadRequest):
                logger.info(f"Bot API get_file rejected {file_id} ({ex}). Switching to MTProto Pyrogram...")
            else:
                logger.warning(f"HTTP download failed with error: {ex}. Falling back to MTProto...")

    # MTProto download branch for large files (>20MB) or HTTP fallback
    client = await get_pyrogram_client()
    if client is None:
        raise RuntimeError(
            "Telegram Bot API កំណត់ទំហំត្រឹម 20MB សម្រាប់ការទាញយកធម្មតា។ "
            "ដើម្បីទាញយកវីដេអូធំជាង 20MB សូមប្រាកដថាបានកំណត់ TELEGRAM_API_ID និង TELEGRAM_API_HASH ក្នុង .env។"
        )

    last_edit = 0.0

    async def progress_cb(current: int, total: int) -> None:
        nonlocal last_edit
        if not status_msg:
            return
        now = asyncio.get_event_loop().time()
        # Edit message at most once every 3.5 seconds to respect rate limits
        if (now - last_edit >= 3.5) or (total > 0 and current >= total):
            last_edit = now
            cur_mb = current / (1024 * 1024)
            tot_mb = (total or file_size) / (1024 * 1024)
            pct = (current / total * 100) if total > 0 else 0
            try:
                await status_msg.edit_text(
                    f"⏳ កំពុងទាញយកវីដេអូ... {cur_mb:.1f} MB / {tot_mb:.1f} MB ({pct:.0f}%)"
                )
            except Exception:
                pass

    media_ref = MediaWrapper(
        file_id=file_id,
        file_size=file_size,
        file_name=file_name,
        mime_type=mime_type,
    )

    try:
        res = await client.download_media(
            media_ref,
            file_name=str(destination_path),
            progress=progress_cb,
        )
    except Exception as e:
        logger.exception(f"MTProto download_media failed for file_id {file_id}: {e}")
        raise RuntimeError(f"បរាជ័យក្នុងការទាញយកឯកសារតាម MTProto៖ {e}") from e

    if not destination_path.exists() or destination_path.stat().st_size == 0:
        raise RuntimeError("ការទាញយកឯកសារវីដេអូបរាជ័យ៖ ឯកសារមិនត្រូវបានរក្សាទុកពេញលេញទេ។")

    return destination_path
