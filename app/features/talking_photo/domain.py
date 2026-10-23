"""Domain models for Talking Photo feature."""
import json
import hashlib
from dataclasses import dataclass, field, asdict
from typing import Any

@dataclass
class TalkingPhotoSettings:
    face_size: int = 256            # 256 | 512
    batch_size: int = 1             # default 1 for memory bounded execution on RTX 3060
    still_mode: bool = False        # if True, keeps head motion subtle
    expression_scale: float = 1.0   # 1.0 = normal expression
    pose_style: int = 0             # 0 = default natural pose

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "TalkingPhotoSettings":
        if not data:
            return cls()
        return cls(
            face_size=int(data.get("face_size", 256)),
            batch_size=int(data.get("batch_size", 1)),
            still_mode=bool(data.get("still_mode", False)),
            expression_scale=float(data.get("expression_scale", 1.0)),
            pose_style=int(data.get("pose_style", 0)),
        )

@dataclass
class TalkingPhotoRevision:
    job_id: str
    revision_id: int
    input_version: int = 1
    image_path: str = ""
    original_voice_path: str = ""
    inference_wav_path: str | None = None
    master_audio_path: str | None = None
    settings: TalkingPhotoSettings = field(default_factory=TalkingPhotoSettings)
    manifest_path: str | None = None
    preview_path: str | None = None
    approved_preview_id: str | None = None
    final_path: str | None = None
    input_digest: str = ""
    engine_version: str = "sadtalker-1.0"
    audio_source: str = "recorded_voice"  # 'recorded_voice' | 'cloned_voice'
    approved_audio_artifact_id: str | None = None
    audio_approval_id: str | None = None
    image_sha256: str = ""
    settings_digest: str = ""
    video_snapshot_digest: str = ""
    avatar_backend: str = "sadtalker"
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "revision_id": self.revision_id,
            "input_version": self.input_version,
            "image_path": self.image_path,
            "original_voice_path": self.original_voice_path,
            "inference_wav_path": self.inference_wav_path,
            "master_audio_path": self.master_audio_path,
            "settings": self.settings.to_dict(),
            "manifest_path": self.manifest_path,
            "preview_path": self.preview_path,
            "approved_preview_id": self.approved_preview_id,
            "final_path": self.final_path,
            "input_digest": self.input_digest,
            "engine_version": self.engine_version,
            "audio_source": self.audio_source,
            "approved_audio_artifact_id": self.approved_audio_artifact_id,
            "audio_approval_id": self.audio_approval_id,
            "image_sha256": self.image_sha256,
            "settings_digest": self.settings_digest,
            "video_snapshot_digest": self.video_snapshot_digest,
            "avatar_backend": self.avatar_backend,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TalkingPhotoRevision":
        settings_raw = data.get("settings_json") or data.get("settings")
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
            job_id=str(data["job_id"]),
            revision_id=int(data["revision_id"]),
            input_version=int(data.get("input_version", 1)),
            image_path=str(data.get("image_path", "")),
            original_voice_path=str(data.get("original_voice_path", "")),
            inference_wav_path=data.get("inference_wav_path"),
            master_audio_path=data.get("master_audio_path"),
            settings=TalkingPhotoSettings.from_dict(settings_dict),
            manifest_path=data.get("manifest_path"),
            preview_path=data.get("preview_path"),
            approved_preview_id=data.get("approved_preview_id"),
            final_path=data.get("final_path"),
            input_digest=str(data.get("input_digest", "")),
            engine_version=str(data.get("engine_version", "sadtalker-1.0")),
            audio_source=str(data.get("audio_source", "recorded_voice")),
            approved_audio_artifact_id=data.get("approved_audio_artifact_id"),
            audio_approval_id=data.get("audio_approval_id"),
            image_sha256=str(data.get("image_sha256", "")),
            settings_digest=str(data.get("settings_digest", "")),
            video_snapshot_digest=str(data.get("video_snapshot_digest", "")),
            avatar_backend=str(data.get("avatar_backend", "sadtalker")),
            created_at=float(data.get("created_at", 0.0)),
        )

@dataclass(frozen=True)
class AvatarRequest:
    task_id: str
    snapshot_digest: str
    source_image: str
    approved_master_wav: str
    audio_sha256: str
    output_dir: str
    preview_seconds: float | None = None
    backend_id: str = "sadtalker"
    motion_prompt: str = ""

@dataclass(frozen=True)
class AvatarResult:
    video_path: str
    manifest_path: str
    duration_seconds: float
    backend_revision: str

@dataclass
class TalkingPhotoInputManifest:
    job_id: str
    input_version: int
    image_path: str
    image_width: int
    image_height: int
    voice_path: str
    voice_duration: float
    input_digest: str
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TalkingPhotoInputManifest":
        return cls(
            job_id=str(data["job_id"]),
            input_version=int(data.get("input_version", 1)),
            image_path=str(data.get("image_path", "")),
            image_width=int(data.get("image_width", 0)),
            image_height=int(data.get("image_height", 0)),
            voice_path=str(data.get("voice_path", "")),
            voice_duration=float(data.get("voice_duration", 0.0)),
            input_digest=str(data.get("input_digest", "")),
            created_at=float(data.get("created_at", 0.0)),
        )
