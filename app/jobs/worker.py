"""Background worker queue for preview and final video rendering."""
import asyncio
import logging
from typing import Any
from aiogram import Bot
from app.config import config
from app.domain.states import JobState
from app.domain.features import QueueTask, JobFeature
from app.features.registry import feature_registry
from app.jobs.processes import kill_process_tree
from app.storage.jobs import job_storage

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

    def get_bot(self) -> Bot | None:
        return self.bot

    def register_pid(self, job_id: str, pid: int) -> None:
        self._active_pids[job_id] = pid

    def pop_pid(self, job_id: str) -> int | None:
        return self._active_pids.pop(job_id, None)

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
                task_data = self.storage.claim_next_task()
                if not task_data:
                    await asyncio.sleep(0.5)
                    continue

                job_id = task_data["job_id"]
                revision_id = task_data["revision_id"]
                task_type = task_data["task_type"]
                feature = task_data.get("feature") or JobFeature.VIDEO_VOICEOVER.value
                input_digest = task_data.get("input_digest")

                # Check if already cancelled
                if self.is_cancelled(job_id):
                    self.storage.complete_task(job_id, "cancelled")
                    continue

                await self._process_task(
                    job_id=job_id,
                    revision_id=revision_id,
                    task_type=task_type,
                    feature=feature,
                    input_digest=input_digest,
                )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"Unhandled error in worker {worker_id}: {e}")
                await asyncio.sleep(1.0)

    async def _process_task(
        self,
        job_id: str,
        revision_id: int,
        task_type: str,
        feature: str = JobFeature.VIDEO_VOICEOVER.value,
        input_digest: str | None = None,
    ) -> None:
        job = self.storage.get_job(job_id)
        if not job:
            logger.error(f"Cannot process task {task_type} for missing job {job_id}")
            self.storage.complete_task(job_id, "failed")
            return

        if self.is_cancelled(job_id):
            self.storage.complete_task(job_id, "cancelled")
            return

        job_feature = getattr(job, "feature", None) or feature or JobFeature.VIDEO_VOICEOVER.value
        task = QueueTask(
            job_id=job_id,
            revision_id=revision_id,
            feature=job_feature,
            task_type=task_type,
            user_id=job.user_id,
            input_digest=input_digest,
        )

        try:
            pipeline = feature_registry.get(job_feature)
            pipeline.validate_task_type(task_type)
            await pipeline.run(task, self)
        except Exception as e:
            logger.exception(f"Error executing pipeline {job_feature} for job {job_id}: {e}")
            self.storage.set_job_status(job_id, JobState.FAILED, error_message=str(e)[:300])
            self.storage.complete_task(job_id, "failed")
        finally:
            self._active_pids.pop(job_id, None)

worker_pool = WorkerPool()
