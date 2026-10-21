"""Root entry point for Telegram Voiceover Bot."""
import asyncio
import logging
import sys
from app.main import main

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Voiceover Bot exited.")
        sys.exit(0)
