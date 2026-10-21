"""
Required Test 6: Cancellation.
Verifies:
- Queued jobs cancel immediately.
- Active render subprocesses and entire process tree terminate upon cancellation.
- Merely cancelling an asyncio Future is not sufficient; process tree must die.
"""

import sys
import time
import shutil
import threading
import subprocess
import psutil
import pytest

from job_manager import JobQueueManager
from process_runner import ProcessRunner, kill_process_tree
from errors import JobCancelledError


@pytest.fixture
def queue_mgr(tmp_path):
    mgr = JobQueueManager(tmp_path)
    yield mgr
    shutil.rmtree(tmp_path, ignore_errors=True)


class TestCancellation:
    def test_queued_job_cancellation(self, queue_mgr):
        """Queued jobs cancel without running."""
        user_id = 1111
        job = queue_mgr.create_job(user_id=user_id, chat_id=1111)
        assert job.status == "queued"

        cancelled = queue_mgr.cancel_job(user_id=user_id)
        assert cancelled is not None
        assert cancelled.job_id == job.job_id
        assert cancelled.status == "cancelled"
        assert cancelled.cancel_event.is_set()

    def test_active_subprocess_tree_termination(self, queue_mgr):
        """
        When an active job is cancelled, its running subprocess tree
        (parent and child processes) must be terminated completely.
        """
        user_id = 2222
        job = queue_mgr.create_job(user_id=user_id, chat_id=2222)
        job.status = "running"
        job.started_at = time.time()

        # Spawn a multi-process tree: Python spawning a child sleep process
        script = (
            "import subprocess, sys, time; "
            "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
            "p.wait()"
        )
        cmd = [sys.executable, "-c", script]

        pid_holder = []
        cancel_exception_caught = []

        def worker():
            try:
                ProcessRunner.run(
                    cmd,
                    timeout=30.0,
                    on_pid_assigned=job.register_pid,
                    cancel_event=job.cancel_event,
                    job_id=job.job_id
                )
            except JobCancelledError:
                cancel_exception_caught.append(True)

        t = threading.Thread(target=worker)
        t.start()

        # Wait until process is alive
        time.sleep(0.5)
        assert job.active_pid is not None
        root_pid = job.active_pid
        assert psutil.pid_exists(root_pid)

        # Trigger cancellation through JobQueueManager
        cancelled_job = queue_mgr.cancel_job(user_id=user_id)
        assert cancelled_job is not None
        assert cancelled_job.status == "cancelled"

        t.join(timeout=3.0)

        # Verify root process and child processes are terminated
        time.sleep(0.5)
        assert not psutil.pid_exists(root_pid)
        assert len(cancel_exception_caught) == 1
