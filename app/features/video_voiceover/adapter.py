import logging
from typing import Any
from aiogram.types import FSInputFile
from app.config import config
from app.domain.features import QueueTask
from app.domain.states import JobState
from app.storage.jobs import job_storage
from app.storage.workspaces import workspace
from app.ui import texts_km as texts
from app.ui.keyboards import video_preview_review_keyboard

logger = logging.getLogger(__name__)

class VideoVoiceoverPipeline:
    def validate_task_type(self, task_type: str) -> None:
        if task_type not in ("preview", "final"):
            raise ValueError(f"Unsupported task_type '{task_type}' for video_voiceover pipeline.")

    async def run(self, task: QueueTask, worker_pool: Any) -> None:
        from app.services.previews import render_preview_video
        from app.services.render import render_video, RenderCancelledError
        from app.services.delivery import deliver_final_video

        job_id = task.job_id
        revision_id = task.revision_id
        task_type = task.task_type

        job = job_storage.get_job(job_id)
        revision = job_storage.get_revision(job_id, revision_id)

        if not job or not revision:
            logger.error(f"Cannot process task {task_type} for missing job {job_id} / rev {revision_id}")
            job_storage.complete_task(job_id, "failed")
            return

        chat_id = job.chat_id
        source_path = job.source_path
        voice_path = revision.audio_path
        ass_path = revision.subtitles_ass
        settings = revision.settings
        duration = revision.audio_duration
        bot = worker_pool.get_bot()

        if not source_path or not voice_path:
            logger.error(f"Missing media paths for job {job_id}")
            job_storage.set_job_status(job_id, JobState.FAILED, error_message="Missing source or audio files.")
            job_storage.complete_task(job_id, "failed")
            return

        def on_pid(pid: int) -> None:
            worker_pool.register_pid(job_id, pid)

        mode = revision.mode or (job.mode if job else "free_narration")
        cancel_check = lambda: worker_pool.is_cancelled(job_id)

        try:
            if task_type == "preview":
                job_storage.set_job_status(job_id, JobState.PREVIEW_RENDERING)
                preview_dest = workspace.get_preview_video_path(job_id, revision_id)

                preview_start_time = 0.0
                if mode == "source_timed":
                    from app.storage.dubbing import load_dubbing_plan
                    plan = load_dubbing_plan(job_id, revision_id)
                    if plan and plan.placements:
                        first_ms = plan.placements[0].timeline_start_ms
                        preview_start_time = max(0.0, (first_ms / 1000.0) - 0.5)

                await render_preview_video(
                    source_path=source_path,
                    voice_audio_path=voice_path,
                    output_preview_path=preview_dest,
                    settings=settings,
                    target_duration=duration,
                    subtitles_ass_path=ass_path,
                    preview_duration=5.0,
                    timeout_seconds=float(config.subprocess_timeout_seconds),
                    cancel_check=cancel_check,
                    on_pid=on_pid,
                    mode=mode,
                    start_time=preview_start_time,
                )

                if cancel_check():
                    job_storage.complete_task(job_id, "cancelled")
                    return

                job_storage.update_revision(job_id, revision_id, preview_path=str(preview_dest))
                job_storage.set_job_status(job_id, JobState.AWAITING_APPROVAL)
                job_storage.complete_task(job_id, "completed")

                if bot and preview_dest.exists():
                    video_input = FSInputFile(str(preview_dest), filename="preview.mp4")
                    await bot.send_video(
                        chat_id=chat_id,
                        video=video_input,
                        caption=texts.PREVIEW_REVIEW_PROMPT,
                        reply_markup=video_preview_review_keyboard(job_id, revision_id),
                        supports_streaming=True,
                    )

            elif task_type == "final":
                if mode == "source_timed":
                    from app.storage.dubbing import load_dubbing_plan
                    from app.services.content_coverage import validate_content_coverage
                    plan = load_dubbing_plan(job_id, revision_id)
                    if not plan or plan.has_blocking_issues:
                        logger.error(f"Cannot render final for job {job_id}: plan has unresolved blocking issues.")
                        job_storage.set_job_status(job_id, JobState.FAILED, error_message="Unresolved blocking issues exist.")
                        job_storage.complete_task(job_id, "failed")
                        return

                    coverage_issues = validate_content_coverage(plan, settings, require_clips_and_placements=True)
                    if coverage_issues:
                        logger.error(f"Cannot render final for job {job_id}: coverage validation failed: {coverage_issues[0].message}")
                        job_storage.set_job_status(job_id, JobState.FAILED, error_message=coverage_issues[0].message)
                        job_storage.complete_task(job_id, "failed")
                        return

                    if plan.speaker_mode == "multi" and plan.full_preview_approved_digest:
                        from app.services.speaker_review import compute_plan_content_digest
                        current_digest = compute_plan_content_digest(plan, settings)
                        if plan.full_preview_approved_digest != current_digest:
                            logger.error(f"Cannot render final for job {job_id}: approved digest mismatch (plan modified after approval).")
                            job_storage.set_job_status(job_id, JobState.FAILED, error_message="Plan was modified after preview approval.")
                            job_storage.complete_task(job_id, "failed")
                            return

                job_storage.set_job_status(job_id, JobState.RENDERING)
                final_dest = workspace.get_final_video_path(job_id, revision_id)

                await render_video(
                    source_path=source_path,
                    voice_audio_path=voice_path,
                    output_path=final_dest,
                    settings=settings,
                    target_duration=duration,
                    subtitles_ass_path=ass_path,
                    is_preview=False,
                    timeout_seconds=float(config.subprocess_timeout_seconds),
                    cancel_check=cancel_check,
                    on_pid=on_pid,
                    mode=mode,
                )

                if cancel_check():
                    job_storage.complete_task(job_id, "cancelled")
                    return

                job_storage.update_revision(job_id, revision_id, final_path=str(final_dest))
                job_storage.complete_task(job_id, "completed")

                # Re-fetch updated revision for delivery
                rev_updated = job_storage.get_revision(job_id, revision_id)
                if bot and rev_updated:
                    await deliver_final_video(bot, chat_id, job_id, rev_updated)

        except RenderCancelledError:
            logger.info(f"Job {job_id} was successfully cancelled.")
            job_storage.set_job_status(job_id, JobState.CANCELLED)
            job_storage.complete_task(job_id, "cancelled")
            if bot:
                try:
                    await bot.send_message(chat_id, texts.JOB_CANCELLED)
                except Exception:
                    pass

        except Exception as e:
            logger.exception(f"Error rendering job {job_id}: {e}")
            job_storage.set_job_status(job_id, JobState.FAILED, error_message=str(e))
            job_storage.complete_task(job_id, "failed")
            if bot and not cancel_check():
                try:
                    await bot.send_message(chat_id, texts.JOB_FAILED.format(error=str(e)))
                except Exception:
                    pass

video_voiceover_pipeline = VideoVoiceoverPipeline()
