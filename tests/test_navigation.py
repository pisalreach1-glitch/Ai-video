"""Test navigation, keyboard callback integrity, and resume flows."""
import pytest
from app.domain.states import JobState, WizardStep
from app.domain.models import VoiceSettings
from app.ui import keyboards as kb

def test_all_keyboards_generate_valid_inline_markups():
    """Verify that every keyboard helper constructs a valid InlineKeyboardMarkup."""
    m1 = kb.main_menu_keyboard(has_active_job=True)
    assert any(b.callback_data == "nav_resume" for row in m1.inline_keyboard for b in row)

    m2 = kb.source_choice_keyboard()
    callbacks = [b.callback_data for row in m2.inline_keyboard for b in row]
    assert "src_upload" in callbacks
    assert "src_link" in callbacks
    assert "nav_main" in callbacks

    m3 = kb.caption_confirm_keyboard()
    assert any(b.callback_data == "caption_use" for row in m3.inline_keyboard for b in row)

    m4 = kb.settings_menu_keyboard("test-job", 1)
    s_callbacks = [b.callback_data for row in m4.inline_keyboard for b in row]
    assert "set_voice:test-job:1" in s_callbacks
    assert "set_proceed:test-job:1" in s_callbacks

    m5 = kb.audio_review_keyboard("test-job", 1)
    a_callbacks = [b.callback_data for row in m5.inline_keyboard for b in row]
    assert "aud_next:test-job:1" in a_callbacks

    m6 = kb.video_preview_review_keyboard("test-job", 1)
    p_callbacks = [b.callback_data for row in m6.inline_keyboard for b in row]
    assert "apprv_final:test-job:1" in p_callbacks

def test_session_state_isolation(temp_sessions):
    """Ensure user/chat sessions remain strictly isolated."""
    temp_sessions.set_session(
        user_id=101,
        chat_id=101,
        active_job_id="job-101",
        wizard_state="awaiting_text",
        state_data={"narration_text": "Text 101"},
    )
    temp_sessions.set_session(
        user_id=202,
        chat_id=202,
        active_job_id="job-202",
        wizard_state="awaiting_settings",
        state_data={"narration_text": "Text 202"},
    )

    s1 = temp_sessions.get_session(101, 101)
    s2 = temp_sessions.get_session(202, 202)

    assert s1["active_job_id"] == "job-101"
    assert s1["state_data"]["narration_text"] == "Text 101"

    assert s2["active_job_id"] == "job-202"
    assert s2["state_data"]["narration_text"] == "Text 202"

def test_job_resume_detection(temp_job_storage):
    """Check that unfinished jobs are accurately identified for resume."""
    user_id = 999
    chat_id = 999

    assert temp_job_storage.get_user_active_job(user_id, chat_id) is None

    job = temp_job_storage.create_job(user_id=user_id, chat_id=chat_id)
    assert job.status == JobState.AWAITING_SOURCE

    active = temp_job_storage.get_user_active_job(user_id, chat_id)
    assert active is not None
    assert active.job_id == job.job_id

    # Marking completed means no active job to resume
    temp_job_storage.set_job_status(job.job_id, JobState.COMPLETED)
    assert temp_job_storage.get_user_active_job(user_id, chat_id) is None
