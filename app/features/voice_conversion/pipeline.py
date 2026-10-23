"""Pipeline runner for Voice Conversion and downstream Avatar Preview."""
import logging
from pathlib import Path
from typing import Any
from aiogram.types import FSInputFile

from app.domain.features import QueueTask
from app.domain.states import JobState
from app.storage.jobs import job_storage
from app.storage.workspaces import workspace
from app.jobs.gpu_scheduler import gpu_scheduler
from app.features.voice_conversion.storage import voice_conversion_storage
from app.features.voice_conversion.domain import ConversionRequest
from app.features.voice_conversion.backends.seed_vc import seed_vc_backend
from app.features.voice_conversion.quality import evaluate_conversion_quality
from app.features.talking_photo.storage import talking_photo_storage
from app.features.talking_photo.engine import sadtalker_engine
from app.features.talking_photo.long_render import mux_master_audio
from app.features.voice_conversion.keyboards import vc_preview_keyboard
from app.jobs.processes import run_process
from app.config import config

logger = logging.getLogger(__name__)

class VoiceConversionPipeline:
    def validate_task_type(self, task_type: str) -> None:
        if task_type not in ("voice_conversion",):
            raise ValueError(f"Unsupported task_type '{task_type}' for voice_conversion pipeline.")

    async def run(self, task: QueueTask, worker_pool: Any) -> None:
        job_id = task.job_id
        job = job_storage.get_job(job_id)
        conv = voice_conversion_storage.get_latest_conversion_for_job(job_id)

        if not job or not conv:
            logger.error(f"Missing job {job_id} or voice conversion record.")
            job_storage.complete_task(job_id, "failed")
            return

        chat_id = job.chat_id
        bot = worker_pool.get_bot()
        cancel_check = lambda: worker_pool.is_cancelled(job_id)

        def on_pid(pid: int) -> None:
            worker_pool.register_pid(job_id, pid)

        out_dir = Path("runtime") / "jobs" / job_id / "conversion" / conv.conversion_id
        out_dir.mkdir(parents=True, exist_ok=True)

        req = ConversionRequest(
            artifact_id=conv.conversion_id,
            target_reference_wav=Path(conv.target_reference_path),
            full_source_wav=Path(conv.full_source_path),
            output_dir=out_dir,
            input_digest=conv.request_digest,
            backend_revision="seed_vc-v2",
        )

        job_storage.set_job_status(job_id, JobState.RENDERING, stage="voice_converting")

        try:
            # 1. Voice Conversion under GPU lease
            async with gpu_scheduler.acquire(tag="voice_conversion", job_id=job_id):
                converted = await seed_vc_backend.convert(
                    req,
                    cancel_check=cancel_check,
                    on_pid=on_pid,
                )

            if cancel_check():
                job_storage.set_job_status(job_id, JobState.CANCELLED, error_message="Conversion cancelled.")
                voice_conversion_storage.update_conversion_failed(conv.conversion_id, "cancelled")
                job_storage.complete_task(job_id, "cancelled")
                return

            voice_conversion_storage.update_conversion_completed(
                conversion_id=conv.conversion_id,
                converted_wav_path=str(converted.master_wav),
                converted_wav_sha256=converted.sha256,
                converted_duration=converted.duration_seconds,
                manifest_path=str(converted.manifest_path),
            )

            # 2. Update TalkingPhotoRevision with converted master audio
            rev = talking_photo_storage.get_latest_revision(job_id)
            if rev:
                talking_photo_storage.update_revision_paths(
                    job_id=job_id,
                    revision_id=rev.revision_id,
                    inference_wav_path=str(converted.master_wav),
                    master_audio_path=str(converted.master_wav),
                    audio_source="converted_voice",
                    approved_audio_artifact_id=conv.conversion_id,
                )

                # 3. Generate 5-second video preview automatically
                preview_audio = out_dir / "preview_audio_5s.wav"
                cmd_trim = [
                    config.ffmpeg_path,
                    "-y",
                    "-i", str(converted.master_wav),
                    "-t", "5.0",
                    "-c:a", "pcm_s16le",
                    str(preview_audio),
                ]
                await run_process(cmd_trim, timeout=30.0, cancel_check=cancel_check)
                audio_for_preview = preview_audio if preview_audio.exists() else converted.master_wav

                preview_dest = workspace.get_tp_preview_path(job_id, rev.revision_id)

                async with gpu_scheduler.acquire(tag="talking_photo", job_id=job_id):
                    raw_preview = await sadtalker_engine.run_animation(
                        image_path=Path(rev.image_path),
                        audio_path=audio_for_preview,
                        output_dir=out_dir,
                        settings=rev.settings,
                        preview_mode=True,
                        on_pid=on_pid,
                        cancel_check=cancel_check,
                    )

                    await mux_master_audio(
                        video_track=raw_preview,
                        master_audio=converted.master_wav,
                        output_mp4=preview_dest,
                        on_pid=on_pid,
                        cancel_check=cancel_check,
                        preview_limit=5.0,
                    )

                talking_photo_storage.update_revision_paths(job_id, rev.revision_id, preview_path=str(preview_dest))

                # Send preview video with approval options
                caption = (
                    f"🎬 **វីដេអូគំរូ (Preview ៥ វិនាទី) ជាមួយសំឡេងបម្លែងរួចរាល់!**\n\n"
                    f"• រយៈពេលសំឡេងនិយាយពេញ៖ {converted.duration_seconds:.1f} វិនាទី\n"
                    f"• សូមពិនិត្យចលនាមាត់ និងសំនៀងសំឡេងខាងលើ\n"
                    f"• ចុច «✅ អនុម័ត និង Render វីដេអូពេញ» ដើម្បីបង្កើតវីដេអូពេញលេញ។"
                )
                await bot.send_video(
                    chat_id=chat_id,
                    video=FSInputFile(str(preview_dest)),
                    caption=caption,
                    reply_markup=vc_preview_keyboard(job_id, conv.conversion_id),
                )

            job_storage.set_job_status(job_id, JobState.AWAITING_APPROVAL, stage="preview_ready")
            job_storage.complete_task(job_id, "completed")

        except Exception as e:
            logger.exception(f"Voice conversion pipeline error: {e}")
            voice_conversion_storage.update_conversion_failed(conv.conversion_id, str(e))
            job_storage.set_job_status(job_id, JobState.FAILED, error_message=str(e))
            job_storage.complete_task(job_id, "failed")
            await bot.send_message(chat_id, f"❌ ការបម្លែងសំឡេងបានជួបបញ្ហា៖ {e}")

voice_conversion_pipeline = VoiceConversionPipeline()
