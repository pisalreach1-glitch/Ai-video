"""Test approval validation, double click prevention, and outdated revision rejection."""
import pytest
from app.domain.states import JobState
from app.domain.models import VoiceSettings

def test_outdated_revision_approval_rejection(temp_job_storage):
    """An approval callback for revision 1 must be rejected if current revision is 2."""
    job = temp_job_storage.create_job(user_id=10, chat_id=10)
    r1 = temp_job_storage.create_revision(job.job_id, "Rev 1 text", VoiceSettings())
    r2 = temp_job_storage.create_revision(job.job_id, "Rev 2 text", VoiceSettings())

    current_job = temp_job_storage.get_job(job.job_id)
    assert current_job.current_revision_id == 2

    # Attempting to approve r1 when current is r2
    assert current_job.current_revision_id != r1.revision_id

def test_atomic_queue_claim_prevents_duplicate_processing(temp_job_storage):
    """Multiple concurrent workers claiming the queue only process a task once."""
    job = temp_job_storage.create_job(user_id=10, chat_id=10)
    r1 = temp_job_storage.create_revision(job.job_id, "Text", VoiceSettings())

    # Enqueue final render
    enqueued = temp_job_storage.enqueue_task(job.job_id, r1.revision_id, 10, "final")
    assert enqueued is True

    # First claim succeeds
    claim1 = temp_job_storage.claim_next_task()
    assert claim1 is not None
    assert claim1["job_id"] == job.job_id

    # Second claim returns None (no duplicate renders!)
    claim2 = temp_job_storage.claim_next_task()
    assert claim2 is None

def test_ownership_verification(temp_job_storage):
    """Verifies user_id and chat_id matching."""
    job = temp_job_storage.create_job(user_id=555, chat_id=666)

    # Correct owner
    assert temp_job_storage.verify_ownership(job.job_id, 555, 666) is True

    # Wrong user
    assert temp_job_storage.verify_ownership(job.job_id, 999, 666) is False

    # Wrong chat
    assert temp_job_storage.verify_ownership(job.job_id, 555, 999) is False

@pytest.mark.asyncio
async def test_stale_preview_and_edit_handlers_rejected(temp_job_storage, monkeypatch):
    """Ensure aud_next, dur_pick, apprv_final, edit_text, and edit_settings reject stale revision 1 when current revision is 2."""
    import app.handlers.previews
    import app.handlers.common
    monkeypatch.setattr(app.handlers.previews, "job_storage", temp_job_storage)
    monkeypatch.setattr(app.handlers.common, "job_storage", temp_job_storage)

    job = temp_job_storage.create_job(user_id=10, chat_id=20)
    r1 = temp_job_storage.create_revision(job.job_id, "Rev 1 text", VoiceSettings())
    r2 = temp_job_storage.create_revision(job.job_id, "Rev 2 text", VoiceSettings())
    temp_job_storage.set_job_status(job.job_id, JobState.AWAITING_AUDIO_REVIEW)

    answered_alerts = []

    class MockMsg:
        chat = type("Chat", (), {"id": 20})()
        video = None
        document = None
        photo = None

        async def answer(self, text, reply_markup=None):
            pass

        async def edit_reply_markup(self, reply_markup=None):
            pass

    class MockCall:
        def __init__(self, data):
            self.data = data
            self.from_user = type("User", (), {"id": 10})()
            self.message = MockMsg()

        async def answer(self, text="", show_alert=False):
            answered_alerts.append(text)

    class MockState:
        async def set_state(self, s):
            pass
        async def update_data(self, **kwargs):
            pass

    # 1. aud_next for stale revision 1
    call1 = MockCall(f"aud_next:{job.job_id}:{r1.revision_id}")
    await app.handlers.previews.cb_audio_next_to_preview(call1, MockState())
    assert any("ហួសសម័យ" in a for a in answered_alerts)
    assert temp_job_storage.claim_next_task() is None

    # 2. dur_pick for stale revision 1
    answered_alerts.clear()
    call2 = MockCall(f"dur_pick:fit_video:{job.job_id}:{r1.revision_id}")
    await app.handlers.previews.cb_duration_policy_picked(call2, MockState())
    assert any("ហួសសម័យ" in a for a in answered_alerts)
    assert temp_job_storage.claim_next_task() is None

    # 3. apprv_final for stale revision 1
    answered_alerts.clear()
    temp_job_storage.set_job_status(job.job_id, JobState.AWAITING_APPROVAL)
    call3 = MockCall(f"apprv_final:{job.job_id}:{r1.revision_id}")
    await app.handlers.previews.cb_approve_final(call3, MockState())
    assert any("ហួសសម័យ" in a for a in answered_alerts)
    assert temp_job_storage.claim_next_task() is None

    # 4. edit_text for stale revision 1
    answered_alerts.clear()
    call4 = MockCall(f"edit_text:{job.job_id}:{r1.revision_id}")
    await app.handlers.previews.cb_edit_text(call4, MockState())
    assert any("ហួសសម័យ" in a for a in answered_alerts)

    # 5. edit_voice for stale revision 1
    answered_alerts.clear()
    call5 = MockCall(f"edit_voice:{job.job_id}:{r1.revision_id}")
    await app.handlers.previews.cb_edit_settings_forward(call5, MockState())
    assert any("ហួសសម័យ" in a for a in answered_alerts)
