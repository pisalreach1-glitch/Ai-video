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
    audio_source TEXT NOT NULL DEFAULT 'recorded_voice', -- 'recorded_voice' | 'cloned_voice'
    approved_audio_artifact_id TEXT,
    audio_approval_id TEXT,
    image_sha256 TEXT,
    settings_digest TEXT,
    video_snapshot_digest TEXT,
    avatar_backend TEXT NOT NULL DEFAULT 'sadtalker', -- 'sadtalker' | 'wan2gp_hunyuan'
    created_at REAL NOT NULL,
    PRIMARY KEY (job_id, revision_id),
    FOREIGN KEY (job_id) REFERENCES jobs (job_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS voice_references (
    reference_id TEXT PRIMARY KEY,
    owner_user_id INTEGER NOT NULL,
    job_id TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    wav_path TEXT NOT NULL,
    reference_text TEXT NOT NULL DEFAULT '',
    sha256 TEXT NOT NULL,
    duration_seconds REAL NOT NULL,
    sample_rate INTEGER NOT NULL,
    channels INTEGER NOT NULL,
    created_at REAL NOT NULL,
    FOREIGN KEY (job_id) REFERENCES jobs (job_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS voice_clone_artifacts (
    artifact_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    owner_user_id INTEGER NOT NULL,
    reference_id TEXT NOT NULL,
    reference_sha256 TEXT NOT NULL,
    text TEXT NOT NULL,
    text_sha256 TEXT NOT NULL,
    reference_text TEXT NOT NULL DEFAULT '',
    language TEXT NOT NULL DEFAULT 'km',
    backend_id TEXT NOT NULL,
    model_version TEXT NOT NULL,
    settings_json TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending',
    wav_path TEXT,
    wav_sha256 TEXT,
    duration_seconds REAL NOT NULL DEFAULT 0.0,
    manifest_path TEXT,
    error_code TEXT,
    created_at REAL NOT NULL,
    FOREIGN KEY (job_id) REFERENCES jobs (job_id) ON DELETE CASCADE,
    FOREIGN KEY (reference_id) REFERENCES voice_references (reference_id)
);

CREATE TABLE IF NOT EXISTS audio_approvals (
    approval_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    wav_sha256 TEXT NOT NULL,
    owner_user_id INTEGER NOT NULL,
    approved_at REAL NOT NULL,
    invalidated_at REAL,
    FOREIGN KEY (job_id) REFERENCES jobs (job_id) ON DELETE CASCADE,
    FOREIGN KEY (artifact_id) REFERENCES voice_clone_artifacts (artifact_id)
);

CREATE TABLE IF NOT EXISTS voice_conversions (
    conversion_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    owner_user_id INTEGER NOT NULL,
    target_reference_path TEXT NOT NULL,
    target_reference_sha256 TEXT NOT NULL,
    target_reference_duration REAL NOT NULL DEFAULT 0.0,
    full_source_path TEXT NOT NULL,
    full_source_sha256 TEXT NOT NULL,
    full_source_duration REAL NOT NULL DEFAULT 0.0,
    converted_wav_path TEXT,
    converted_wav_sha256 TEXT,
    converted_duration REAL NOT NULL DEFAULT 0.0,
    state TEXT NOT NULL DEFAULT 'pending',
    backend_id TEXT NOT NULL DEFAULT 'seed_vc',
    request_digest TEXT NOT NULL,
    manifest_path TEXT,
    error_code TEXT,
    created_at REAL NOT NULL,
    FOREIGN KEY (job_id) REFERENCES jobs (job_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS render_queue (
    job_id TEXT PRIMARY KEY,
    revision_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    task_type TEXT NOT NULL, -- 'preview' | 'final' | 'clone_synthesis' | 'voice_conversion'
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
CREATE INDEX IF NOT EXISTS idx_voice_refs_job ON voice_references(job_id);
CREATE INDEX IF NOT EXISTS idx_voice_clone_job ON voice_clone_artifacts(job_id);
CREATE INDEX IF NOT EXISTS idx_audio_approvals_job ON audio_approvals(job_id);
CREATE INDEX IF NOT EXISTS idx_voice_conversions_job ON voice_conversions(job_id);
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

        # Additive migration for talking_photo_revisions table
        tp_cols = {row["name"] for row in conn.execute("PRAGMA table_info(talking_photo_revisions)").fetchall()}
        if "audio_source" not in tp_cols:
            conn.execute("ALTER TABLE talking_photo_revisions ADD COLUMN audio_source TEXT NOT NULL DEFAULT 'recorded_voice'")
        if "approved_audio_artifact_id" not in tp_cols:
            conn.execute("ALTER TABLE talking_photo_revisions ADD COLUMN approved_audio_artifact_id TEXT")
        if "audio_approval_id" not in tp_cols:
            conn.execute("ALTER TABLE talking_photo_revisions ADD COLUMN audio_approval_id TEXT")
        if "image_sha256" not in tp_cols:
            conn.execute("ALTER TABLE talking_photo_revisions ADD COLUMN image_sha256 TEXT")
        if "settings_digest" not in tp_cols:
            conn.execute("ALTER TABLE talking_photo_revisions ADD COLUMN settings_digest TEXT")
        if "video_snapshot_digest" not in tp_cols:
            conn.execute("ALTER TABLE talking_photo_revisions ADD COLUMN video_snapshot_digest TEXT")
        if "avatar_backend" not in tp_cols:
            conn.execute("ALTER TABLE talking_photo_revisions ADD COLUMN avatar_backend TEXT NOT NULL DEFAULT 'sadtalker'")

        # Additive migration for voice_references
        vr_cols = {row["name"] for row in conn.execute("PRAGMA table_info(voice_references)").fetchall()}
        if "reference_text" not in vr_cols:
            conn.execute("ALTER TABLE voice_references ADD COLUMN reference_text TEXT NOT NULL DEFAULT ''")

        # Additive migration for voice_clone_artifacts
        vca_cols = {row["name"] for row in conn.execute("PRAGMA table_info(voice_clone_artifacts)").fetchall()}
        if "reference_text" not in vca_cols:
            conn.execute("ALTER TABLE voice_clone_artifacts ADD COLUMN reference_text TEXT NOT NULL DEFAULT ''")

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
