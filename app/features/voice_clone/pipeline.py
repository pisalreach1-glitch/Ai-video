"""Synthesis pipeline for Voice Cloning."""
import logging
from pathlib import Path
from typing import Any
from aiogram.types import FSInputFile
from app.domain.features import QueueTask
from app.domain.states import JobState
from app.storage.jobs import job_storage
from app.storage.workspaces import workspace
from app.jobs.gpu_scheduler import gpu_scheduler
from app.features.voice_clone.storage import voice_clone_storage
from app.features.voice_clone.domain import CloneRequest
from app.features.voice_clone.backends import get_voice_clone_backend
from app.features.voice_clone.assembly import create_telegram_playback_audio
from app.features.voice_clone.keyboards import vc_review_keyboard

logger = logging.getLogger(__name__)

class VoiceClonePipeline:
    def validate_task_type(self, task_type: str) -> None:
        if task_type != "clone_synthesis":
            raise ValueError(f"Unsupported task_type '{task_type}' for voice_clone pipeline.")

    async def run(self, task: QueueTask, worker_pool: Any) -> None:
        job_id = task.job_id
        artifact_id = task.payload.get("artifact_id") or task.task_id
        job = job_storage.get_job(job_id)
        artifact = voice_clone_storage.get_artifact(artifact_id)

        if not job or not artifact:
            logger.error(f"Missing job {job_id} or voice clone artifact {artifact_id}")
            job_storage.complete_task(job_id, "failed")
            return

        reference = voice_clone_storage.get_reference(artifact.reference_id)
        if not reference:
            logger.error(f"Missing voice reference {artifact.reference_id} for artifact {artifact_id}")
            voice_clone_storage.update_artifact_failed(artifact_id, "missing_reference")
            job_storage.complete_task(job_id, "failed")
            return

        chat_id = job.chat_id
        bot = worker_pool.get_bot()
        cancel_check = lambda: worker_pool.is_cancelled(job_id)

        def on_pid(pid: int) -> None:
            worker_pool.register_pid(job_id, pid)

        # Artifact workspace
        art_output_dir = Path("runtime") / "jobs" / job_id / "voice_clone" / "artifacts" / artifact_id
        art_output_dir.mkdir(parents=True, exist_ok=True)

        req = CloneRequest(
            artifact_id=artifact_id,
            owner_user_id=job.user_id,
            reference_wav=Path(reference.wav_path),
            reference_sha256=reference.sha256,
            text=artifact.text,
            language=artifact.language,
            output_dir=art_output_dir,
            model_version=artifact.model_version,
            settings_digest=artifact.request_digest,
            reference_text=artifact.reference_text or reference.reference_text,
        )

        job_storage.set_job_status(job_id, JobState.RENDERING, stage="voice_clone_synthesizing")

        try:
            # Shared GPU lease during model inference
            backend = get_voice_clone_backend()
            async with gpu_scheduler.acquire(tag="voice_clone", job_id=job_id):
                out = await backend.synthesize(
                    req,
                    cancel_check=cancel_check,
                    on_pid=on_pid,
                )

            if cancel_check():
                job_storage.set_job_status(job_id, JobState.CANCELLED, error_message="Synthesis cancelled.")
                voice_clone_storage.update_artifact_failed(artifact_id, "cancelled")
                job_storage.complete_task(job_id, "cancelled")
                return

            # Update artifact status in storage
            voice_clone_storage.update_artifact_completed(
                artifact_id=artifact_id,
                wav_path=str(out.wav_path),
                wav_sha256=out.sha256,
                duration_seconds=out.duration_seconds,
                manifest_path=str(out.manifest_path),
            )

            job_storage.set_job_status(job_id, JobState.AWAITING_APPROVAL, stage="voice_clone_review")
            job_storage.complete_task(job_id, "completed")

            # Deliver playback audio to user
            if bot:
                playback_dest = art_output_dir / "playback.m4a"
                playback_file = await create_telegram_playback_audio(
                    master_wav=out.wav_path,
                    output_audio=playback_dest,
                    cancel_check=cancel_check,
                )
                caption = (
                    f"🔊 **សំឡេង Clone របស់អ្នកត្រូវបានបង្កើតជោគជ័យ!**\n\n"
                    f"• រយៈពេលសំឡេង៖ {out.duration_seconds:.1f} វិនាទី\n"
                    f"• អត្ថបទ៖ «{artifact.text[:80]}{'...' if len(artifact.text) > 80 else ''}»\n\n"
                    f"សូមស្តាប់សំឡេងខាងលើផ្ទៀងផ្ទាត់។ ប្រសិនបើពេញចិត្ត សូមចុច «✅ អនុម័តសំឡេង» ដើម្បីបន្តទៅកាន់ការបង្កើត Talking Photo។"
                )
                await bot.send_audio(
                    chat_id=chat_id,
                    audio=FSInputFile(str(playback_file)),
                    caption=caption,
                    reply_markup=vc_review_keyboard(job_id, artifact_id),
                )

        except Exception as e:
            logger.exception(f"Voice clone synthesis pipeline error for job {job_id}: {e}")
            voice_clone_storage.update_artifact_failed(artifact_id, str(e))
            job_storage.set_job_status(job_id, JobState.FAILED, error_message=str(e))
            job_storage.complete_task(job_id, "failed")
            if bot:
                await bot.send_message(
                    chat_id=chat_id,
                    text=f"❌ **ការបង្កើតសំឡេង Clone បានជួបបញ្ហា៖**\n{e}\n\n"
                         f"💡 លោកអ្នកអាចជ្រើសរើស «🎤 ប្រើសំឡេងថតផ្ទាល់» (Recorded Voice) ជំនួសវិញ។",
                )

voice_clone_pipeline = VoiceClonePipeline()
