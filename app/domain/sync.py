"""Explicit speech-window bounds. Defaults are configurable engineering choices."""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class SyncPolicy:
    max_tempo: float = 1.15
    start_tolerance_ms: int = 80
    end_tolerance_ms: int = 120
    filter_duration_tolerance_ms: int = 80
    guard_ms: int = 0
    sample_rate: int = 48000

    def __post_init__(self):
        if not math.isfinite(self.max_tempo) or not 1 <= self.max_tempo <= 2:
            raise ValueError("invalid_max_tempo")
        if min(self.start_tolerance_ms, self.end_tolerance_ms, self.filter_duration_tolerance_ms, self.guard_ms) < 0:
            raise ValueError("negative_tolerance")
        if self.sample_rate <= 0:
            raise ValueError("invalid_sample_rate")


@dataclass(frozen=True)
class SpeechSlot:
    segment_id: str
    start_ms: int
    source_end_ms: int
    target_end_ms: int
    hard_end_ms: int

    def start_sample(self, rate: int) -> int:
        return round(self.start_ms * rate / 1000)

    def target_frames(self, rate: int) -> int:
        return round(self.target_end_ms * rate / 1000) - self.start_sample(rate)

    def hard_frames(self, rate: int) -> int:
        return round(self.hard_end_ms * rate / 1000) - self.start_sample(rate)


@dataclass(frozen=True)
class SyncProblem:
    segment_id: str
    issue_type: str
    message: str
    severity: str = "blocking"
    producer: str = "sync_validation"


class SyncPlanningError(ValueError):
    pass
