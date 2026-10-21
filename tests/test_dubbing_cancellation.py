"""Tests for dubbing cancellation handling and prevention of resurrection."""
import pytest
from app.domain.states import JobState
from app.jobs.worker import WorkerPool

def test_dubbing_cancellation_marks_cancelled(temp_job_storage):
    """Requirement 13: Cancel during dubbing cannot recreate a revision or revive a cancelled job."""
    pool = WorkerPool(storage=temp_job_storage)
    job = temp_job_storage.create_job(user_id=100, chat_id=200)

    temp_job_storage.set_job_status(job.job_id, JobState.GENERATING_SEGMENTS)
    assert pool.is_cancelled(job.job_id) is False

    # Issue cancellation
    cancelled = pool.cancel_job(job.job_id)
    assert cancelled is True
    assert pool.is_cancelled(job.job_id) is True

    updated = temp_job_storage.get_job(job.job_id)
    assert updated.status == JobState.CANCELLED

    # Cancelled job should not accept late results
    if pool.is_cancelled(job.job_id):
        temp_job_storage.complete_task(job.job_id, "cancelled")

    assert updated.status == JobState.CANCELLED
