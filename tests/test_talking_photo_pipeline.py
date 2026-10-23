"""Tests for Talking Photo pipeline execution, worker dispatch, preview, and final delivery."""
import asyncio
import pytest
from pathlib import Path
from PIL import Image
from app.config import config
from app.domain.features import JobFeature, QueueTask
from app.domain.states import JobState
from app.storage.database import Database
from app.storage.jobs import JobStorage
from app.storage.workspaces import WorkspaceManager
from app.features.talking_photo.domain import TalkingPhotoSettings
from app.features.talking_photo.storage import TalkingPhotoStorage
from app.features.talking_photo.pipeline import talking_photo_pipeline
from app.features.talking_photo.engine import sadtalker_engine
from app.jobs.worker import WorkerPool
from app.jobs.processes import run_process

@pytest.fixture
def test_env(tmp_path, monkeypatch):
    db = Database(tmp_path / "test_tp_pipe.sqlite3")
    job_store = JobStorage(db)
    tp_store = TalkingPhotoStorage(db)
    ws = WorkspaceManager(runtime_dir=tmp_path / "runtime")

    monkeypatch.setattr("app.features.talking_photo.pipeline.job_storage", job_store)
    monkeypatch.setattr("app.features.talking_photo.pipeline.talking_photo_storage", tp_store)
    monkeypatch.setattr("app.features.talking_photo.pipeline.workspace", ws)
    monkeypatch.setattr("app.jobs.worker.job_storage", job_store)

    return db, job_store, tp_store, ws

@pytest.mark.asyncio
async def test_talking_photo_preview_pipeline_run(test_env, tmp_path):
    db, job_store, tp_store, ws = test_env

    # 1. Prepare synthetic portrait image and voice
    img_path = tmp_path / "portrait.png"
    Image.new("RGB", (256, 256), color=(120, 140, 180)).save(img_path)

    voice_path = tmp_path / "speech.wav"
    cmd = [
        config.ffmpeg_path,
        "-y",
        "-f", "lavfi",
        "-i", "sine=frequency=400:duration=3.0",
        str(voice_path),
    ]
    await run_process(cmd, timeout=30.0)

    # 2. Create job and revision
    user_id = 1111
    chat_id = 2222
    job = job_store.create_job(user_id=user_id, chat_id=chat_id, feature=JobFeature.TALKING_PHOTO.value)
    rev = tp_store.create_revision(
        job_id=job.job_id,
        image_path=str(img_path),
        original_voice_path=str(voice_path),
        settings=TalkingPhotoSettings(face_size=256),
    )
    tp_store.update_revision_paths(
        job.job_id,
        rev.revision_id,
        inference_wav_path=str(voice_path),
        master_audio_path=str(voice_path),
    )

    # 3. Create mock worker pool
    class MockWorkerPool:
        def __init__(self):
            self._active_pids = {}
        def get_bot(self):
            return None
        def register_pid(self, jid, pid):
            self._active_pids[jid] = pid
        def is_cancelled(self, jid):
            return False

    wp = MockWorkerPool()
    task = QueueTask(
        job_id=job.job_id,
        revision_id=rev.revision_id,
        feature=JobFeature.TALKING_PHOTO.value,
        task_type="preview",
        user_id=user_id,
    )

    # 4. Run pipeline
    await talking_photo_pipeline.run(task, wp)

    # 5. Verify status and output
    updated_job = job_store.get_job(job.job_id)
    assert updated_job.status == JobState.AWAITING_APPROVAL

    updated_rev = tp_store.get_revision(job.job_id, rev.revision_id)
    assert updated_rev.preview_path is not None
    assert Path(updated_rev.preview_path).exists()
    assert Path(updated_rev.preview_path).stat().st_size > 0

@pytest.mark.asyncio
async def test_talking_photo_final_render_and_worker_dispatch(test_env, tmp_path):
    db, job_store, tp_store, ws = test_env

    img_path = tmp_path / "portrait_final.png"
    Image.new("RGB", (256, 256), color=(200, 100, 150)).save(img_path)

    voice_path = tmp_path / "speech_final.wav"
    cmd = [
        config.ffmpeg_path,
        "-y",
        "-f", "lavfi",
        "-i", "sine=frequency=500:duration=2.5",
        str(voice_path),
    ]
    await run_process(cmd, timeout=30.0)

    user_id = 3333
    chat_id = 4444
    job = job_store.create_job(user_id=user_id, chat_id=chat_id, feature=JobFeature.TALKING_PHOTO.value)
    rev = tp_store.create_revision(
        job_id=job.job_id,
        image_path=str(img_path),
        original_voice_path=str(voice_path),
        settings=TalkingPhotoSettings(face_size=256),
    )
    tp_store.update_revision_paths(
        job.job_id,
        rev.revision_id,
        inference_wav_path=str(voice_path),
        master_audio_path=str(voice_path),
    )

    # Enqueue final task
    enqueued = job_store.enqueue_task(
        job_id=job.job_id,
        revision_id=rev.revision_id,
        user_id=user_id,
        task_type="final",
        feature=JobFeature.TALKING_PHOTO.value,
    )
    assert enqueued is True

    # Run via WorkerPool
    worker = WorkerPool(storage=job_store, concurrency=1)
    task_data = job_store.claim_next_task()
    assert task_data is not None
    assert task_data["feature"] == JobFeature.TALKING_PHOTO.value

    await worker._process_task(
        job_id=task_data["job_id"],
        revision_id=task_data["revision_id"],
        task_type=task_data["task_type"],
        feature=task_data["feature"],
    )

    # Verify final completed
    updated_job = job_store.get_job(job.job_id)
    assert updated_job.status == JobState.COMPLETED

    updated_rev = tp_store.get_revision(job.job_id, rev.revision_id)
    assert updated_rev.final_path is not None
    assert Path(updated_rev.final_path).exists()
    assert Path(updated_rev.final_path).stat().st_size > 0
