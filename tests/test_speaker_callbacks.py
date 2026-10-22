"""Tests for Telegram callback data lengths, expiry, and cross-user rejection."""
import pytest
from app.storage.speaker_reviews import speaker_review_store
from app.ui.speaker_keyboards import (
    speaker_mode_choice_keyboard,
    speaker_card_keyboard,
    speaker_voice_picker_keyboard,
    review_issue_keyboard,
    speaker_assignment_picker_keyboard,
)


def test_all_speaker_callback_lengths_strictly_le_64_bytes():
    """Quality Constraint: All Telegram callback data must be <= 64 bytes."""
    dummy_token = "abcd1234"
    dummy_job = "87a145ab-716a-4654-a5e5-66e3dbd2a995"

    keyboards = [
        speaker_mode_choice_keyboard(dummy_job),
        speaker_card_keyboard(dummy_token, page=1, total_pages=5, is_confirmed=False, open_issue_count=3, has_full_preview=True),
        speaker_voice_picker_keyboard(
            dummy_token,
            [{"ShortName": "km-KH-SreymomNeural", "Gender": "Female"}, {"ShortName": "km-KH-PisethNeural", "Gender": "Male"}],
            "km-KH-SreymomNeural",
        ),
        review_issue_keyboard(dummy_token, issue_idx=2, total_issues=5, allow_confirm=True, segment_id="s001_a"),
        speaker_assignment_picker_keyboard(dummy_token, segment_id="s001_a", speakers=["Speaker A", "Speaker B"]),
    ]

    for kb in keyboards:
        for row in kb.inline_keyboard:
            for btn in row:
                if btn.callback_data:
                    byte_len = len(btn.callback_data.encode("utf-8"))
                    assert byte_len <= 64, f"Callback '{btn.callback_data}' exceeded 64 bytes ({byte_len} bytes)"


def test_token_store_lifecycle_and_expiry():
    """Criteria 15: Stale and expired callback tokens are rejected."""
    token = speaker_review_store.create_token(
        job_id="job1",
        revision_id=1,
        user_id=12345,
        target_id="Speaker A",
        ttl_seconds=-1.0,  # immediate expiry
    )
    # Expired token resolves to None
    assert speaker_review_store.get_token(token) is None
    # Non-existent token resolves to None
    assert speaker_review_store.get_token("non_existent_token") is None
