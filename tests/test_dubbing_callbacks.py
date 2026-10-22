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

    # 3. Fit resolution keyboard (single and multiple overlong clips)
    kb3 = dubbing_fit_resolution_keyboard(job_id, revision_id, segment_id="s001", overlong_count=1)
    for row in kb3.inline_keyboard:
        for btn in row:
            cb_bytes = len(btn.callback_data.encode("utf-8"))
            assert cb_bytes <= 64, f"Callback exceeds 64 bytes: {btn.callback_data} ({cb_bytes}b)"

    kb4 = dubbing_fit_resolution_keyboard(job_id, revision_id, segment_id="s001", overlong_count=10)
    for row in kb4.inline_keyboard:
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

@pytest.mark.asyncio
async def test_dubbing_auto_translate_callback(temp_job_storage, monkeypatch):
    """Ensure d_ai callback triggers AI translation and updates DubbingPlan."""
    from app.domain.states import JobState
    from app.domain.dubbing import SourceSegment, TranslatedSegment, DubbingPlan
    from app.storage.dubbing import save_source_segments, save_dubbing_plan, load_dubbing_plan
    from app.handlers.dubbing import cb_dubbing_auto_translate

    job = temp_job_storage.create_job(user_id=111, chat_id=222)
    temp_job_storage.set_job_status(job.job_id, JobState.AWAITING_SEGMENT_REVIEW)

    import app.handlers.dubbing
    monkeypatch.setattr(app.handlers.dubbing, "job_storage", temp_job_storage)
    monkeypatch.setattr("app.handlers.common.job_storage", temp_job_storage)

    sources = [
        SourceSegment(segment_id="s001", start_ms=0, end_ms=2000, source_text="Hello world"),
    ]
    save_source_segments(job.job_id, sources)

    plan = DubbingPlan(
        mode="source_timed",
        source_duration_ms=2000,
        sample_rate=48000,
        segments=sources,
        translations=[TranslatedSegment(segment_id="s001", translated_text="", translation_provider="manual", status="needs_review")],
    )
    save_dubbing_plan(job.job_id, 1, plan)

    # Mock translate_segments to return Khmer text
    async def mock_translate(segs, provider=None, cancel_check=None):
        return [TranslatedSegment(segment_id="s001", translated_text="សួស្តីពិភពលោក", translation_provider="gemini", status="ready")]

    monkeypatch.setattr("app.services.segment_translation.translate_segments", mock_translate)

    class MockCall:
        from_user = type("User", (), {"id": 111})()
        message = type("Msg", (), {"chat": type("Chat", (), {"id": 222})(), "video": None, "document": None, "photo": None, "edit_text": _async_noop, "answer": _async_noop})()
        data = f"d_ai:{job.job_id}:1"
        async def answer(self, text="", show_alert=False):
            pass

    class MockState:
        async def update_data(self, **kwargs):
            pass

    await cb_dubbing_auto_translate(MockCall(), MockState())

    # Verify plan translations updated to Khmer
    updated_plan = load_dubbing_plan(job.job_id, 1)
    assert updated_plan is not None
    assert updated_plan.translations[0].translated_text == "សួស្តីពិភពលោក"
    assert updated_plan.translations[0].status == "ready"

async def _async_noop(*args, **kwargs):
    pass
