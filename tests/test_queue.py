"""
Required Test 5: Queue & Capacity limits.
Verifies:
- Per-user concurrent job limits prevent double submission.
- Global queue capacity limit rejects overflow gracefully.
- Non-blocking /status reporting remains responsive while work runs.
"""

import time
import shutil
import pytest
from job_manager import JobQueueManager, MAX_QUEUE_SIZE
from errors import BotProcessingError


@pytest.fixture
def queue_mgr(tmp_path):
    mgr = JobQueueManager(tmp_path)
    yield mgr
    shutil.rmtree(tmp_path, ignore_errors=True)


class TestQueue:
    def test_per_user_limit_enforced(self, queue_mgr):
        """User cannot create a second active job while one is queued or running."""
        user_id = 9999
        job_1 = queue_mgr.create_job(user_id=user_id, chat_id=123)
        assert job_1.is_active() is True

        # Attempting second job should raise BotProcessingError
        with pytest.raises(BotProcessingError) as exc_info:
            queue_mgr.create_job(user_id=user_id, chat_id=123)
        assert exc_info.value.error_code == "USER_JOB_LIMIT_EXCEEDED"

        # Once job_1 completes, user can submit again
        job_1.status = "completed"
        job_2 = queue_mgr.create_job(user_id=user_id, chat_id=123)
        assert job_2.job_id != job_1.job_id
        assert job_2.is_active() is True

    def test_queue_capacity_limit(self, queue_mgr):
        """Queue capacity limit rejects jobs exceeding MAX_QUEUE_SIZE."""
        created_jobs = []
        for i in range(MAX_QUEUE_SIZE):
            job = queue_mgr.create_job(user_id=10000 + i, chat_id=10000 + i)
            created_jobs.append(job)

        # The (MAX_QUEUE_SIZE + 1)th job must be rejected
        with pytest.raises(BotProcessingError) as exc_info:
            queue_mgr.create_job(user_id=99999, chat_id=99999)
        assert exc_info.value.error_code == "QUEUE_FULL"

    def test_status_remains_responsive(self, queue_mgr):
        """Checking status must be instantaneous and non-blocking."""
        user_id = 8888
        job = queue_mgr.create_job(user_id=user_id, chat_id=8888)
        job.status = "running"
        job.started_at = time.time() - 15.0

        t0 = time.time()
        summary = queue_mgr.get_status_summary(user_id)
        elapsed = time.time() - t0

        # Non-blocking query executes in milliseconds (< 50ms)
        assert elapsed < 0.05
        assert summary["user_job"].job_id == job.job_id
        assert summary["user_job"].status == "running"
        assert summary["total_running"] == 1
        assert summary["total_queued"] == 0
