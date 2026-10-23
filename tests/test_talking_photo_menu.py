"""Tests for Main Menu, Talking Photo button, and Job Picker navigation."""
import pytest
from app.domain.features import JobFeature
from app.domain.models import Job
from app.domain.states import JobState
from app.ui.keyboards import (
    main_menu_keyboard,
    active_job_picker_keyboard,
)
from app.features.talking_photo.keyboards import (
    tp_photo_prompt_keyboard,
    tp_voice_prompt_keyboard,
    tp_input_review_keyboard,
    tp_settings_keyboard,
    tp_preview_keyboard,
    tp_completed_keyboard,
)
from app.features.talking_photo.domain import TalkingPhotoSettings

def test_main_menu_keyboard_layout():
    kb_no_active = main_menu_keyboard(has_active_job=False)
    # Check button texts and callbacks
    texts = [btn.text for row in kb_no_active.inline_keyboard for btn in row]
    callbacks = [btn.callback_data for row in kb_no_active.inline_keyboard for btn in row]

    assert "🎬 បញ្ចូលសំឡេងទៅវីដេអូ" in texts
    assert "🖼️ រូបថតនិយាយតាម Voice" in texts
    assert "nav_new_video" in callbacks
    assert "nav_talking_photo" in callbacks
    assert "nav_resume" not in callbacks

    kb_active = main_menu_keyboard(has_active_job=True)
    active_texts = [btn.text for row in kb_active.inline_keyboard for btn in row]
    active_callbacks = [btn.callback_data for row in kb_active.inline_keyboard for btn in row]
    assert "▶️ បន្តការងារ" in active_texts
    assert "nav_resume" in active_callbacks

def test_all_talking_photo_callbacks_strictly_le_64_bytes():
    job_id = "12345678-1234-5678-1234-567812345678"
    rev_id = 99
    st = TalkingPhotoSettings()

    kbs = [
        main_menu_keyboard(True),
        tp_photo_prompt_keyboard(),
        tp_voice_prompt_keyboard(job_id),
        tp_input_review_keyboard(job_id, rev_id),
        tp_settings_keyboard(job_id, rev_id, st),
        tp_preview_keyboard(job_id, rev_id),
        tp_completed_keyboard(job_id, rev_id),
    ]

    for kb in kbs:
        for row in kb.inline_keyboard:
            for btn in row:
                if btn.callback_data:
                    encoded = btn.callback_data.encode("utf-8")
                    assert len(encoded) <= 64, f"Callback {btn.callback_data} exceeds 64 bytes ({len(encoded)})"

def test_active_job_picker_keyboard():
    jobs = [
        Job(job_id="job_vid_123", user_id=1, chat_id=2, feature=JobFeature.VIDEO_VOICEOVER.value, status=JobState.AWAITING_SOURCE),
        Job(job_id="job_tp_456", user_id=1, chat_id=2, feature=JobFeature.TALKING_PHOTO.value, status=JobState.AWAITING_SOURCE),
    ]
    picker = active_job_picker_keyboard(jobs)
    assert len(picker.inline_keyboard) == 3 # 2 jobs + 1 back button
    callbacks = [btn.callback_data for row in picker.inline_keyboard for btn in row]
    assert "resume_job:job_vid_123" in callbacks
    assert "resume_job:job_tp_456" in callbacks
    assert "nav_main" in callbacks
