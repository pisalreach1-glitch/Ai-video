"""Feature identifiers and pipeline dispatch contracts."""
from enum import Enum
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

class JobFeature(str, Enum):
    VIDEO_VOICEOVER = "video_voiceover"
    TALKING_PHOTO = "talking_photo"

@dataclass(frozen=True)
class QueueTask:
    job_id: str
    revision_id: int
    feature: str
    task_type: str  # 'preview' | 'final'
    user_id: int
    input_digest: str | None = None

@runtime_checkable
class FeaturePipeline(Protocol):
    def validate_task_type(self, task_type: str) -> None:
        """Validate whether the task_type is supported by this pipeline."""
        ...

    async def run(self, task: QueueTask, worker_pool: Any) -> None:
        """Execute the task within this feature's pipeline."""
        ...
