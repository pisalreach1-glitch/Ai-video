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

def test_recover_interrupted_jobs_on_startup(temp_job_storage):
    """Verify that jobs in processing or queued states are safely recovered to INTERRUPTED."""
    job1 = temp_job_storage.create_job(user_id=1, chat_id=1)
    temp_job_storage.set_job_status(job1.job_id, JobState.RENDERING)
    temp_job_storage.enqueue_task(job1.job_id, 1, 1, "final")
    # Simulate worker claiming the task so it becomes 'processing'
    temp_job_storage.claim_next_task()

    job2 = temp_job_storage.create_job(user_id=2, chat_id=2)
    temp_job_storage.set_job_status(job2.job_id, JobState.PREVIEW_RENDERING)

    recovered = temp_job_storage.recover_interrupted_jobs()
    assert recovered >= 2

    j1_after = temp_job_storage.get_job(job1.job_id)
    assert j1_after.status == JobState.INTERRUPTED
    assert "interrupted" in j1_after.stage

    j2_after = temp_job_storage.get_job(job2.job_id)
    assert j2_after.status == JobState.INTERRUPTED
    assert j2_after.stage == "interrupted:preview_rendering"

@pytest.mark.asyncio
async def test_retry_interrupted_downloading_job_without_revision(temp_job_storage, monkeypatch):
    """Verify that retrying a job interrupted during downloading works even when no revision has been created yet."""
    import app.handlers.jobs
    monkeypatch.setattr(app.handlers.jobs, "job_storage", temp_job_storage)

    job = temp_job_storage.create_job(user_id=10, chat_id=20, source_type="link")
    temp_job_storage.set_job_status(job.job_id, JobState.INTERRUPTED, stage="interrupted:downloading")

    # Confirm there are NO revisions for this job
    assert temp_job_storage.get_latest_revision(job.job_id) is None

    answered_text = None
    edited_text = None

    class MockMsg:
        chat = type("Chat", (), {"id": 20})()
        video = None
        document = None
        photo = None

        async def edit_text(self, text, reply_markup=None):
            nonlocal edited_text
            edited_text = text

    class MockCall:
        data = f"retry_job:{job.job_id}:1"
        from_user = type("User", (), {"id": 10})()
        message = MockMsg()

        async def answer(self, text="", show_alert=False):
            nonlocal answered_text
            answered_text = text

    class MockState:
        current_state = None
        stored_data = {}

        async def set_state(self, s):
            self.current_state = s

        async def update_data(self, **kwargs):
            self.stored_data.update(kwargs)

    state = MockState()
    call = MockCall()

    await app.handlers.jobs.cb_retry_interrupted_job(call, state, None)

    # Must NOT return "Job or revision not found."
    assert answered_text != "Job or revision not found."
    assert "សូមផ្ញើ Link ឬ Upload វីដេអូឡើងវិញ" in answered_text

    # Job status reset to AWAITING_SOURCE
    refreshed = temp_job_storage.get_job(job.job_id)
    assert refreshed.status == JobState.AWAITING_SOURCE
