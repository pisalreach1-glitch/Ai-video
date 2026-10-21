"""Atomic job, revision, and queue storage operations."""
import json
import time
import uuid
from typing import Any
from app.domain.models import Job, Revision, VoiceSettings, MediaInfo
from app.domain.states import JobState
from app.storage.database import get_db

class JobStorage:
    def __init__(self, db=None):
        self.db = db or get_db()

    def create_job(
        self,
        user_id: int,
        chat_id: int,
        source_type: str = "upload",
        source_url: str | None = None,
    ) -> Job:
        job_id = str(uuid.uuid4())
        now = time.time()
        job = Job(
            job_id=job_id,
            user_id=user_id,
            chat_id=chat_id,
            source_type=source_type,
            source_url=source_url,
            status=JobState.AWAITING_SOURCE,
            stage="init",
            current_revision_id=1,
            created_at=now,
            updated_at=now,
        )

        conn = self.db.get_connection()
        conn.execute(
            """
            INSERT INTO jobs (
                job_id, user_id, chat_id, source_type, source_path, source_url,
                source_media_info, status, stage, current_revision_id,
                duration_policy, error_message, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job.job_id,
                job.user_id,
                job.chat_id,
                job.source_type,
                job.source_path,
                job.source_url,
                None,
                job.status.value,
                job.stage,
                job.current_revision_id,
                job.duration_policy,
                job.error_message,
                job.created_at,
                job.updated_at,
            )
        )
        return job

    def get_job(self, job_id: str) -> Job | None:
        conn = self.db.get_connection()
        row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if not row:
            return None
        return Job.from_dict(dict(row))

    def verify_ownership(self, job_id: str, user_id: int, chat_id: int) -> bool:
        job = self.get_job(job_id)
        if not job:
            return False
        return job.user_id == user_id and job.chat_id == chat_id

    def set_job_status(
        self,
        job_id: str,
        status: JobState,
        stage: str | None = None,
        error_message: str | None = None,
    ) -> None:
        conn = self.db.get_connection()
        now = time.time()
        if stage is not None:
            conn.execute(
                """
                UPDATE jobs
                SET status = ?, stage = ?, error_message = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (status.value, stage, error_message, now, job_id)
            )
        else:
            conn.execute(
                """
                UPDATE jobs
                SET status = ?, error_message = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (status.value, error_message, now, job_id)
            )

    def set_job_source(
        self,
        job_id: str,
        source_path: str,
        media_info: MediaInfo,
        source_url: str | None = None
    ) -> None:
        conn = self.db.get_connection()
        now = time.time()
        media_info_json = json.dumps(media_info.to_dict())
        conn.execute(
            """
            UPDATE jobs
            SET source_path = ?, source_media_info = ?, source_url = COALESCE(?, source_url), updated_at = ?
            WHERE job_id = ?
            """,
            (source_path, media_info_json, source_url, now, job_id)
        )

    def set_duration_policy(self, job_id: str, policy: str) -> None:
        conn = self.db.get_connection()
        now = time.time()
        conn.execute(
            "UPDATE jobs SET duration_policy = ?, updated_at = ? WHERE job_id = ?",
            (policy, now, job_id)
        )

    # ---------------- Revision Operations ----------------
    def create_revision(
        self,
        job_id: str,
        narration_text: str,
        settings: VoiceSettings,
        audio_path: str | None = None,
        audio_duration: float = 0.0,
        subtitles_srt: str | None = None,
    ) -> Revision:
        conn = self.db.get_connection()
        now = time.time()
        row = conn.execute(
            "SELECT COALESCE(MAX(revision_id), 0) + 1 AS next_rev FROM revisions WHERE job_id = ?",
            (job_id,)
        ).fetchone()
        next_rev = row["next_rev"]

        settings_json = json.dumps(settings.to_dict(), ensure_ascii=False)
        conn.execute(
            """
            INSERT INTO revisions (
                job_id, revision_id, narration_text, settings,
                audio_path, audio_duration, subtitles_srt, subtitles_ass,
                preview_path, final_path, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                next_rev,
                narration_text,
                settings_json,
                audio_path,
                audio_duration,
                subtitles_srt,
                None,
                None,
                None,
                now,
            )
        )

        conn.execute(
            "UPDATE jobs SET current_revision_id = ?, updated_at = ? WHERE job_id = ?",
            (next_rev, now, job_id)
        )

        return Revision(
            revision_id=next_rev,
            job_id=job_id,
            narration_text=narration_text,
            settings=settings,
            audio_path=audio_path,
            audio_duration=audio_duration,
            subtitles_srt=subtitles_srt,
            created_at=now,
        )

    def get_revision(self, job_id: str, revision_id: int) -> Revision | None:
        conn = self.db.get_connection()
        row = conn.execute(
            "SELECT * FROM revisions WHERE job_id = ? AND revision_id = ?",
            (job_id, revision_id)
        ).fetchone()
        if not row:
            return None
        return Revision.from_dict(dict(row))

    def get_latest_revision(self, job_id: str) -> Revision | None:
        conn = self.db.get_connection()
        row = conn.execute(
            "SELECT * FROM revisions WHERE job_id = ? ORDER BY revision_id DESC LIMIT 1",
            (job_id,)
        ).fetchone()
        if not row:
            return None
        return Revision.from_dict(dict(row))

    def update_revision(self, job_id: str, revision_id: int, **kwargs: Any) -> None:
        conn = self.db.get_connection()
        updates = []
        params = []
        for key, value in kwargs.items():
            if key == "settings" and isinstance(value, VoiceSettings):
                updates.append(f"{key} = ?")
                params.append(json.dumps(value.to_dict(), ensure_ascii=False))
            else:
                updates.append(f"{key} = ?")
                params.append(value)
        if not updates:
            return

        params.extend([job_id, revision_id])
        query = f"UPDATE revisions SET {', '.join(updates)} WHERE job_id = ? AND revision_id = ?"
        conn.execute(query, tuple(params))

    # ---------------- Queue Operations ----------------
    def enqueue_task(
        self,
        job_id: str,
        revision_id: int,
        user_id: int,
        task_type: str, # "preview" | "final"
    ) -> bool:
        conn = self.db.get_connection()
        now = time.time()
        try:
            conn.execute(
                """
                INSERT INTO render_queue (
                    job_id, revision_id, user_id, task_type, status, enqueued_at, retry_count
                ) VALUES (?, ?, ?, ?, 'queued', ?, 0)
                ON CONFLICT(job_id) DO UPDATE SET
                    revision_id = excluded.revision_id,
                    task_type = excluded.task_type,
                    status = 'queued',
                    enqueued_at = excluded.enqueued_at
                """,
                (job_id, revision_id, user_id, task_type, now)
            )
            return True
        except Exception:
            return False

    def claim_next_task(self) -> dict[str, Any] | None:
        """Atomically claim the next queued task in a transaction."""
        with self.db.transaction() as conn:
            row = conn.execute(
                """
                SELECT job_id, revision_id, user_id, task_type, enqueued_at
                FROM render_queue
                WHERE status = 'queued'
                ORDER BY enqueued_at ASC
                LIMIT 1
                """
            ).fetchone()

            if not row:
                return None

            now = time.time()
            conn.execute(
                """
                UPDATE render_queue
                SET status = 'processing', started_at = ?
                WHERE job_id = ? AND status = 'queued'
                """,
                (now, row["job_id"])
            )
            return dict(row)

    def complete_task(self, job_id: str, status: str = "completed") -> None:
        conn = self.db.get_connection()
        now = time.time()
        conn.execute(
            """
            UPDATE render_queue
            SET status = ?, completed_at = ?
            WHERE job_id = ?
            """,
            (status, now, job_id)
        )

    def cancel_task(self, job_id: str) -> None:
        conn = self.db.get_connection()
        now = time.time()
        conn.execute(
            """
            UPDATE render_queue
            SET status = 'cancelled', completed_at = ?
            WHERE job_id = ?
            """,
            (now, job_id)
        )

    def get_queue_size(self) -> int:
        conn = self.db.get_connection()
        row = conn.execute("SELECT COUNT(*) AS cnt FROM render_queue WHERE status = 'queued'").fetchone()
        return row["cnt"] if row else 0

    def count_active_jobs_for_user(self, user_id: int) -> int:
        conn = self.db.get_connection()
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM render_queue WHERE user_id = ? AND status IN ('queued', 'processing')",
            (user_id,)
        ).fetchone()
        return row["cnt"] if row else 0

    def recover_interrupted_jobs(self) -> int:
        """
        Recover tasks stuck in processing/queued states from an unexpected bot shutdown.
        Transitions stuck render_queue tasks to 'interrupted' and corresponding jobs to INTERRUPTED.
        Returns the number of jobs recovered.
        """
        conn = self.db.get_connection()
        now = time.time()

        # 1. Recover any tasks stuck in the render_queue
        rows = conn.execute(
            "SELECT job_id, task_type FROM render_queue WHERE status IN ('processing', 'queued')"
        ).fetchall()

        count = 0
        for r in rows:
            job_id = r["job_id"]
            task_type = r["task_type"]
            conn.execute(
                "UPDATE render_queue SET status = 'interrupted', completed_at = ? WHERE job_id = ?",
                (now, job_id)
            )
            interrupted_stage = f"interrupted:{task_type}_render"
            conn.execute(
                """
                UPDATE jobs
                SET status = ?, stage = ?, error_message = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (JobState.INTERRUPTED.value, interrupted_stage, "Server restarted while task was processing.", now, job_id)
            )
            count += 1

        # 2. Recover any jobs that were in transient states when the server stopped
        transient_states = (
            JobState.DOWNLOADING.value,
            JobState.GENERATING_AUDIO.value,
            JobState.PREVIEW_QUEUED.value,
            JobState.PREVIEW_RENDERING.value,
            JobState.FINAL_QUEUED.value,
            JobState.RENDERING.value,
            JobState.UPLOADING.value,
        )
        placeholders = ",".join("?" for _ in transient_states)
        stuck_jobs = conn.execute(
            f"SELECT job_id, status FROM jobs WHERE status IN ({placeholders})",
            transient_states
        ).fetchall()

        for r in stuck_jobs:
            old_status = r["status"]
            interrupted_stage = f"interrupted:{old_status}"
            conn.execute(
                """
                UPDATE jobs
                SET status = ?, stage = ?, error_message = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (JobState.INTERRUPTED.value, interrupted_stage, "Server restarted while task was processing.", now, r["job_id"])
            )
            count += 1

        return count

    # ---------------- History & Active Jobs ----------------
    def get_user_active_job(self, user_id: int, chat_id: int) -> Job | None:
        conn = self.db.get_connection()
        active_statuses = (
            JobState.AWAITING_SOURCE.value,
            JobState.AWAITING_URL.value,
            JobState.DOWNLOADING.value,
            JobState.AWAITING_TEXT.value,
            JobState.AWAITING_SETTINGS.value,
            JobState.AUDIO_QUEUED.value,
            JobState.GENERATING_AUDIO.value,
            JobState.AWAITING_AUDIO_REVIEW.value,
            JobState.AWAITING_DURATION_CHOICE.value,
            JobState.PREVIEW_QUEUED.value,
            JobState.PREVIEW_RENDERING.value,
            JobState.AWAITING_APPROVAL.value,
            JobState.FINAL_QUEUED.value,
            JobState.RENDERING.value,
            JobState.UPLOADING.value,
            JobState.DELIVERY_FAILED.value,
            JobState.INTERRUPTED.value,
        )
        placeholders = ",".join("?" for _ in active_statuses)
        row = conn.execute(
            f"""
            SELECT * FROM jobs
            WHERE user_id = ? AND chat_id = ? AND status IN ({placeholders})
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (user_id, chat_id, *active_statuses)
        ).fetchone()
        if not row:
            return None
        return Job.from_dict(dict(row))

    def list_user_jobs(
        self,
        user_id: int,
        limit: int = 5,
        offset: int = 0
    ) -> tuple[list[Job], int]:
        conn = self.db.get_connection()
        count_row = conn.execute(
            "SELECT COUNT(*) AS total FROM jobs WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        total = count_row["total"] if count_row else 0

        rows = conn.execute(
            """
            SELECT * FROM jobs
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            (user_id, limit, offset)
        ).fetchall()
        jobs = [Job.from_dict(dict(r)) for r in rows]
        return jobs, total

job_storage = JobStorage()
