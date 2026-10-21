"""
SQLite database persistence for Video Bot.
Provides:
- Persistent wizard sessions (mode -> upload -> style -> length -> review)
- Persistent processing jobs with full state history and revision tracking
- Startup recovery marking interrupted jobs
- Queue queries and per-user active job checks
"""

import os
import json
import time
import sqlite3
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

DB_PATH = Path(os.getenv("DB_PATH", "bot_data.sqlite")).resolve()

# Valid processing states
PROCESSING_STATES = [
    "queued",
    "analyzing",
    "planning",
    "generating",
    "validating",
    "preview_rendering",
    "awaiting_approval",
    "final_rendering",
    "uploading",
    "completed",
    "awaiting_manual_agent",
    "failed",
    "cancelled",
    "interrupted"
]

ACTIVE_PROCESSING_STATES = [
    "queued",
    "analyzing",
    "planning",
    "generating",
    "validating",
    "preview_rendering",
    "final_rendering",
    "uploading"
]


@dataclass
class WizardSession:
    user_id: int
    chat_id: int
    current_step: str = "mode" # 'mode', 'upload', 'style', 'length', 'review'
    mode: str = "quick"        # 'auto', 'quick', 'story', 'custom'
    input_path: Optional[str] = None
    original_filename: Optional[str] = None
    style_theme: str = "tiktok_viral"
    custom_font: Optional[str] = None
    bgm: str = "lofi"
    target_length: str = "auto" # 'auto', 'short_30s', 'medium_60s', 'full'
    custom_prompt: Optional[str] = None
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DbJob:
    job_id: str
    user_id: int
    chat_id: int
    revision_id: int = 1
    status: str = "queued"
    step_progress: float = 0.0
    mode: str = "quick"
    input_path: str = ""
    output_path: Optional[str] = None
    preview_path: Optional[str] = None
    job_dir: str = ""
    params: Dict[str, Any] = None
    error_reason: Optional[str] = None
    error_detail: Optional[str] = None
    retry_count: int = 0
    active_pid: Optional[int] = None
    created_at: float = 0.0
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    updated_at: float = 0.0

    def is_active(self) -> bool:
        return self.status in ACTIVE_PROCESSING_STATES


class DatabaseManager:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = Path(db_path).resolve()
        self.init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def init_db(self) -> None:
        """Initializes tables and indexes."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._get_connection() as conn:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS wizard_sessions (
                user_id INTEGER PRIMARY KEY,
                chat_id INTEGER NOT NULL,
                current_step TEXT NOT NULL DEFAULT 'mode',
                mode TEXT NOT NULL DEFAULT 'quick',
                input_path TEXT,
                original_filename TEXT,
                style_theme TEXT NOT NULL DEFAULT 'tiktok_viral',
                custom_font TEXT,
                bgm TEXT NOT NULL DEFAULT 'lofi',
                target_length TEXT NOT NULL DEFAULT 'auto',
                custom_prompt TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            """)

            conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                revision_id INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'queued',
                step_progress REAL NOT NULL DEFAULT 0.0,
                mode TEXT NOT NULL DEFAULT 'quick',
                input_path TEXT NOT NULL,
                output_path TEXT,
                preview_path TEXT,
                job_dir TEXT NOT NULL,
                params_json TEXT,
                error_reason TEXT,
                error_detail TEXT,
                retry_count INTEGER NOT NULL DEFAULT 0,
                active_pid INTEGER,
                created_at REAL NOT NULL,
                started_at REAL,
                finished_at REAL,
                updated_at REAL NOT NULL
            );
            """)

            conn.execute("""
            CREATE TABLE IF NOT EXISTS job_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                revision_id INTEGER NOT NULL,
                from_status TEXT,
                to_status TEXT,
                timestamp REAL NOT NULL,
                note TEXT,
                FOREIGN KEY (job_id) REFERENCES jobs (job_id) ON DELETE CASCADE
            );
            """)

            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_user ON jobs (user_id, status);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs (status);")
            conn.commit()

    def recover_interrupted_jobs(self) -> int:
        """
        On startup, identifies all unfinished in-progress jobs and marks them 'interrupted'.
        Guarantees that unfinished jobs are never marked completed and cannot hang.
        """
        now = time.time()
        placeholders = ",".join("?" for _ in ACTIVE_PROCESSING_STATES)
        with self._get_connection() as conn:
            cursor = conn.execute(
                f"""
                UPDATE jobs
                SET status = 'interrupted',
                    finished_at = ?,
                    updated_at = ?,
                    error_reason = 'Bot server restarted while job was in progress'
                WHERE status IN ({placeholders})
                """,
                [now, now] + ACTIVE_PROCESSING_STATES
            )
            count = cursor.rowcount
            if count > 0:
                logger.warning(f"Recovery: Marked {count} active jobs as 'interrupted'.")
            conn.commit()
            return count

    # -------------------------------------------------------------
    # WIZARD SESSION METHODS
    # -------------------------------------------------------------
    def get_or_create_wizard(self, user_id: int, chat_id: int) -> WizardSession:
        now = time.time()
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM wizard_sessions WHERE user_id = ?", (user_id,)).fetchone()
            if row:
                return WizardSession(
                    user_id=row["user_id"],
                    chat_id=row["chat_id"],
                    current_step=row["current_step"],
                    mode=row["mode"],
                    input_path=row["input_path"],
                    original_filename=row["original_filename"],
                    style_theme=row["style_theme"],
                    custom_font=row["custom_font"],
                    bgm=row["bgm"],
                    target_length=row["target_length"],
                    custom_prompt=row["custom_prompt"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"]
                )
            # Create new
            conn.execute(
                """
                INSERT INTO wizard_sessions (
                    user_id, chat_id, current_step, mode, input_path, original_filename,
                    style_theme, custom_font, bgm, target_length, custom_prompt, created_at, updated_at
                ) VALUES (?, ?, 'mode', 'quick', NULL, NULL, 'tiktok_viral', NULL, 'lofi', 'auto', NULL, ?, ?)
                """,
                (user_id, chat_id, now, now)
            )
            conn.commit()
            return WizardSession(user_id=user_id, chat_id=chat_id, created_at=now, updated_at=now)

    def update_wizard(self, user_id: int, **kwargs) -> WizardSession:
        allowed = {
            "chat_id", "current_step", "mode", "input_path", "original_filename",
            "style_theme", "custom_font", "bgm", "target_length", "custom_prompt"
        }
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        updates["updated_at"] = time.time()

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [user_id]

        with self._get_connection() as conn:
            conn.execute(f"UPDATE wizard_sessions SET {set_clause} WHERE user_id = ?", values)
            conn.commit()

        # Return updated
        return self.get_or_create_wizard(user_id, kwargs.get("chat_id", 0))

    def reset_wizard(self, user_id: int, chat_id: int) -> WizardSession:
        now = time.time()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO wizard_sessions (
                    user_id, chat_id, current_step, mode, input_path, original_filename,
                    style_theme, custom_font, bgm, target_length, custom_prompt, created_at, updated_at
                ) VALUES (?, ?, 'mode', 'quick', NULL, NULL, 'tiktok_viral', NULL, 'lofi', 'auto', NULL, ?, ?)
                """,
                (user_id, chat_id, now, now)
            )
            conn.commit()
        return WizardSession(user_id=user_id, chat_id=chat_id, created_at=now, updated_at=now)

    # -------------------------------------------------------------
    # JOB METHODS
    # -------------------------------------------------------------
    def _row_to_job(self, row: sqlite3.Row) -> DbJob:
        params = {}
        if row["params_json"]:
            try:
                params = json.loads(row["params_json"])
            except Exception:
                params = {}

        return DbJob(
            job_id=row["job_id"],
            user_id=row["user_id"],
            chat_id=row["chat_id"],
            revision_id=row["revision_id"],
            status=row["status"],
            step_progress=row["step_progress"],
            mode=row["mode"],
            input_path=row["input_path"],
            output_path=row["output_path"],
            preview_path=row["preview_path"],
            job_dir=row["job_dir"],
            params=params,
            error_reason=row["error_reason"],
            error_detail=row["error_detail"],
            retry_count=row["retry_count"],
            active_pid=row["active_pid"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            updated_at=row["updated_at"]
        )

    def insert_job(
        self,
        job_id: str,
        user_id: int,
        chat_id: int,
        mode: str,
        input_path: str,
        job_dir: str,
        params: Optional[Dict[str, Any]] = None
    ) -> DbJob:
        now = time.time()
        params_json = json.dumps(params or {}, ensure_ascii=False)
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    job_id, user_id, chat_id, revision_id, status, step_progress,
                    mode, input_path, job_dir, params_json, created_at, updated_at
                ) VALUES (?, ?, ?, 1, 'queued', 0.0, ?, ?, ?, ?, ?, ?)
                """,
                (job_id, user_id, chat_id, mode, input_path, job_dir, params_json, now, now)
            )
            conn.execute(
                """
                INSERT INTO job_history (job_id, revision_id, from_status, to_status, timestamp, note)
                VALUES (?, 1, NULL, 'queued', ?, 'Job created')
                """,
                (job_id, now)
            )
            conn.commit()

        return self.get_job(job_id)

    def get_job(self, job_id: str) -> Optional[DbJob]:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            if row:
                return self._row_to_job(row)
        return None

    def get_active_job_for_user(self, user_id: int) -> Optional[DbJob]:
        """Finds any job currently queued or in processing for user."""
        placeholders = ",".join("?" for _ in ACTIVE_PROCESSING_STATES)
        with self._get_connection() as conn:
            row = conn.execute(
                f"SELECT * FROM jobs WHERE user_id = ? AND status IN ({placeholders}) ORDER BY created_at DESC LIMIT 1",
                [user_id] + ACTIVE_PROCESSING_STATES
            ).fetchone()
            if row:
                return self._row_to_job(row)
        return None

    def get_resumable_job_for_user(self, user_id: int) -> Optional[DbJob]:
        """Finds active job or job awaiting approval that can be resumed."""
        resumable_states = ACTIVE_PROCESSING_STATES + ["awaiting_approval", "awaiting_manual_agent"]
        placeholders = ",".join("?" for _ in resumable_states)
        with self._get_connection() as conn:
            row = conn.execute(
                f"SELECT * FROM jobs WHERE user_id = ? AND status IN ({placeholders}) ORDER BY created_at DESC LIMIT 1",
                [user_id] + resumable_states
            ).fetchone()
            if row:
                return self._row_to_job(row)
        return None

    def get_latest_job_for_user(self, user_id: int) -> Optional[DbJob]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
                (user_id,)
            ).fetchone()
            if row:
                return self._row_to_job(row)
        return None

    def update_job_status(
        self,
        job_id: str,
        new_status: str,
        step_progress: Optional[float] = None,
        output_path: Optional[str] = None,
        preview_path: Optional[str] = None,
        error_reason: Optional[str] = None,
        error_detail: Optional[str] = None,
        active_pid: Optional[int] = None,
        params: Optional[Dict[str, Any]] = None,
        note: Optional[str] = None
    ) -> Optional[DbJob]:
        now = time.time()
        with self._get_connection() as conn:
            current = conn.execute("SELECT status, revision_id FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            if not current:
                return None

            from_status = current["status"]
            revision_id = current["revision_id"]

            fields = ["status = ?", "updated_at = ?"]
            values = [new_status, now]

            if step_progress is not None:
                fields.append("step_progress = ?")
                values.append(step_progress)

            if output_path is not None:
                fields.append("output_path = ?")
                values.append(output_path)

            if preview_path is not None:
                fields.append("preview_path = ?")
                values.append(preview_path)

            if error_reason is not None:
                fields.append("error_reason = ?")
                values.append(error_reason)

            if error_detail is not None:
                fields.append("error_detail = ?")
                values.append(error_detail)

            if active_pid is not None:
                fields.append("active_pid = ?")
                values.append(active_pid)

            if params is not None:
                fields.append("params_json = ?")
                values.append(json.dumps(params, ensure_ascii=False))

            if new_status == "analyzing" and from_status == "queued":
                fields.append("started_at = ?")
                values.append(now)

            if new_status in ("completed", "failed", "cancelled", "interrupted"):
                fields.append("finished_at = ?")
                values.append(now)

            values.append(job_id)
            conn.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE job_id = ?", values)

            # Record history
            conn.execute(
                """
                INSERT INTO job_history (job_id, revision_id, from_status, to_status, timestamp, note)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (job_id, revision_id, from_status, new_status, now, note)
            )
            conn.commit()

        return self.get_job(job_id)

    def bump_revision(self, job_id: str, new_params: Optional[Dict[str, Any]] = None) -> Optional[DbJob]:
        """Increments revision_id (e.g. after edit) and sets status back to planning/queued."""
        now = time.time()
        with self._get_connection() as conn:
            current = conn.execute("SELECT revision_id FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            if not current:
                return None
            new_rev = current["revision_id"] + 1

            fields = ["revision_id = ?", "updated_at = ?"]
            values = [new_rev, now]
            if new_params:
                fields.append("params_json = ?")
                values.append(json.dumps(new_params, ensure_ascii=False))

            values.append(job_id)
            conn.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE job_id = ?", values)
            conn.commit()

        return self.get_job(job_id)

    def get_next_queued_job(self) -> Optional[DbJob]:
        """Fetches the oldest queued job (FIFO)."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE status = 'queued' ORDER BY created_at ASC LIMIT 1"
            ).fetchone()
            if row:
                return self._row_to_job(row)
        return None

    def get_active_job_ids(self) -> List[str]:
        placeholders = ",".join("?" for _ in ACTIVE_PROCESSING_STATES)
        with self._get_connection() as conn:
            rows = conn.execute(f"SELECT job_id FROM jobs WHERE status IN ({placeholders})", ACTIVE_PROCESSING_STATES).fetchall()
            return [r["job_id"] for r in rows]

    def get_queue_stats(self) -> Dict[str, int]:
        with self._get_connection() as conn:
            queued = conn.execute("SELECT COUNT(*) as c FROM jobs WHERE status = 'queued'").fetchone()["c"]
            running = conn.execute(
                f"SELECT COUNT(*) as c FROM jobs WHERE status IN ('analyzing', 'planning', 'generating', 'validating', 'preview_rendering', 'final_rendering', 'uploading')"
            ).fetchone()["c"]
            awaiting_appr = conn.execute("SELECT COUNT(*) as c FROM jobs WHERE status = 'awaiting_approval'").fetchone()["c"]
            total = conn.execute("SELECT COUNT(*) as c FROM jobs").fetchone()["c"]
            return {
                "queued": queued,
                "running": running,
                "awaiting_approval": awaiting_appr,
                "total": total
            }
