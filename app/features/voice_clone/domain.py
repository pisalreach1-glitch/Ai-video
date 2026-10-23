"""Domain models and interfaces for Voice Cloning feature."""
import json
import hashlib
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable, Protocol, Any

@dataclass(frozen=True)
class CloneCapabilities:
    backend_id: str
    model_version: str
    languages: tuple[str, ...]
    reference_min_seconds: float
    reference_max_seconds: float
    max_text_units_per_chunk: int
    text_unit_kind: str  # 'characters' | 'tokens'
    supports_khmer: bool = False

@dataclass(frozen=True)
class CloneRequest:
    artifact_id: str
    owner_user_id: int
    reference_wav: Path
    reference_sha256: str
    text: str
    language: str
    output_dir: Path
    model_version: str
    settings_digest: str
    reference_text: str = ""

@dataclass(frozen=True)
class CloneOutput:
    artifact_id: str
    wav_path: Path
    manifest_path: Path
    duration_seconds: float
    sha256: str

# Project contract alias per Section 4
AudioArtifact = CloneOutput

class VoiceCloneBackend(Protocol):
    async def capabilities(self) -> CloneCapabilities:
        ...

    async def synthesize(
        self,
        request: CloneRequest,
        *,
        cancel_check: Callable[[], bool],
        on_pid: Callable[[int], None],
    ) -> CloneOutput:
        ...

@dataclass
class VoiceReference:
    reference_id: str
    owner_user_id: int
    job_id: str
    version: int = 1
    wav_path: str = ""
    sha256: str = ""
    duration_seconds: float = 0.0
    sample_rate: int = 24000
    channels: int = 1
    reference_text: str = ""
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VoiceReference":
        return cls(
            reference_id=str(data["reference_id"]),
            owner_user_id=int(data["owner_user_id"]),
            job_id=str(data["job_id"]),
            version=int(data.get("version", 1)),
            wav_path=str(data.get("wav_path", "")),
            sha256=str(data.get("sha256", "")),
            duration_seconds=float(data.get("duration_seconds", 0.0)),
            sample_rate=int(data.get("sample_rate", 24000)),
            channels=int(data.get("channels", 1)),
            reference_text=str(data.get("reference_text", "")),
            created_at=float(data.get("created_at", 0.0)),
        )

@dataclass
class VoiceCloneArtifact:
    artifact_id: str
    job_id: str
    owner_user_id: int
    reference_id: str
    reference_sha256: str
    text: str
    text_sha256: str
    language: str = "km"
    backend_id: str = "local"
    model_version: str = "1.0"
    settings_json: str = "{}"
    request_digest: str = ""
    state: str = "pending"  # 'pending' | 'ready' | 'failed' | 'cancelled'
    wav_path: str | None = None
    wav_sha256: str | None = None
    duration_seconds: float = 0.0
    manifest_path: str | None = None
    error_code: str | None = None
    reference_text: str = ""
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VoiceCloneArtifact":
        return cls(
            artifact_id=str(data["artifact_id"]),
            job_id=str(data["job_id"]),
            owner_user_id=int(data["owner_user_id"]),
            reference_id=str(data["reference_id"]),
            reference_sha256=str(data.get("reference_sha256", "")),
            text=str(data["text"]),
            text_sha256=str(data.get("text_sha256", "")),
            language=str(data.get("language", "km")),
            backend_id=str(data.get("backend_id", "local")),
            model_version=str(data.get("model_version", "1.0")),
            settings_json=str(data.get("settings_json", "{}")),
            request_digest=str(data.get("request_digest", "")),
            state=str(data.get("state", "pending")),
            wav_path=data.get("wav_path"),
            wav_sha256=data.get("wav_sha256"),
            duration_seconds=float(data.get("duration_seconds", 0.0)),
            manifest_path=data.get("manifest_path"),
            error_code=data.get("error_code"),
            reference_text=str(data.get("reference_text", "")),
            created_at=float(data.get("created_at", 0.0)),
        )

@dataclass
class AudioApproval:
    approval_id: str
    job_id: str
    artifact_id: str
    request_digest: str
    wav_sha256: str
    owner_user_id: int
    approved_at: float = 0.0
    invalidated_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AudioApproval":
        return cls(
            approval_id=str(data["approval_id"]),
            job_id=str(data["job_id"]),
            artifact_id=str(data["artifact_id"]),
            request_digest=str(data["request_digest"]),
            wav_sha256=str(data["wav_sha256"]),
            owner_user_id=int(data["owner_user_id"]),
            approved_at=float(data.get("approved_at", 0.0)),
            invalidated_at=data.get("invalidated_at"),
        )
