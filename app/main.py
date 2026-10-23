"""Main application entry point for Telegram Voiceover Bot."""
import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from app.config import config
from app.storage.database import get_db
from app.storage.cleanup import cleanup_expired_jobs
from app.jobs.worker import worker_pool
from app.handlers import register_all_handlers

from pathlib import Path

# Setup logging handlers safely (supports console and pythonw background execution)
_log_handlers = []
if sys.stdout is not None:
    _log_handlers.append(logging.StreamHandler(sys.stdout))
_log_dir = Path(__file__).resolve().parent.parent / "runtime"
_log_dir.mkdir(parents=True, exist_ok=True)
_log_handlers.append(logging.FileHandler(_log_dir / "bot.log", encoding="utf-8"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=_log_handlers,
)
logger = logging.getLogger("voiceover_bot")

async def main() -> None:
    if not config.telegram_bot_token:
        logger.error("TELEGRAM_BOT_TOKEN is not configured! Please set it in .env.")
        sys.exit(1)

    logger.info("Initializing database...")
    db = get_db()
    db.init_db()

    # Clean up expired jobs on startup
    cleaned = cleanup_expired_jobs()
    if cleaned > 0:
        logger.info(f"Cleaned up {cleaned} expired jobs on startup.")

    # Recover any interrupted jobs from previous shutdown
    from app.storage.jobs import job_storage
    interrupted_count = job_storage.recover_interrupted_jobs()
    if interrupted_count > 0:
        logger.info(f"Recovered {interrupted_count} interrupted jobs from previous run.")

    # Initialize Bot and Dispatcher
    bot = Bot(
        token=config.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Register handlers
    register_all_handlers(dp)

    if config.telegram_api_id and config.telegram_api_hash:
        logger.info("MTProto credentials configured: large video downloads (>20MB up to 2GB) are ENABLED.")
    else:
        logger.warning("TELEGRAM_API_ID or TELEGRAM_API_HASH missing: downloads limited to 20MB by Telegram Bot API.")

    # Initialize background worker pool
    worker_pool.set_bot(bot)
    worker_pool.start()

    logger.info("Telegram Voiceover Bot is ONLINE and polling for updates...")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        logger.info("Shutting down worker pool and closing sessions...")
        from app.services.tg_downloader import stop_pyrogram_client
        await stop_pyrogram_client()
        await worker_pool.stop()
        await bot.session.close()
        logger.info("Bot stopped cleanly.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot exited.")
