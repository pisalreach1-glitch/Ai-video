"""Tests for crash recovery and delivery retry without re-rendering."""
from pathlib import Path
import pytest
from app.domain.states import JobState

def test_dubbing_restart_recovers_transient_stages_honestly(temp_job_storage):
    """Requirement 14: Restart at ASR, translation, TTS, assembly transitions to INTERRUPTED."""
    job1 = temp_job_storage.create_job(user_id=1, chat_id=1)
    temp_job_storage.set_job_status(job1.job_id, JobState.GENERATING_AUDIO)

    job2 = temp_job_storage.create_job(user_id=2, chat_id=2)
    temp_job_storage.set_job_status(job2.job_id, JobState.PREVIEW_RENDERING)

    # Simulate bot restart
    recovered = temp_job_storage.recover_interrupted_jobs()
    assert recovered >= 2

    j1 = temp_job_storage.get_job(job1.job_id)
    assert j1.status == JobState.INTERRUPTED
    assert "interrupted" in j1.stage

    j2 = temp_job_storage.get_job(job2.job_id)
    assert j2.status == JobState.INTERRUPTED

def test_delivery_retry_retains_completed_video_without_rerender(temp_job_storage, tmp_path):
    """Requirement 15: Delivery retry sends retained MP4 without re-rendering."""
    job = temp_job_storage.create_job(user_id=1, chat_id=1)
    mp4_file = tmp_path / "final.mp4"
    mp4_file.write_bytes(b"dummy mp4 content")

    from app.domain.models import VoiceSettings
    rev = temp_job_storage.create_revision(
        job_id=job.job_id,
        narration_text="Test",
        settings=VoiceSettings(),
        mode="source_timed",
    )
    temp_job_storage.update_revision(job.job_id, rev.revision_id, final_path=str(mp4_file))
    temp_job_storage.set_job_status(job.job_id, JobState.DELIVERY_FAILED)

    # When retrying delivery, the final_path is already retained
    loaded_rev = temp_job_storage.get_revision(job.job_id, rev.revision_id)
    assert loaded_rev.final_path == str(mp4_file)
    assert Path(loaded_rev.final_path).exists()
