"""Background worker queue for preview and final video rendering."""
import asyncio
import logging
from pathlib import Path
from typing import Any
from aiogram import Bot
from aiogram.types import FSInputFile
from app.config import config
from app.domain.states import JobState
from app.domain.models import Job, Revision
from app.jobs.processes import kill_process_tree
from app.storage.jobs import job_storage
from app.storage.workspaces import workspace
from app.ui import texts_km as texts
from app.ui.keyboards import video_preview_review_keyboard

logger = logging.getLogger(__name__)

class WorkerPool:
    def __init__(self, bot: Bot | None = None, concurrency: int | None = None, storage=None):
        self.bot = bot
        self.concurrency = concurrency or config.max_concurrent_jobs
        self.storage = storage or job_storage
        self._tasks: list[asyncio.Task] = []
        self._running = False
        self._active_pids: dict[str, int] = {}
        self._cancelled_jobs: set[str] = set()

    def set_bot(self, bot: Bot) -> None:
        self.bot = bot

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        for i in range(self.concurrency):
            t = asyncio.create_task(self._worker_loop(i), name=f"render-worker-{i}")
            self._tasks.append(t)
        logger.info(f"WorkerPool started with concurrency={self.concurrency}")

    async def stop(self) -> None:
        self._running = False
        for pid in list(self._active_pids.values()):
            try:
                kill_process_tree(pid)
            except Exception:
                pass
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("WorkerPool stopped.")

    def cancel_job(self, job_id: str) -> bool:
        """Flag job as cancelled and terminate running subprocess tree immediately."""
        self._cancelled_jobs.add(job_id)
        self.storage.cancel_task(job_id)
        self.storage.set_job_status(job_id, JobState.CANCELLED)

        pid = self._active_pids.get(job_id)
        if pid:
            logger.info(f"Killing process tree for cancelled job {job_id} (PID: {pid})")
            kill_process_tree(pid)
            self._active_pids.pop(job_id, None)
            return True
        return True

    def is_cancelled(self, job_id: str) -> bool:
        return job_id in self._cancelled_jobs

    async def _worker_loop(self, worker_id: int) -> None:
        logger.info(f"Worker {worker_id} started loop.")
        while self._running:
            try:
                task_data = job_storage.claim_next_task()
                if not task_data:
                    await asyncio.sleep(0.5)
                    continue

                job_id = task_data["job_id"]
                revision_id = task_data["revision_id"]
                task_type = task_data["task_type"]

                # Check if already cancelled
                if self.is_cancelled(job_id):
                    job_storage.complete_task(job_id, "cancelled")
                    continue

                await self._process_task(job_id, revision_id, task_type)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"Unhandled error in worker {worker_id}: {e}")
                await asyncio.sleep(1.0)

    async def _process_task(self, job_id: str, revision_id: int, task_type: str) -> None:
        from app.services.previews import render_preview_video
        from app.services.render import render_video, RenderCancelledError
        from app.services.delivery import deliver_final_video

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

        if not source_path or not voice_path:
            logger.error(f"Missing media paths for job {job_id}")
            job_storage.set_job_status(job_id, JobState.FAILED, error_message="Missing source or audio files.")
            job_storage.complete_task(job_id, "failed")
            return

        def on_pid(pid: int) -> None:
            self._active_pids[job_id] = pid

        mode = revision.mode or (job.mode if job else "free_narration")
        cancel_check = lambda: self.is_cancelled(job_id)

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

                if self.bot and preview_dest.exists():
                    video_input = FSInputFile(str(preview_dest), filename="preview.mp4")
                    await self.bot.send_video(
                        chat_id=chat_id,
                        video=video_input,
                        caption=texts.PREVIEW_REVIEW_PROMPT,
                        reply_markup=video_preview_review_keyboard(job_id, revision_id),
                        supports_streaming=True,
                    )

            elif task_type == "final":
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
                if self.bot and rev_updated:
                    await deliver_final_video(self.bot, chat_id, job_id, rev_updated)

        except RenderCancelledError:
            logger.info(f"Job {job_id} was successfully cancelled.")
            job_storage.set_job_status(job_id, JobState.CANCELLED)
            job_storage.complete_task(job_id, "cancelled")
            if self.bot:
                try:
                    await self.bot.send_message(chat_id, texts.JOB_CANCELLED)
                except Exception:
                    pass

        except Exception as e:
            logger.exception(f"Error rendering job {job_id}: {e}")
            job_storage.set_job_status(job_id, JobState.FAILED, error_message=str(e))
            job_storage.complete_task(job_id, "failed")
            if self.bot and not cancel_check():
                try:
                    await self.bot.send_message(chat_id, texts.JOB_FAILED.format(error=str(e)))
                except Exception:
                    pass
        finally:
            self._active_pids.pop(job_id, None)

worker_pool = WorkerPool()
