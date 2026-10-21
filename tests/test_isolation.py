"""
Required Test 4: Isolation.
Verifies:
- Two users' videos and subtitles cannot mix (filesystem and state isolation).
- Old callbacks cannot edit a different job (callback validation rejects mismatched jobs).
"""

import os
import shutil
import pytest
from pathlib import Path
from job_manager import JobQueueManager


@pytest.fixture
def test_queue(tmp_path):
    mgr = JobQueueManager(tmp_path)
    yield mgr
    shutil.rmtree(tmp_path, ignore_errors=True)


class TestIsolation:
    def test_two_users_cannot_mix(self, test_queue):
        """Two users submitting videos concurrently have distinct directories and state."""
        user_1 = 1001
        user_2 = 2002

        job_1 = test_queue.create_job(user_id=user_1, chat_id=1001, input_filename="video1.mp4")
        job_2 = test_queue.create_job(user_id=user_2, chat_id=2002, input_filename="video2.mp4")

        # Distinct IDs
        assert job_1.job_id != job_2.job_id

        # Distinct isolated directories
        assert job_1.job_dir != job_2.job_dir
        assert job_1.job_dir.exists()
        assert job_2.job_dir.exists()

        # Input paths cannot overwrite each other
        assert job_1.input_path != job_2.input_path
        assert Path(job_1.input_path).parent == job_1.job_dir
        assert Path(job_2.input_path).parent == job_2.job_dir

        # Data isolation
        job_1.words = [{"word": "User1_word"}]
        job_2.words = [{"word": "User2_word"}]

        assert test_queue.get_user_job(user_1).words[0]["word"] == "User1_word"
        assert test_queue.get_user_job(user_2).words[0]["word"] == "User2_word"

    def test_old_callbacks_cannot_edit_different_job(self, test_queue):
        """Callbacks from an earlier completed/cancelled job must be rejected."""
        user_id = 5555

        # Create Job A
        job_a = test_queue.create_job(user_id=user_id, chat_id=5555)
        job_a_id = job_a.job_id

        # Callback for Job A is currently valid
        assert test_queue.validate_callback(user_id, job_a_id) is True

        # Job A finishes and user starts Job B
        job_a.status = "completed"
        job_b = test_queue.create_job(user_id=user_id, chat_id=5555)
        job_b_id = job_b.job_id
        assert job_a_id != job_b_id

        # Callback for new Job B is valid
        assert test_queue.validate_callback(user_id, job_b_id) is True

        # Callback for old Job A MUST be rejected
        assert test_queue.validate_callback(user_id, job_a_id) is False

    def test_cross_user_callback_rejection(self, test_queue):
        """User A cannot trigger callback for User B's job."""
        user_a = 7001
        user_b = 7002

        job_b = test_queue.create_job(user_id=user_b, chat_id=7002)

        # User A tries to pass Job B's ID in callback
        assert test_queue.validate_callback(user_a, job_b.job_id) is False
