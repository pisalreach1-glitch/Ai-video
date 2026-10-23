"""Pipeline execution orchestrator for Talking Photo."""
import logging
from pathlib import Path
from typing import Any
from aiogram.types import FSInputFile
from app.domain.features import QueueTask
from app.domain.states import JobState
from app.storage.jobs import job_storage
from app.storage.workspaces import workspace
from app.jobs.gpu_scheduler import gpu_scheduler
from app.features.talking_photo.storage import talking_photo_storage
from app.features.talking_photo.engine import sadtalker_engine
from app.features.talking_photo.long_render import mux_master_audio
from app.features.talking_photo.keyboards import tp_preview_keyboard, tp_completed_keyboard
from app.features.talking_photo.media import measure_audio_duration

logger = logging.getLogger(__name__)

class TalkingPhotoPipeline:
    def validate_task_type(self, task_type: str) -> None:
        if task_type not in ("preview", "final", "clone_synthesis"):
            raise ValueError(f"Unsupported task_type '{task_type}' for talking_photo pipeline.")

    async def run(self, task: QueueTask, worker_pool: Any) -> None:
        if task.task_type == "clone_synthesis":
            from app.features.voice_clone.pipeline import voice_clone_pipeline
            return await voice_clone_pipeline.run(task, worker_pool)

        job_id = task.job_id
        revision_id = task.revision_id
        task_type = task.task_type

        job = job_storage.get_job(job_id)
        revision = talking_photo_storage.get_revision(job_id, revision_id)

        if not job or not revision:
            logger.error(f"Missing job {job_id} or talking_photo revision {revision_id}")
            job_storage.complete_task(job_id, "failed")
            return

        chat_id = job.chat_id
        bot = worker_pool.get_bot()
        cancel_check = lambda: worker_pool.is_cancelled(job_id)

        def on_pid(pid: int) -> None:
            worker_pool.register_pid(job_id, pid)

        # Prepare workspace paths
        output_dir = workspace.get_tp_revision_dir(job_id, revision_id)
        image_path = Path(revision.image_path)
        master_audio = Path(revision.master_audio_path or revision.original_voice_path)
        inference_wav = Path(revision.inference_wav_path or master_audio)

        # Verify master audio checksum before render if an active approval exists
        from app.features.voice_clone.storage import voice_clone_storage
        active_approval = voice_clone_storage.get_active_approval(job_id)
        if active_approval and master_audio.exists():
            import hashlib
            hasher = hashlib.sha256()
            with open(master_audio, "rb") as f:
                while chunk := f.read(65536):
                    hasher.update(chunk)
            if hasher.hexdigest() != active_approval.wav_sha256:
                raise RuntimeError("Master audio checksum mismatch: approved audio artifact was modified.")

        try:
            if task_type == "preview":
                job_storage.set_job_status(job_id, JobState.PREVIEW_RENDERING, stage="preview_rendering")
                preview_dest = workspace.get_tp_preview_path(job_id, revision_id)

                # Trim dedicated <=5-second audio BEFORE model inference to save GPU time
                preview_audio = output_dir / f"preview_inference_{revision_id}.wav"
                from app.jobs.processes import run_process
                from app.config import config
                cmd_trim = [
                    config.ffmpeg_path,
                    "-y",
                    "-i", str(inference_wav),
                    "-t", "5.0",
                    "-c:a", "pcm_s16le",
                    str(preview_audio),
                ]
                await run_process(cmd_trim, timeout=30.0, cancel_check=cancel_check)
                inference_to_run = preview_audio if preview_audio.exists() else inference_wav

                async with gpu_scheduler.acquire(tag="talking_photo", job_id=job_id):
                    raw_video = await sadtalker_engine.run_animation(
                        image_path=image_path,
                        audio_path=inference_to_run,
                        output_dir=output_dir,
                        settings=revision.settings,
                        preview_mode=True,
                        on_pid=on_pid,
                        cancel_check=cancel_check,
                        timeout=300.0,
                    )

                    await mux_master_audio(
                        video_track=raw_video,
                        master_audio=master_audio,
                        output_mp4=preview_dest,
                        on_pid=on_pid,
                        cancel_check=cancel_check,
                        preview_limit=5.0,
                    )

                if cancel_check():
                    job_storage.set_job_status(job_id, JobState.CANCELLED, error_message="Preview cancelled.")
                    job_storage.complete_task(job_id, "cancelled")
                    return

                talking_photo_storage.update_revision_paths(job_id, revision_id, preview_path=str(preview_dest))
                job_storage.set_job_status(job_id, JobState.AWAITING_APPROVAL, stage="preview_ready")
                job_storage.complete_task(job_id, "completed")

                if bot:
                    audio_dur = await measure_audio_duration(master_audio)
                    caption = (
                        f"🎬 **វីដេអូគំរូ (Preview 5s) រួចរាល់ហើយ!**\n\n"
                        f"• រយៈពេលសំឡេងពេញ៖ {audio_dur:.1f} វិនាទី\n"
                        f"• ទំហំផ្ទៃមុខ៖ {revision.settings.face_size}x{revision.settings.face_size}\n\n"
                        f"សូមពិនិត្យចលនាមាត់ និងក្បាល។ ប្រសិនបើពេញចិត្ត សូមចុច «✅ អនុម័ត និងទាញយកវីដេអូពេញ»។"
                    )
                    await bot.send_video(
                        chat_id=chat_id,
                        video=FSInputFile(str(preview_dest)),
                        caption=caption,
                        reply_markup=tp_preview_keyboard(job_id, revision_id),
                    )

            elif task_type == "final":
                job_storage.set_job_status(job_id, JobState.RENDERING, stage="rendering_final")
                final_dest = workspace.get_tp_final_path(job_id, revision_id)

                async with gpu_scheduler.acquire(tag="talking_photo", job_id=job_id):
                    raw_video = await sadtalker_engine.run_animation(
                        image_path=image_path,
                        audio_path=inference_wav,
                        output_dir=output_dir,
                        settings=revision.settings,
                        preview_mode=False,
                        on_pid=on_pid,
                        cancel_check=cancel_check,
                        timeout=900.0,
                    )

                    await mux_master_audio(
                        video_track=raw_video,
                        master_audio=master_audio,
                        output_mp4=final_dest,
                        on_pid=on_pid,
                        cancel_check=cancel_check,
                        preview_limit=None, # full duration, covers >= 120s!
                    )

                if cancel_check():
                    job_storage.set_job_status(job_id, JobState.CANCELLED, error_message="Render cancelled.")
                    job_storage.complete_task(job_id, "cancelled")
                    return

                talking_photo_storage.update_revision_paths(job_id, revision_id, final_path=str(final_dest))
                job_storage.set_job_status(job_id, JobState.UPLOADING, stage="delivering")

                if bot:
                    try:
                        audio_dur = await measure_audio_duration(master_audio)
                        caption = (
                            f"🎉 **វីដេអូរូបថតនិយាយ (Talking Photo) រួចរាល់ជាស្ថាពរ!**\n\n"
                            f"• រយៈពេលសរុប៖ {audio_dur:.1f} វិនាទី\n"
                            f"• គុណភាព៖ H.264 / AAC ({revision.settings.face_size}p)"
                        )
                        await bot.send_video(
                            chat_id=chat_id,
                            video=FSInputFile(str(final_dest)),
                            caption=caption,
                            reply_markup=tp_completed_keyboard(job_id, revision_id),
                        )
                        job_storage.set_job_status(job_id, JobState.COMPLETED, stage="completed")
                        job_storage.complete_task(job_id, "completed")
                    except Exception as upload_err:
                        logger.error(f"Delivery failed for talking_photo job {job_id}: {upload_err}")
                        job_storage.set_job_status(
                            job_id,
                            JobState.DELIVERY_FAILED,
                            stage="delivery_failed",
                            error_message=str(upload_err),
                        )
                        job_storage.complete_task(job_id, "failed")
                else:
                    job_storage.set_job_status(job_id, JobState.COMPLETED, stage="completed")
                    job_storage.complete_task(job_id, "completed")

        except Exception as e:
            logger.exception(f"Talking photo pipeline error for job {job_id}: {e}")
            job_storage.set_job_status(
                job_id,
                JobState.FAILED,
                stage="error",
                error_message=str(e)[:300],
            )
            job_storage.complete_task(job_id, "failed")
            if bot:
                try:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=f"❌ ការបង្កើតវីដេអូរូបថតនិយាយបានជួបបញ្ហា៖\n`{str(e)[:200]}`",
                    )
                except Exception:
                    pass

talking_photo_pipeline = TalkingPhotoPipeline()
