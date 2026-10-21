"""
Required Test 7: Cleanup & Retention.
Verifies:
- Active or queued jobs are NEVER deleted.
- Expired jobs beyond retention hours are safely removed.
- Path traversal guards prevent deletion outside designated temp directories.
"""

import os
import time
import shutil
import pytest
from pathlib import Path
from cleanup_manager import CleanupManager, is_safe_deletion_path


@pytest.fixture
def cleanup_env(tmp_path):
    temp_dir = tmp_path / "temp"
    cache_dir = tmp_path / "cache"
    temp_dir.mkdir()
    cache_dir.mkdir()
    mgr = CleanupManager(temp_dir=temp_dir, cache_dir=cache_dir, retention_hours=1.0)
    yield mgr, temp_dir, cache_dir
    shutil.rmtree(tmp_path, ignore_errors=True)


class TestCleanup:
    def test_active_jobs_survive_cleanup(self, cleanup_env):
        """Files and directories of running or queued jobs must never be deleted."""
        mgr, temp_dir, _ = cleanup_env

        jobs_dir = temp_dir / "jobs"
        active_job_id = "job_active_123"
        expired_job_id = "job_expired_456"

        active_path = jobs_dir / active_job_id
        expired_path = jobs_dir / expired_job_id
        active_path.mkdir(parents=True)
        expired_path.mkdir(parents=True)

        # Make both old (mtime 5 hours ago)
        old_time = time.time() - (5 * 3600)
        os.utime(active_path, (old_time, old_time))
        os.utime(expired_path, (old_time, old_time))

        # Run cleanup while active_job_id is in active_job_ids set
        stats = mgr.cleanup_expired_jobs(active_job_ids={active_job_id}, force_retention_seconds=3600.0)

        # Active job survived
        assert active_path.exists() is True

        # Expired job was deleted
        assert expired_path.exists() is False
        assert stats["deleted_jobs"] == 1

    def test_path_traversal_guard(self, cleanup_env):
        """Security guard must block deletion paths outside allowed directories."""
        mgr, temp_dir, cache_dir = cleanup_env
        allowed = [temp_dir, cache_dir]

        # Valid paths inside temp_dir
        valid_sub = temp_dir / "jobs" / "job_01"
        assert is_safe_deletion_path(valid_sub, allowed) is True

        # Malicious traversal attempts
        outside_path = temp_dir.parent / "important_system_file.txt"
        assert is_safe_deletion_path(outside_path, allowed) is False

        root_traversal = Path("C:/Windows/System32") if os.name == "nt" else Path("/etc")
        assert is_safe_deletion_path(root_traversal, allowed) is False

        # Attempt to delete the temp_dir itself must also be blocked
        assert is_safe_deletion_path(temp_dir, allowed) is False
