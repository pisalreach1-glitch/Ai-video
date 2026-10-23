"""Domain models and interfaces for Voice Conversion (Speech-to-Speech)."""
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable, Protocol, Any

@dataclass(frozen=True)
class ConversionRequest:
    artifact_id: str
    target_reference_wav: Path  # Timbre / speaker identity (target)
    full_source_wav: Path       # Content / words / delivery (source)
    output_dir: Path
    input_digest: str
    backend_revision: str
    preserve_source_delivery: bool = True

@dataclass(frozen=True)
class ConvertedAudio:
    artifact_id: str
    master_wav: Path
    sha256: str
    sample_rate: int
    sample_count: int
    duration_seconds: float
    manifest_path: Path

class VoiceConversionBackend(Protocol):
    async def convert(
        self,
        request: ConversionRequest,
        *,
        cancel_check: Callable[[], bool],
        on_pid: Callable[[int], None],
    ) -> ConvertedAudio:
        ...

@dataclass
class VoiceConversionRecord:
    conversion_id: str
    job_id: str
    owner_user_id: int
    target_reference_path: str
    target_reference_sha256: str
    target_reference_duration: float
    full_source_path: str
    full_source_sha256: str
    full_source_duration: float
    converted_wav_path: str | None = None
    converted_wav_sha256: str | None = None
    converted_duration: float = 0.0
    state: str = "pending"  # 'pending' | 'ready' | 'failed' | 'cancelled'
    backend_id: str = "seed_vc"
    request_digest: str = ""
    manifest_path: str | None = None
    error_code: str | None = None
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VoiceConversionRecord":
        return cls(
            conversion_id=str(data["conversion_id"]),
            job_id=str(data["job_id"]),
            owner_user_id=int(data["owner_user_id"]),
            target_reference_path=str(data["target_reference_path"]),
            target_reference_sha256=str(data["target_reference_sha256"]),
            target_reference_duration=float(data.get("target_reference_duration", 0.0)),
            full_source_path=str(data["full_source_path"]),
            full_source_sha256=str(data["full_source_sha256"]),
            full_source_duration=float(data.get("full_source_duration", 0.0)),
            converted_wav_path=data.get("converted_wav_path"),
            converted_wav_sha256=data.get("converted_wav_sha256"),
            converted_duration=float(data.get("converted_duration", 0.0)),
            state=str(data.get("state", "pending")),
            backend_id=str(data.get("backend_id", "seed_vc")),
            request_digest=str(data.get("request_digest", "")),
            manifest_path=data.get("manifest_path"),
            error_code=data.get("error_code"),
            created_at=float(data.get("created_at", 0.0)),
        )
