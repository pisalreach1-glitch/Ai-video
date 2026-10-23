"""Tests for shared GPU Resource Scheduler."""
import asyncio
import pytest
from app.jobs.gpu_scheduler import GPUResourceScheduler

@pytest.mark.asyncio
async def test_gpu_scheduler_concurrency_one():
    scheduler = GPUResourceScheduler(concurrency=1)
    assert not scheduler.is_busy()
    assert scheduler.current_holder() is None

    execution_order = []

    async def task_a():
        async with scheduler.acquire(tag="task_a", job_id="job_1"):
            assert scheduler.is_busy()
            holder = scheduler.current_holder()
            assert holder["tag"] == "task_a"
            assert holder["job_id"] == "job_1"
            execution_order.append("a_start")
            await asyncio.sleep(0.05)
            execution_order.append("a_end")

    async def task_b():
        await asyncio.sleep(0.01) # ensure task_a acquires first
        async with scheduler.acquire(tag="task_b", job_id="job_2"):
            execution_order.append("b_start")
            holder = scheduler.current_holder()
            assert holder["tag"] == "task_b"
            assert holder["job_id"] == "job_2"
            execution_order.append("b_end")

    await asyncio.gather(task_a(), task_b())

    assert execution_order == ["a_start", "a_end", "b_start", "b_end"]
    assert not scheduler.is_busy()
    assert scheduler.current_holder() is None

@pytest.mark.asyncio
async def test_gpu_scheduler_releases_on_exception():
    scheduler = GPUResourceScheduler(concurrency=1)

    with pytest.raises(ValueError):
        async with scheduler.acquire(tag="error_task", job_id="job_err"):
            assert scheduler.is_busy()
            raise ValueError("GPU out of memory or crash")

    # Ensure lease was released
    assert not scheduler.is_busy()
    assert scheduler.current_holder() is None

    # Another task should immediately be able to acquire
    async with scheduler.acquire(tag="task_after_err", job_id="job_ok"):
        assert scheduler.is_busy()
    assert not scheduler.is_busy()
