import pytest
from app.features.voice_clone.keyboards import (
    tp_audio_source_keyboard,
    vc_reference_prompt_keyboard,
    vc_text_prompt_keyboard,
    vc_review_keyboard,
)

def test_all_voice_clone_callbacks_under_64_bytes():
    """Ensure all callback_data in voice clone keyboards respect Telegram's 64-byte limit."""
    # Standard UUIDs are 36 chars: e.g. "12345678-1234-1234-1234-123456789abc"
    job_id = "job_1234567890_abcdef"
    artifact_id = "art_1234567890_abcdef"

    keyboards = [
        tp_audio_source_keyboard(job_id),
        vc_reference_prompt_keyboard(job_id),
        vc_text_prompt_keyboard(job_id),
        vc_review_keyboard(job_id, artifact_id),
    ]

    for kb in keyboards:
        for row in kb.inline_keyboard:
            for btn in row:
                if btn.callback_data:
                    encoded = btn.callback_data.encode("utf-8")
                    assert len(encoded) <= 64, (
                        f"Callback data '{btn.callback_data}' exceeds 64 bytes: {len(encoded)} bytes"
                    )

def test_uuid_voice_clone_callbacks_under_64_bytes():
    """Test with 36-character standard UUID strings."""
    job_id = "12345678-1234-1234-1234-123456789abc"
    # For artifact_id, verify that compact IDs or UUIDs keep callback_data <= 64 bytes
    artifact_id = "art_abc123xyz"

    kb = vc_review_keyboard(job_id, artifact_id)
    for row in kb.inline_keyboard:
        for btn in row:
            if btn.callback_data:
                encoded = btn.callback_data.encode("utf-8")
                assert len(encoded) <= 64, (
                    f"Callback data '{btn.callback_data}' exceeds 64 bytes ({len(encoded)} bytes)"
                )
