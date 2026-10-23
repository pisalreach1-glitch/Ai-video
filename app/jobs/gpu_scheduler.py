"""Shared GPU Resource Scheduler for single RTX 3060 allocation."""
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Any
from app.config import config

logger = logging.getLogger(__name__)

class GPUResourceScheduler:
    """
    Ensures that only one heavy GPU inference workload runs on the RTX 3060 at a time.
    Covers Talking Photo (SadTalker), local Whisper ASR, Pyannote diarization, etc.
    """
    def __init__(self, concurrency: int = 1):
        self._concurrency = max(1, concurrency)
        self._sem = asyncio.Semaphore(self._concurrency)
        self._active_holder: dict[str, Any] | None = None
        self._lock = asyncio.Lock()

    @property
    def concurrency(self) -> int:
        return self._concurrency

    def is_busy(self) -> bool:
        return self._active_holder is not None

    def current_holder(self) -> dict[str, Any] | None:
        return dict(self._active_holder) if self._active_holder else None

    @asynccontextmanager
    async def acquire(self, tag: str, job_id: str) -> AsyncIterator[None]:
        logger.info(f"GPU lease requested by {tag} for job {job_id}")
        await self._sem.acquire()
        async with self._lock:
            self._active_holder = {"tag": tag, "job_id": job_id}
        logger.info(f"GPU lease GRANTED to {tag} for job {job_id}")
        try:
            yield
        finally:
            async with self._lock:
                if self._active_holder and self._active_holder.get("job_id") == job_id:
                    self._active_holder = None
            self._sem.release()
            logger.info(f"GPU lease RELEASED by {tag} for job {job_id}")

gpu_scheduler = GPUResourceScheduler(concurrency=getattr(config, "gpu_inference_concurrency", 1))
