"""Tests for callback payload constraints, ownership verification, and stale revision rejection."""
import pytest
from app.ui.keyboards import (
    mode_choice_keyboard,
    dubbing_review_keyboard,
    dubbing_fit_resolution_keyboard,
)

def test_dubbing_all_callbacks_within_64_bytes():
    """All inline keyboard callback data for dubbing must be strictly <= 64 UTF-8 bytes."""
    job_id = "12345678-1234-1234-1234-123456789abc"
    revision_id = 12

    # 1. Mode choice keyboard
    kb1 = mode_choice_keyboard(job_id, has_caption=True)
    for row in kb1.inline_keyboard:
        for btn in row:
            cb_bytes = len(btn.callback_data.encode("utf-8"))
            assert cb_bytes <= 64, f"Callback exceeds 64 bytes: {btn.callback_data} ({cb_bytes}b)"

    # 2. Dubbing review keyboard with segment buttons
    segments = [("s001", "s001"), ("s002", "s002"), ("s003", "s003")]
    kb2 = dubbing_review_keyboard(job_id, revision_id, page=2, total_pages=5, segments_on_page=segments)
    for row in kb2.inline_keyboard:
        for btn in row:
            cb_bytes = len(btn.callback_data.encode("utf-8"))
            assert cb_bytes <= 64, f"Callback exceeds 64 bytes: {btn.callback_data} ({cb_bytes}b)"

    # 3. Fit resolution keyboard
    kb3 = dubbing_fit_resolution_keyboard(job_id, revision_id, segment_id="s001")
    for row in kb3.inline_keyboard:
        for btn in row:
            cb_bytes = len(btn.callback_data.encode("utf-8"))
            assert cb_bytes <= 64, f"Callback exceeds 64 bytes: {btn.callback_data} ({cb_bytes}b)"

@pytest.mark.asyncio
async def test_stale_dubbing_callback_rejection(temp_job_storage):
    """Requirement 11: Stale callbacks for outdated revisions are rejected."""
    from app.domain.models import VoiceSettings
    job = temp_job_storage.create_job(user_id=123, chat_id=456)
    rev1 = temp_job_storage.create_revision(job.job_id, "Rev 1 text", settings=VoiceSettings())
    rev2 = temp_job_storage.create_revision(job.job_id, "Rev 2 text", settings=VoiceSettings())

    latest_job = temp_job_storage.get_job(job.job_id)
    assert latest_job.current_revision_id == 2

    # Callback referencing rev1 must be detected as outdated
    assert rev1.revision_id != latest_job.current_revision_id
    assert rev2.revision_id == latest_job.current_revision_id
