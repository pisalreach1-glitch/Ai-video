"""Domain models for Source-Timed Khmer Dubbing."""
from __future__ import annotations
import json
from dataclasses import dataclass, field, asdict
from typing import Any

from app.domain.speakers import (
    SpeakerProfile,
    SpeakerTurn,
    SpeakerAssignment,
    VoiceChoice,
    ReviewIssue,
)

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
    speaker_id: str | None = None
    speaker_assignment_origin: str = "auto" # "auto" | "manual" | "legacy"
    speaker_evidence_key: str = ""
    parent_segment_id: str | None = None

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
            speaker_id=str(data["speaker_id"]) if data.get("speaker_id") is not None else None,
            speaker_assignment_origin=str(data.get("speaker_assignment_origin", "auto")),
            speaker_evidence_key=str(data.get("speaker_evidence_key", "")),
            parent_segment_id=str(data["parent_segment_id"]) if data.get("parent_segment_id") is not None else None,
        )

@dataclass
class TranslatedSegment:
    segment_id: str
    translated_text: str
    translation_provider: str = "gemini"
    status: str = "pending" # "pending" | "ready" | "needs_review"
    full_translation: str = ""
    proposed_concise_text: str | None = None

    def __post_init__(self) -> None:
        if not self.full_translation and self.translated_text:
            self.full_translation = self.translated_text

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TranslatedSegment:
        return cls(
            segment_id=str(data["segment_id"]),
            translated_text=str(data["translated_text"]),
            translation_provider=str(data.get("translation_provider", "gemini")),
            status=str(data.get("status", "pending")),
            full_translation=str(data.get("full_translation", data["translated_text"])),
            proposed_concise_text=str(data["proposed_concise_text"]) if data.get("proposed_concise_text") is not None else None,
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
    producer: str = "fit" # "fit" | "sync_validation" | "speaker_review"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DubbingIssue:
        return cls(
            segment_id=str(data["segment_id"]),
            issue_type=str(data["issue_type"]),
            message=str(data["message"]),
            severity=str(data.get("severity", "blocking")),
            producer=str(data.get("producer", "fit")),
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
    # Multi-speaker extensions & Sync policy
    schema_version: int = 2
    plan_version: int = 1
    sync_policy_metadata: dict[str, Any] = field(default_factory=dict)
    preview_artifact_identity: dict[str, Any] = field(default_factory=dict)
    speaker_mode: str = "single" # "single" | "multi"
    source_analysis_key: str = ""
    speakers: list[SpeakerProfile] = field(default_factory=list)
    speaker_turns: list[SpeakerTurn] = field(default_factory=list)
    speaker_assignments: list[SpeakerAssignment] = field(default_factory=list)
    speaker_voice_map: dict[str, VoiceChoice] = field(default_factory=dict)
    review_issues: list[ReviewIssue] = field(default_factory=list)
    preview_plan_digest: str | None = None
    full_preview_approved_digest: str | None = None

    @property
    def has_blocking_issues(self) -> bool:
        has_fit_blocking = any(issue.severity == "blocking" for issue in self.issues)
        has_review_blocking = any(issue.blocking and issue.is_open for issue in self.review_issues)
        return has_fit_blocking or has_review_blocking

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

    def get_speaker(self, speaker_id: str) -> SpeakerProfile | None:
        for spk in self.speakers:
            if spk.speaker_id == speaker_id:
                return spk
        return None

    def get_assignment(self, segment_id: str) -> SpeakerAssignment | None:
        for asgn in self.speaker_assignments:
            if asgn.segment_id == segment_id:
                return asgn
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
            "schema_version": self.schema_version,
            "plan_version": self.plan_version,
            "sync_policy_metadata": self.sync_policy_metadata,
            "preview_artifact_identity": self.preview_artifact_identity,
            "speaker_mode": self.speaker_mode,
            "source_analysis_key": self.source_analysis_key,
            "speakers": [spk.to_dict() for spk in self.speakers],
            "speaker_turns": [turn.to_dict() for turn in self.speaker_turns],
            "speaker_assignments": [asgn.to_dict() for asgn in self.speaker_assignments],
            "speaker_voice_map": {k: v.to_dict() for k, v in self.speaker_voice_map.items()},
            "review_issues": [issue.to_dict() for issue in self.review_issues],
            "preview_plan_digest": self.preview_plan_digest,
            "full_preview_approved_digest": self.full_preview_approved_digest,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DubbingPlan:
        # Backward compatibility for old JSON schema
        voice_map_data = data.get("speaker_voice_map", {})
        voice_map: dict[str, VoiceChoice] = {}
        if isinstance(voice_map_data, dict):
            for k, v in voice_map_data.items():
                if isinstance(v, dict):
                    voice_map[k] = VoiceChoice.from_dict(v)

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
            schema_version=int(data.get("schema_version", 2 if "speakers" in data else 1)),
            plan_version=int(data.get("plan_version", 1)),
            sync_policy_metadata=data.get("sync_policy_metadata", {}),
            preview_artifact_identity=data.get("preview_artifact_identity", {}),
            speaker_mode=str(data.get("speaker_mode", "single")),
            source_analysis_key=str(data.get("source_analysis_key", "")),
            speakers=[SpeakerProfile.from_dict(spk) for spk in data.get("speakers", [])],
            speaker_turns=[SpeakerTurn.from_dict(turn) for turn in data.get("speaker_turns", [])],
            speaker_assignments=[SpeakerAssignment.from_dict(asgn) for asgn in data.get("speaker_assignments", [])],
            speaker_voice_map=voice_map,
            review_issues=[ReviewIssue.from_dict(issue) for issue in data.get("review_issues", [])],
            preview_plan_digest=data.get("preview_plan_digest"),
            full_preview_approved_digest=data.get("full_preview_approved_digest"),
        )

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_json(cls, json_str: str) -> DubbingPlan:
        return cls.from_dict(json.loads(json_str))
