"""Delivery service for sending final videos and SRTs to Telegram."""
import logging
from pathlib import Path
from aiogram import Bot
from aiogram.types import FSInputFile
from app.domain.models import Revision
from app.domain.states import JobState
from app.storage.jobs import job_storage
from app.ui import texts_km as texts
from app.ui.keyboards import job_completed_keyboard, delivery_retry_keyboard
from app.services.media import probe_media

logger = logging.getLogger(__name__)

async def deliver_final_video(
    bot: Bot,
    chat_id: int,
    job_id: str,
    revision: Revision,
) -> bool:
    """
    Deliver final rendered MP4 and optional SRT to user.
    If delivery fails, updates job to DELIVERY_FAILED and sends retry button.
    Does not delete or re-render the final file.
    """
    if not revision.final_path:
        logger.error(f"Cannot deliver job {job_id}: final_path is empty.")
        job_storage.set_job_status(job_id, JobState.FAILED, error_message="Final video path missing.")
        return False

    final_file = Path(revision.final_path)
    if not final_file.exists() or final_file.stat().st_size == 0:
        logger.error(f"Cannot deliver job {job_id}: file {final_file} does not exist.")
        job_storage.set_job_status(job_id, JobState.FAILED, error_message="Rendered file missing.")
        return False

    try:
        job_storage.set_job_status(job_id, JobState.UPLOADING)
        media_info = probe_media(final_file)

        # 1. Send video
        video_input = FSInputFile(str(final_file), filename=f"voiceover_{job_id[:8]}.mp4")
        caption = texts.JOB_COMPLETED.format(
            duration=media_info.duration,
            width=media_info.width,
            height=media_info.height,
        )

        has_srt = bool(revision.subtitles_srt and Path(revision.subtitles_srt).exists())
        try:
            await bot.send_video(
                chat_id=chat_id,
                video=video_input,
                caption=caption,
                reply_markup=job_completed_keyboard(job_id=job_id, has_srt=has_srt),
                supports_streaming=True,
                width=media_info.width,
                height=media_info.height,
                duration=int(media_info.duration),
                request_timeout=600,
            )
        except Exception as upload_err:
            logger.warning(f"Bot API send_video failed ({upload_err}). Attempting Pyrogram MTProto fallback...")
            try:
                from app.services.tg_downloader import get_pyrogram_client
                pyro = await get_pyrogram_client()
                if pyro:
                    await pyro.send_video(
                        chat_id=chat_id,
                        video=str(final_file),
                        caption=caption,
                        supports_streaming=True,
                        width=media_info.width,
                        height=media_info.height,
                        duration=int(media_info.duration),
                    )
                    await bot.send_message(
                        chat_id=chat_id,
                        text="🎉 **វីដេអូត្រូវបានផ្ញើរួចរាល់ដោយជោគជ័យ!**",
                        reply_markup=job_completed_keyboard(job_id=job_id, has_srt=has_srt),
                    )
                else:
                    raise upload_err
            except Exception as pyro_err:
                logger.error(f"Pyrogram MTProto upload fallback failed: {pyro_err}")
                raise upload_err

        # 2. Mark job completed
        job_storage.set_job_status(job_id, JobState.COMPLETED)
        return True

    except Exception as e:
        logger.exception(f"Delivery failed for job {job_id}: {e}")
        job_storage.set_job_status(job_id, JobState.DELIVERY_FAILED, error_message=str(e))
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=texts.DELIVERY_FAILED,
                reply_markup=delivery_retry_keyboard(job_id=job_id, revision_id=revision.revision_id),
            )
        except Exception:
            pass
        return False

async def send_srt_file(bot: Bot, chat_id: int, srt_path: Path | str) -> bool:
    """Send SRT subtitle document to chat."""
    srt = Path(srt_path)
    if not srt.exists():
        return False
    try:
        doc = FSInputFile(str(srt), filename=srt.name)
        await bot.send_document(
            chat_id=chat_id,
            document=doc,
            caption="📄 ឯកសារ Subtitle (SRT)",
        )
        return True
    except Exception as e:
        logger.warning(f"Failed to send SRT file: {e}")
        return False
