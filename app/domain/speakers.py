"""Domain models for Multi-Speaker Khmer Dubbing."""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from typing import Any, Literal


@dataclass(frozen=True)
class SpeakerTurn:
    speaker_id: str
    start_ms: int
    end_ms: int

    def __post_init__(self) -> None:
        if not self.speaker_id:
            raise ValueError("speaker_id cannot be empty")
        if self.start_ms < 0:
            raise ValueError(f"start_ms must be non-negative, got {self.start_ms}")
        if self.end_ms <= self.start_ms:
            raise ValueError(f"end_ms ({self.end_ms}) must be strictly greater than start_ms ({self.start_ms})")

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SpeakerTurn:
        return cls(
            speaker_id=str(data["speaker_id"]),
            start_ms=int(data["start_ms"]),
            end_ms=int(data["end_ms"]),
        )


@dataclass(frozen=True)
class SpeakerProfile:
    speaker_id: str
    display_name: str
    analysis_key: str

    def __post_init__(self) -> None:
        if not self.speaker_id:
            raise ValueError("speaker_id cannot be empty")
        if not self.display_name:
            raise ValueError("display_name cannot be empty")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SpeakerProfile:
        return cls(
            speaker_id=str(data["speaker_id"]),
            display_name=str(data.get("display_name", data["speaker_id"])),
            analysis_key=str(data.get("analysis_key", "")),
        )


@dataclass(frozen=True)
class VoiceChoice:
    voice_id: str
    rate: str = "+0%"
    confirmed: bool = False

    def __post_init__(self) -> None:
        if not self.voice_id:
            raise ValueError("voice_id cannot be empty")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VoiceChoice:
        return cls(
            voice_id=str(data["voice_id"]),
            rate=str(data.get("rate", "+0%")),
            confirmed=bool(data.get("confirmed", False)),
        )


ALLOWED_ORIGINS = {"auto", "manual", "legacy"}
ALLOWED_CONFIDENCE_KINDS = {"unavailable", "uncalibrated", "calibrated"}


@dataclass(frozen=True)
class SpeakerAssignment:
    segment_id: str
    speaker_id: str | None
    evidence_key: str
    origin: Literal["auto", "manual", "legacy"] = "auto"
    confirmed_by_user: bool = False
    confidence: float | None = None
    confidence_kind: Literal["unavailable", "uncalibrated", "calibrated"] = "unavailable"

    def __post_init__(self) -> None:
        if not self.segment_id:
            raise ValueError("segment_id cannot be empty")
        if self.origin not in ALLOWED_ORIGINS:
            raise ValueError(f"Invalid origin: {self.origin}, must be one of {ALLOWED_ORIGINS}")
        if self.confidence_kind not in ALLOWED_CONFIDENCE_KINDS:
            raise ValueError(
                f"Invalid confidence_kind: {self.confidence_kind}, must be one of {ALLOWED_CONFIDENCE_KINDS}"
            )
        if self.confidence is not None:
            if not math.isfinite(self.confidence):
                raise ValueError("confidence must be a finite number or None")
            if not (0.0 <= self.confidence <= 1.0):
                raise ValueError(f"confidence must be between 0.0 and 1.0, got {self.confidence}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SpeakerAssignment:
        conf = data.get("confidence")
        if conf is not None:
            conf = float(conf)
        return cls(
            segment_id=str(data["segment_id"]),
            speaker_id=str(data["speaker_id"]) if data.get("speaker_id") is not None else None,
            evidence_key=str(data.get("evidence_key", "")),
            origin=str(data.get("origin", "auto")),  # type: ignore
            confirmed_by_user=bool(data.get("confirmed_by_user", False)),
            confidence=conf,
            confidence_kind=str(data.get("confidence_kind", "unavailable")),  # type: ignore
        )


@dataclass(frozen=True)
class ReviewIssue:
    issue_id: str
    segment_id: str
    reason: str
    subject_key: str
    producer: str = "speaker_review"
    blocking: bool = True
    allow_confirmation: bool = False
    confirmed_for_key: str | None = None

    def __post_init__(self) -> None:
        if not self.issue_id:
            raise ValueError("issue_id cannot be empty")
        if not self.segment_id:
            raise ValueError("segment_id cannot be empty")
        if not self.reason:
            raise ValueError("reason cannot be empty")

    @property
    def is_open(self) -> bool:
        """
        Only reviewable uncertainty can be acknowledged. A hard failure must
        disappear through corrected inputs and successful revalidation.
        """
        return not (
            self.allow_confirmation
            and bool(self.subject_key)
            and self.confirmed_for_key == self.subject_key
        )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["is_open"] = self.is_open
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReviewIssue:
        return cls(
            issue_id=str(data["issue_id"]),
            segment_id=str(data["segment_id"]),
            reason=str(data["reason"]),
            subject_key=str(data.get("subject_key", "")),
            producer=str(data.get("producer", "speaker_review")),
            blocking=bool(data.get("blocking", True)),
            allow_confirmation=bool(data.get("allow_confirmation", False)),
            confirmed_for_key=str(data["confirmed_for_key"]) if data.get("confirmed_for_key") is not None else None,
        )
