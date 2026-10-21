"""
Job and Queue Manager for Video Bot.
Provides:
- User isolation: Isolated directory per job, ensuring users' videos/subtitles never mix.
- Callback isolation: Old callbacks from previous jobs are rejected and cannot edit newer jobs.
- Queue management: Capacity limits and per-user concurrency limits.
- Cancellation: Real cancellation stopping running FFmpeg/Node process trees.
- Status reporting: Responsive /status queries while background rendering is running.
"""

import os
import time
import uuid
import logging
import asyncio
import threading
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Any

from errors import BotProcessingError, JobCancelledError
from process_runner import kill_process_tree

logger = logging.getLogger(__name__)

MAX_CONCURRENT_JOBS = int(os.getenv("MAX_CONCURRENT_JOBS", "2"))
MAX_USER_CONCURRENT_JOBS = int(os.getenv("MAX_USER_CONCURRENT_JOBS", "1"))
MAX_QUEUE_SIZE = int(os.getenv("MAX_QUEUE_SIZE", "10"))


@dataclass
class Job:
    job_id: str
    user_id: int
    chat_id: int
    job_dir: Path
    mode: str = "quick" # "quick" or "story"
    status: str = "queued" # "queued", "running", "completed", "failed", "cancelled"
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None

    input_path: str = ""
    output_path: str = ""
    clean_video_path: Optional[str] = None
    
    words: List[Dict[str, Any]] = field(default_factory=list)
    hook_title: str = ""
    detected_lang: str = "km"
    theme: str = "tiktok_viral"
    custom_font: Optional[str] = None
    bgm: str = "lofi"
    story_overlays: List[Dict[str, Any]] = field(default_factory=list)

    error_reason: Optional[str] = None
    error_detail: Optional[str] = None # Traceback for logs
    active_pid: Optional[int] = None

    cancel_event: threading.Event = field(default_factory=threading.Event)
    asyncio_task: Optional[asyncio.Task] = None

    def register_pid(self, pid: int) -> None:
        self.active_pid = pid
        logger.info(f"[Job {self.job_id}] Active PID registered: {pid}")

    def is_active(self) -> bool:
        return self.status in ("queued", "running")

    def duration_seconds(self) -> float:
        if self.started_at:
            end = self.finished_at or time.time()
            return round(end - self.started_at, 1)
        return 0.0


class JobQueueManager:
    """
    Thread-safe, non-blocking queue and job state manager.
    """

    def __init__(self, base_temp_dir: Path):
        self.base_temp_dir = Path(base_temp_dir).resolve()
        self.jobs_dir = self.base_temp_dir / "jobs"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)

        self._jobs: Dict[str, Job] = {} # job_id -> Job
        self._user_active_job: Dict[int, str] = {} # user_id -> active/last job_id
        self._lock = threading.Lock()

    def create_job(
        self,
        user_id: int,
        chat_id: int,
        input_filename: str = "input.mp4",
        mode: str = "quick"
    ) -> Job:
        """
        Creates a new job with user and filesystem isolation.
        Enforces per-user and queue capacity limits.
        """
        with self._lock:
            # 1. Per-user concurrency limit
            if user_id in self._user_active_job:
                prev_id = self._user_active_job[user_id]
                prev_job = self._jobs.get(prev_id)
                if prev_job and prev_job.is_active():
                    raise BotProcessingError(
                        f"អ្នកមានការងារមួយកំពុងដំណើរការរួចហើយ (Job ID: {prev_job.job_id})។ "
                        "សូមរង់ចាំឱ្យចប់ ឬវាយពាក្យបញ្ជា /cancel ដើម្បីបោះបង់វាជាមុនសិន។",
                        job_id=prev_job.job_id,
                        error_code="USER_JOB_LIMIT_EXCEEDED"
                    )

            # 2. Queue capacity limit
            active_count = sum(1 for j in self._jobs.values() if j.is_active())
            if active_count >= MAX_QUEUE_SIZE:
                raise BotProcessingError(
                    "ម៉ាស៊ីនបម្រើការ (Server Queue) កំពុងពេញសមត្ថភាពជាបណ្តោះអាសន្ន។ "
                    "សូមរង់ចាំពីរបីនាទី រួចផ្ញើវីដេអូម្តងទៀត។",
                    error_code="QUEUE_FULL"
                )

            # 3. Create unique isolated directory for this job
            short_id = f"job_{uuid.uuid4().hex[:8]}"
            job_folder = self.jobs_dir / short_id
            job_folder.mkdir(parents=True, exist_ok=True)

            input_path = str(job_folder / input_filename)
            output_path = str(job_folder / f"rendered_{short_id}.mp4")

            job = Job(
                job_id=short_id,
                user_id=user_id,
                chat_id=chat_id,
                job_dir=job_folder,
                mode=mode,
                status="queued",
                input_path=input_path,
                output_path=output_path
            )

            self._jobs[short_id] = job
            self._user_active_job[user_id] = short_id
            logger.info(f"Created isolated job {short_id} for user {user_id} in {job_folder}")
            return job

    def get_job(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def get_user_job(self, user_id: int) -> Optional[Job]:
        with self._lock:
            job_id = self._user_active_job.get(user_id)
            if job_id:
                return self._jobs.get(job_id)
            return None

    def validate_callback(self, user_id: int, callback_job_id: Optional[str]) -> bool:
        """
        Guarantees isolation:
        Verifies that the callback action belongs to the user's active/current job.
        If callback_job_id is from an older job, rejects it to prevent cross-job contamination.
        """
        with self._lock:
            if not callback_job_id:
                return True # Legacy callbacks without ID are handled conditionally

            current_id = self._user_active_job.get(user_id)
            if current_id != callback_job_id:
                logger.warning(
                    f"Callback isolation rejection: user {user_id} triggered callback for {callback_job_id}, "
                    f"but active job is {current_id}"
                )
                return False
            return True

    def cancel_job(self, user_id: int, job_id: Optional[str] = None) -> Optional[Job]:
        """
        Cancels active or queued job for user.
        Terminates the running FFmpeg/Node process tree immediately!
        """
        target_job: Optional[Job] = None
        with self._lock:
            if job_id:
                target_job = self._jobs.get(job_id)
            else:
                current_id = self._user_active_job.get(user_id)
                if current_id:
                    target_job = self._jobs.get(current_id)

            if not target_job or not target_job.is_active():
                return None

            # Mark cancelled
            target_job.status = "cancelled"
            target_job.finished_at = time.time()
            target_job.cancel_event.set()

        # Outside lock: stop process tree and task
        if target_job.active_pid:
            logger.info(f"[Job {target_job.job_id}] Killing process tree for PID {target_job.active_pid}")
            kill_process_tree(target_job.active_pid)

        if target_job.asyncio_task and not target_job.asyncio_task.done():
            target_job.asyncio_task.cancel()

        logger.info(f"[Job {target_job.job_id}] Successfully cancelled by user {user_id}")
        return target_job

    def reset_user_session(self, user_id: int) -> Optional[Job]:
        """
        Clears the user's active job session (used by /new command).
        If job is running, cancels it first.
        """
        cancelled_job = self.cancel_job(user_id)
        with self._lock:
            self._user_active_job.pop(user_id, None)
        return cancelled_job

    def get_active_job_ids(self) -> Set[str]:
        """Returns set of all job IDs currently queued or running."""
        with self._lock:
            return {j.job_id for j in self._jobs.values() if j.is_active()}

    def get_status_summary(self, user_id: int) -> Dict[str, Any]:
        """
        Non-blocking status check for /status command.
        """
        with self._lock:
            user_job = None
            job_id = self._user_active_job.get(user_id)
            if job_id:
                user_job = self._jobs.get(job_id)

            queued_jobs = [j for j in self._jobs.values() if j.status == "queued"]
            running_jobs = [j for j in self._jobs.values() if j.status == "running"]

            user_queue_pos = -1
            if user_job and user_job.status == "queued":
                try:
                    user_queue_pos = queued_jobs.index(user_job) + 1
                except ValueError:
                    user_queue_pos = 1

            return {
                "user_job": user_job,
                "user_queue_position": user_queue_pos,
                "total_queued": len(queued_jobs),
                "total_running": len(running_jobs),
                "max_concurrent": MAX_CONCURRENT_JOBS,
                "max_queue": MAX_QUEUE_SIZE
            }
