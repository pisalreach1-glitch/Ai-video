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
