"""Domain models for Voiceover Bot."""
import json
import hashlib
from dataclasses import dataclass, field, asdict
from typing import Any
from app.domain.states import JobState
from app.domain.features import JobFeature

@dataclass
class MediaInfo:
    width: int
    height: int
    duration: float
    has_audio: bool
    fps: float = 30.0
    format_name: str = "mp4"
    size_bytes: int = 0

    @property
    def aspect_ratio_str(self) -> str:
        if self.width <= 0 or self.height <= 0:
            return "unknown"
        ratio = self.width / self.height
        if abs(ratio - 9/16) < 0.05:
            return "9:16"
        if abs(ratio - 16/9) < 0.05:
            return "16:9"
        if abs(ratio - 1.0) < 0.05:
            return "1:1"
        return f"{self.width}:{self.height}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "MediaInfo | None":
        if not data:
            return None
        return cls(
            width=int(data.get("width", 0)),
            height=int(data.get("height", 0)),
            duration=float(data.get("duration", 0.0)),
            has_audio=bool(data.get("has_audio", False)),
            fps=float(data.get("fps", 30.0)),
            format_name=str(data.get("format_name", "mp4")),
            size_bytes=int(data.get("size_bytes", 0)),
        )

@dataclass
class VoiceSettings:
    voice: str = "km-KH-SreymomNeural"
    speed: str = "+0%"
    subtitles_enabled: bool = True
    subtitle_color: str = "white"        # "white" | "yellow"
    subtitle_position: str = "bottom"    # "bottom" | "middle"
    source_audio_mode: str = "mute"      # "mute" | "low_mix"
    aspect_ratio: str = "original"       # "original" | "9:16" | "1:1"
    framing_mode: str = "fit"            # "fit" (pad) | "fill" (crop)
    duration_policy: str = "extend"      # "extend" | "loop" | "shorten"

    def tts_key(self, narration_text: str) -> str:
        raw = f"{self.voice}:{self.speed}:{narration_text.strip()}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def render_key(self, narration_text: str) -> str:
        raw = (
            f"{self.tts_key(narration_text)}:"
            f"{self.subtitles_enabled}:{self.subtitle_color}:{self.subtitle_position}:"
            f"{self.source_audio_mode}:{self.aspect_ratio}:{self.framing_mode}:{self.duration_policy}"
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "VoiceSettings":
        if not data:
            return cls()
        return cls(
            voice=str(data.get("voice", "km-KH-SreymomNeural")),
            speed=str(data.get("speed", "+0%")),
            subtitles_enabled=bool(data.get("subtitles_enabled", True)),
            subtitle_color=str(data.get("subtitle_color", "white")),
            subtitle_position=str(data.get("subtitle_position", "bottom")),
            source_audio_mode=str(data.get("source_audio_mode", "mute")),
            aspect_ratio=str(data.get("aspect_ratio", "original")),
            framing_mode=str(data.get("framing_mode", "fit")),
            duration_policy=str(data.get("duration_policy", "extend")),
        )

@dataclass
class Revision:
    revision_id: int
    job_id: str
    narration_text: str
    settings: VoiceSettings = field(default_factory=VoiceSettings)
    audio_path: str | None = None
    audio_duration: float = 0.0
    subtitles_srt: str | None = None
    subtitles_ass: str | None = None
    preview_path: str | None = None
    final_path: str | None = None
    mode: str = "free_narration"       # "free_narration" | "source_timed"
    dubbing_plan_path: str | None = None
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "revision_id": self.revision_id,
            "job_id": self.job_id,
            "narration_text": self.narration_text,
            "settings": self.settings.to_dict(),
            "audio_path": self.audio_path,
            "audio_duration": self.audio_duration,
            "subtitles_srt": self.subtitles_srt,
            "subtitles_ass": self.subtitles_ass,
            "preview_path": self.preview_path,
            "final_path": self.final_path,
            "mode": self.mode,
            "dubbing_plan_path": self.dubbing_plan_path,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Revision":
        settings_raw = data.get("settings")
        if isinstance(settings_raw, str):
            try:
                settings_dict = json.loads(settings_raw)
            except Exception:
                settings_dict = {}
        elif isinstance(settings_raw, dict):
            settings_dict = settings_raw
        else:
            settings_dict = {}

        return cls(
            revision_id=int(data["revision_id"]),
            job_id=str(data["job_id"]),
            narration_text=str(data.get("narration_text", "")),
            settings=VoiceSettings.from_dict(settings_dict),
            audio_path=data.get("audio_path"),
            audio_duration=float(data.get("audio_duration", 0.0)),
            subtitles_srt=data.get("subtitles_srt"),
            subtitles_ass=data.get("subtitles_ass"),
            preview_path=data.get("preview_path"),
            final_path=data.get("final_path"),
            mode=str(data.get("mode", "free_narration")),
            dubbing_plan_path=data.get("dubbing_plan_path"),
            created_at=float(data.get("created_at", 0.0)),
        )

@dataclass
class Job:
    job_id: str
    user_id: int
    chat_id: int
    source_type: str = "upload"         # "upload" | "link"
    source_path: str | None = None
    source_url: str | None = None
    source_media_info: MediaInfo | None = None
    status: JobState = JobState.AWAITING_SOURCE
    stage: str = "init"
    current_revision_id: int = 1
    feature: str = JobFeature.VIDEO_VOICEOVER.value  # "video_voiceover" | "talking_photo"
    mode: str = "free_narration"        # "free_narration" | "source_timed"
    dubbing_revision_id: int | None = None
    duration_policy: str = "extend"
    error_message: str | None = None
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "user_id": self.user_id,
            "chat_id": self.chat_id,
            "source_type": self.source_type,
            "source_path": self.source_path,
            "source_url": self.source_url,
            "source_media_info": self.source_media_info.to_dict() if self.source_media_info else None,
            "status": self.status.value if isinstance(self.status, JobState) else str(self.status),
            "stage": self.stage,
            "current_revision_id": self.current_revision_id,
            "feature": self.feature,
            "mode": self.mode,
            "dubbing_revision_id": self.dubbing_revision_id,
            "duration_policy": self.duration_policy,
            "error_message": self.error_message,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Job":
        status_val = data.get("status", JobState.AWAITING_SOURCE.value)
        try:
            status_enum = JobState(status_val)
        except ValueError:
            status_enum = JobState.FAILED

        media_info_raw = data.get("source_media_info")
        if isinstance(media_info_raw, str):
            try:
                media_info_dict = json.loads(media_info_raw)
            except Exception:
                media_info_dict = None
        else:
            media_info_dict = media_info_raw

        return cls(
            job_id=str(data["job_id"]),
            user_id=int(data["user_id"]),
            chat_id=int(data["chat_id"]),
            source_type=str(data.get("source_type", "upload")),
            source_path=data.get("source_path"),
            source_url=data.get("source_url"),
            source_media_info=MediaInfo.from_dict(media_info_dict),
            status=status_enum,
            stage=str(data.get("stage", "init")),
            current_revision_id=int(data.get("current_revision_id", 1)),
            feature=str(data.get("feature", JobFeature.VIDEO_VOICEOVER.value)),
            mode=str(data.get("mode", "free_narration")),
            dubbing_revision_id=int(data["dubbing_revision_id"]) if data.get("dubbing_revision_id") is not None else None,
            duration_policy=str(data.get("duration_policy", "extend")),
            error_message=data.get("error_message"),
            created_at=float(data.get("created_at", 0.0)),
            updated_at=float(data.get("updated_at", 0.0)),
        )
