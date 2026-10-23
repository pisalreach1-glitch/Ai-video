"""Tests for Talking Photo database schema and migrations."""
import sqlite3
import pytest
from app.domain.features import JobFeature
from app.domain.models import Job
from app.storage.database import Database
from app.storage.jobs import JobStorage
from app.features.talking_photo.storage import TalkingPhotoStorage, TalkingPhotoSettings

@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_tp.sqlite3"
    db = Database(db_file)
    return db

def test_jobs_table_has_feature_column_with_default(temp_db):
    conn = temp_db.get_connection()
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    assert "feature" in cols

    # Insert raw row without feature
    conn.execute(
        "INSERT INTO jobs (job_id, user_id, chat_id, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("legacy_1", 111, 222, "completed", 100.0, 100.0)
    )
    row = conn.execute("SELECT feature FROM jobs WHERE job_id = 'legacy_1'").fetchone()
    assert row["feature"] == JobFeature.VIDEO_VOICEOVER.value

def test_talking_photo_revisions_table_exists(temp_db):
    conn = temp_db.get_connection()
    tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "talking_photo_revisions" in tables

def test_talking_photo_storage_crud(temp_db):
    job_store = JobStorage(temp_db)
    tp_store = TalkingPhotoStorage(temp_db)

    job = job_store.create_job(user_id=1, chat_id=2, feature=JobFeature.TALKING_PHOTO.value)
    assert job.feature == JobFeature.TALKING_PHOTO.value

    st = TalkingPhotoSettings(face_size=256, still_mode=True, pose_style=1)
    rev = tp_store.create_revision(
        job_id=job.job_id,
        image_path="/path/to/img.png",
        original_voice_path="/path/to/voice.ogg",
        settings=st,
        input_digest="hash123",
    )
    assert rev.revision_id == 1
    assert rev.settings.face_size == 256
    assert rev.settings.still_mode is True

    fetched = tp_store.get_revision(job.job_id, 1)
    assert fetched is not None
    assert fetched.image_path == "/path/to/img.png"
    assert fetched.settings.pose_style == 1

    tp_store.update_revision_paths(
        job.job_id,
        1,
        preview_path="/path/to/preview.mp4",
        final_path="/path/to/final.mp4",
    )
    updated = tp_store.get_revision(job.job_id, 1)
    assert updated.preview_path == "/path/to/preview.mp4"
    assert updated.final_path == "/path/to/final.mp4"
