"""Domain models for Source-Timed Khmer Dubbing."""
from __future__ import annotations
import json
from dataclasses import dataclass, field, asdict
from typing import Any

@dataclass
class SourceSegment:
    segment_id: str
    start_ms: int
    end_ms: int
    source_text: str
    source_language: str = "en"
    words: list[dict[str, Any]] | None = None
    timing_origin: str = "local_asr" # "local_asr" | "imported_srt" | "user_corrected"
    needs_review: bool = False

    @property
    def duration_ms(self) -> int:
        return max(0, self.end_ms - self.start_ms)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourceSegment:
        return cls(
            segment_id=str(data["segment_id"]),
            start_ms=int(data["start_ms"]),
            end_ms=int(data["end_ms"]),
            source_text=str(data["source_text"]),
            source_language=str(data.get("source_language", "en")),
            words=data.get("words"),
            timing_origin=str(data.get("timing_origin", "local_asr")),
            needs_review=bool(data.get("needs_review", False)),
        )

@dataclass
class TranslatedSegment:
    segment_id: str
    translated_text: str
    translation_provider: str = "gemini"
    status: str = "pending" # "pending" | "ready" | "needs_review"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TranslatedSegment:
        return cls(
            segment_id=str(data["segment_id"]),
            translated_text=str(data["translated_text"]),
            translation_provider=str(data.get("translation_provider", "gemini")),
            status=str(data.get("status", "pending")),
        )

@dataclass
class DubClip:
    segment_id: str
    tts_cache_key: str
    raw_audio_path: str
    fitted_audio_path: str | None = None
    raw_duration_ms: int = 0
    fitted_duration_ms: int | None = None
    tempo_factor: float = 1.0
    tts_events: list[dict[str, Any]] = field(default_factory=list) # local timing within this generated clip
    status: str = "pending" # "pending" | "ready" | "too_long" | "failed"

    @property
    def effective_duration_ms(self) -> int:
        if self.fitted_duration_ms is not None:
            return self.fitted_duration_ms
        return self.raw_duration_ms

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DubClip:
        return cls(
            segment_id=str(data["segment_id"]),
            tts_cache_key=str(data.get("tts_cache_key", "")),
            raw_audio_path=str(data["raw_audio_path"]),
            fitted_audio_path=data.get("fitted_audio_path"),
            raw_duration_ms=int(data.get("raw_duration_ms", 0)),
            fitted_duration_ms=int(data["fitted_duration_ms"]) if data.get("fitted_duration_ms") is not None else None,
            tempo_factor=float(data.get("tempo_factor", 1.0)),
            tts_events=data.get("tts_events", []),
            status=str(data.get("status", "pending")),
        )

@dataclass
class Placement:
    segment_id: str
    timeline_start_ms: int
    slot_end_ms: int
    speech_end_ms: int
    start_sample: int
    sample_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Placement:
        return cls(
            segment_id=str(data["segment_id"]),
            timeline_start_ms=int(data["timeline_start_ms"]),
            slot_end_ms=int(data["slot_end_ms"]),
            speech_end_ms=int(data["speech_end_ms"]),
            start_sample=int(data["start_sample"]),
            sample_count=int(data["sample_count"]),
        )

@dataclass
class DubbingIssue:
    segment_id: str
    issue_type: str # "too_long" | "collision" | "overrun" | "missing_translation"
    message: str
    severity: str = "blocking" # "blocking" | "warning"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DubbingIssue:
        return cls(
            segment_id=str(data["segment_id"]),
            issue_type=str(data["issue_type"]),
            message=str(data["message"]),
            severity=str(data.get("severity", "blocking")),
        )

@dataclass
class DubbingPlan:
    mode: str = "source_timed"
    source_fingerprint: str = ""
    source_duration_ms: int = 0
    timeline_origin_metadata: dict[str, Any] = field(default_factory=dict)
    sample_rate: int = 48000
    segments: list[SourceSegment] = field(default_factory=list)
    translations: list[TranslatedSegment] = field(default_factory=list)
    clips: list[DubClip] = field(default_factory=list)
    placements: list[Placement] = field(default_factory=list)
    issues: list[DubbingIssue] = field(default_factory=list)

    @property
    def has_blocking_issues(self) -> bool:
        return any(issue.severity == "blocking" for issue in self.issues)

    def get_segment(self, segment_id: str) -> SourceSegment | None:
        for s in self.segments:
            if s.segment_id == segment_id:
                return s
        return None

    def get_translation(self, segment_id: str) -> TranslatedSegment | None:
        for t in self.translations:
            if t.segment_id == segment_id:
                return t
        return None

    def get_clip(self, segment_id: str) -> DubClip | None:
        for c in self.clips:
            if c.segment_id == segment_id:
                return c
        return None

    def get_placement(self, segment_id: str) -> Placement | None:
        for p in self.placements:
            if p.segment_id == segment_id:
                return p
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "source_fingerprint": self.source_fingerprint,
            "source_duration_ms": self.source_duration_ms,
            "timeline_origin_metadata": self.timeline_origin_metadata,
            "sample_rate": self.sample_rate,
            "segments": [s.to_dict() for s in self.segments],
            "translations": [t.to_dict() for t in self.translations],
            "clips": [c.to_dict() for c in self.clips],
            "placements": [p.to_dict() for p in self.placements],
            "issues": [i.to_dict() for i in self.issues],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DubbingPlan:
        return cls(
            mode=str(data.get("mode", "source_timed")),
            source_fingerprint=str(data.get("source_fingerprint", "")),
            source_duration_ms=int(data.get("source_duration_ms", 0)),
            timeline_origin_metadata=data.get("timeline_origin_metadata", {}),
            sample_rate=int(data.get("sample_rate", 48000)),
            segments=[SourceSegment.from_dict(s) for s in data.get("segments", [])],
            translations=[TranslatedSegment.from_dict(t) for t in data.get("translations", [])],
            clips=[DubClip.from_dict(c) for c in data.get("clips", [])],
            placements=[Placement.from_dict(p) for p in data.get("placements", [])],
            issues=[DubbingIssue.from_dict(i) for i in data.get("issues", [])],
        )

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_json(cls, json_str: str) -> DubbingPlan:
        return cls.from_dict(json.loads(json_str))
