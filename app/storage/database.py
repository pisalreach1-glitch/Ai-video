"""Database initialization, schema management, and connection helpers."""
import sqlite3
import threading
from pathlib import Path
from typing import Iterator
from contextlib import contextmanager
from app.config import config

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS preferences (
    user_id INTEGER PRIMARY KEY,
    voice TEXT NOT NULL DEFAULT 'km-KH-SreymomNeural',
    speed TEXT NOT NULL DEFAULT '+0%',
    subtitles_enabled INTEGER NOT NULL DEFAULT 1,
    subtitle_color TEXT NOT NULL DEFAULT 'white',
    subtitle_position TEXT NOT NULL DEFAULT 'bottom',
    source_audio_mode TEXT NOT NULL DEFAULT 'mute',
    aspect_ratio TEXT NOT NULL DEFAULT 'original',
    framing_mode TEXT NOT NULL DEFAULT 'fit',
    duration_policy TEXT NOT NULL DEFAULT 'extend',
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    active_job_id TEXT,
    wizard_state TEXT,
    state_data TEXT,
    updated_at REAL NOT NULL,
    PRIMARY KEY (user_id, chat_id)
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'upload',
    source_path TEXT,
    source_url TEXT,
    source_media_info TEXT,
    status TEXT NOT NULL,
    stage TEXT DEFAULT 'init',
    current_revision_id INTEGER NOT NULL DEFAULT 1,
    feature TEXT NOT NULL DEFAULT 'video_voiceover',
    mode TEXT NOT NULL DEFAULT 'free_narration',
    dubbing_revision_id INTEGER,
    duration_policy TEXT NOT NULL DEFAULT 'extend',
    error_message TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS revisions (
    job_id TEXT NOT NULL,
    revision_id INTEGER NOT NULL,
    narration_text TEXT NOT NULL,
    settings TEXT NOT NULL,
    audio_path TEXT,
    audio_duration REAL NOT NULL DEFAULT 0.0,
    subtitles_srt TEXT,
    subtitles_ass TEXT,
    preview_path TEXT,
    final_path TEXT,
    mode TEXT NOT NULL DEFAULT 'free_narration',
    dubbing_plan_path TEXT,
    created_at REAL NOT NULL,
    PRIMARY KEY (job_id, revision_id),
    FOREIGN KEY (job_id) REFERENCES jobs (job_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS talking_photo_revisions (
    job_id TEXT NOT NULL,
    revision_id INTEGER NOT NULL,
    input_version INTEGER NOT NULL DEFAULT 1,
    image_path TEXT NOT NULL,
    original_voice_path TEXT NOT NULL,
    inference_wav_path TEXT,
    master_audio_path TEXT,
    settings_json TEXT NOT NULL,
    manifest_path TEXT,
    preview_path TEXT,
    approved_preview_id TEXT,
    final_path TEXT,
    input_digest TEXT NOT NULL,
    engine_version TEXT,
    created_at REAL NOT NULL,
    PRIMARY KEY (job_id, revision_id),
    FOREIGN KEY (job_id) REFERENCES jobs (job_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS render_queue (
    job_id TEXT PRIMARY KEY,
    revision_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    task_type TEXT NOT NULL, -- 'preview' | 'final'
    status TEXT NOT NULL,    -- 'queued' | 'processing' | 'completed' | 'failed' | 'cancelled'
    feature TEXT NOT NULL DEFAULT 'video_voiceover',
    input_digest TEXT,
    enqueued_at REAL NOT NULL,
    started_at REAL,
    completed_at REAL,
    retry_count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_jobs_user_chat ON jobs(user_id, chat_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_revisions_job_id ON revisions(job_id, revision_id);
CREATE INDEX IF NOT EXISTS idx_talking_photo_revisions_job_id ON talking_photo_revisions(job_id, revision_id);
CREATE INDEX IF NOT EXISTS idx_render_queue_status ON render_queue(status, enqueued_at ASC);
"""

class Database:
    def __init__(self, db_path: Path | str | None = None):
        if db_path is None:
            self.db_path = config.db_path
        else:
            self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(
                str(self.db_path),
                timeout=10.0,
                check_same_thread=False,
                isolation_level=None # autocommit by default; explicit transactions when needed
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA busy_timeout=5000;")
            conn.execute("PRAGMA foreign_keys=ON;")
            self._local.conn = conn
        return self._local.conn

    def init_db(self) -> None:
        conn = self.get_connection()
        conn.executescript(SCHEMA_SQL)
        self._run_migrations(conn)

    def _run_migrations(self, conn: sqlite3.Connection) -> None:
        # Additive migration for jobs table
        job_cols = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
        if "feature" not in job_cols:
            conn.execute("ALTER TABLE jobs ADD COLUMN feature TEXT NOT NULL DEFAULT 'video_voiceover'")
        if "mode" not in job_cols:
            conn.execute("ALTER TABLE jobs ADD COLUMN mode TEXT NOT NULL DEFAULT 'free_narration'")
        if "dubbing_revision_id" not in job_cols:
            conn.execute("ALTER TABLE jobs ADD COLUMN dubbing_revision_id INTEGER")

        # Additive migration for revisions table
        rev_cols = {row["name"] for row in conn.execute("PRAGMA table_info(revisions)").fetchall()}
        if "mode" not in rev_cols:
            conn.execute("ALTER TABLE revisions ADD COLUMN mode TEXT NOT NULL DEFAULT 'free_narration'")
        if "dubbing_plan_path" not in rev_cols:
            conn.execute("ALTER TABLE revisions ADD COLUMN dubbing_plan_path TEXT")

        # Additive migration for render_queue table
        q_cols = {row["name"] for row in conn.execute("PRAGMA table_info(render_queue)").fetchall()}
        if "feature" not in q_cols:
            conn.execute("ALTER TABLE render_queue ADD COLUMN feature TEXT NOT NULL DEFAULT 'video_voiceover'")
        if "input_digest" not in q_cols:
            conn.execute("ALTER TABLE render_queue ADD COLUMN input_digest TEXT")

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self.get_connection()
        conn.execute("BEGIN IMMEDIATE;")
        try:
            yield conn
            conn.execute("COMMIT;")
        except Exception:
            conn.execute("ROLLBACK;")
            raise

_db_instance: Database | None = None

def get_db(db_path: Path | str | None = None) -> Database:
    global _db_instance
    if _db_instance is None or db_path is not None:
        inst = Database(db_path)
        if db_path is None:
            _db_instance = inst
        return inst
    return _db_instance
