"""Test cancellation and subprocess tree termination."""
import sys
import time
import subprocess
import psutil
import pytest
from app.jobs.processes import run_process, kill_process_tree, ProcessResult
from app.jobs.worker import WorkerPool
from app.domain.states import JobState

def test_kill_process_tree_terminates_all_children():
    """Verify that kill_process_tree terminates a process and all nested subprocesses."""
    # Launch a parent python process that launches a child sleep process
    script = (
        "import subprocess, sys, time; "
        "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
        "p.wait()"
    )
    parent = subprocess.Popen([sys.executable, "-c", script])
    time.sleep(0.5)

    try:
        proc = psutil.Process(parent.pid)
        children = proc.children(recursive=True)
        assert len(children) >= 1
        child_pid = children[0].pid

        # Kill tree
        kill_process_tree(parent.pid)
        time.sleep(0.5)

        assert not psutil.pid_exists(parent.pid)
        assert not psutil.pid_exists(child_pid)
    finally:
        try:
            parent.kill()
        except Exception:
            pass

@pytest.mark.asyncio
async def test_worker_cancellation_sets_job_state(temp_job_storage):
    """Cancelling a job via WorkerPool sets state to CANCELLED and marks queue item."""
    job = temp_job_storage.create_job(user_id=1, chat_id=1)
    temp_job_storage.enqueue_task(job.job_id, 1, 1, "final")

    pool = WorkerPool(storage=temp_job_storage)
    pool.cancel_job(job.job_id)

    assert pool.is_cancelled(job.job_id) is True
    updated = temp_job_storage.get_job(job.job_id)
    assert updated.status == JobState.CANCELLED
