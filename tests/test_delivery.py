"""Test delivery resilience, failure handling, and delivery retry."""
from unittest.mock import AsyncMock, MagicMock
import pytest
from app.domain.states import JobState
from app.domain.models import Revision, VoiceSettings
from app.services.delivery import deliver_final_video

@pytest.mark.asyncio
async def test_delivery_success_marks_completed(session_media_dir, temp_job_storage, monkeypatch):
    """Successful upload updates job state to COMPLETED."""
    job = temp_job_storage.create_job(user_id=10, chat_id=10)
    rev = temp_job_storage.create_revision(job.job_id, "Test text", VoiceSettings())

    # Point final_path to real synthetic video
    real_video = str(session_media_dir["video_with_audio"])
    temp_job_storage.update_revision(job.job_id, rev.revision_id, final_path=real_video)
    rev.final_path = real_video

    # Mock bot to avoid real telegram call
    mock_bot = MagicMock()
    mock_bot.send_video = AsyncMock()

    # Monkeypatch job_storage in delivery to use our temp_job_storage
    monkeypatch.setattr("app.services.delivery.job_storage", temp_job_storage)

    delivered = await deliver_final_video(mock_bot, 10, job.job_id, rev)
    assert delivered is True

    updated_job = temp_job_storage.get_job(job.job_id)
    assert updated_job.status == JobState.COMPLETED
    mock_bot.send_video.assert_called_once()

@pytest.mark.asyncio
async def test_delivery_failure_preserves_file_and_sets_delivery_failed(session_media_dir, temp_job_storage, monkeypatch):
    """Delivery network failure preserves final MP4 and transitions to DELIVERY_FAILED."""
    job = temp_job_storage.create_job(user_id=10, chat_id=10)
    rev = temp_job_storage.create_revision(job.job_id, "Test text", VoiceSettings())

    real_video = str(session_media_dir["video_with_audio"])
    temp_job_storage.update_revision(job.job_id, rev.revision_id, final_path=real_video)
    rev.final_path = real_video

    # Mock bot that throws exception on send_video
    mock_bot = MagicMock()
    mock_bot.send_video = AsyncMock(side_effect=RuntimeError("Simulated Telegram upload timeout"))
    mock_bot.send_message = AsyncMock()

    monkeypatch.setattr("app.services.delivery.job_storage", temp_job_storage)

    delivered = await deliver_final_video(mock_bot, 10, job.job_id, rev)
    assert delivered is False

    updated_job = temp_job_storage.get_job(job.job_id)
    assert updated_job.status == JobState.DELIVERY_FAILED

    # File must still be intact
    assert session_media_dir["video_with_audio"].exists()

    # Retry message was sent with retry keyboard
    mock_bot.send_message.assert_called_once()
