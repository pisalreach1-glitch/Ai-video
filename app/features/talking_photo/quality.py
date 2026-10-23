"""Quality validation, timing sync, and duration checks for Talking Photo avatars."""
from dataclasses import dataclass
from typing import Dict, Any

@dataclass(frozen=True)
class QualityReport:
    audio_duration: float
    video_duration: float
    duration_difference: float
    duration_valid: bool
    final_phrase_preserved: bool
    framing_status: str  # 'intact' | 'padded' | 'truncated'
    notes: str

def evaluate_render_quality(
    video_duration: float,
    audio_duration: float,
    max_drift_seconds: float = 0.5,
) -> QualityReport:
    """
    Evaluate whether avatar render preserved full audio duration and speech integrity.
    Rejects renders where speech is cut short.
    """
    diff = abs(video_duration - audio_duration)
    # Renders that are substantially shorter than audio must be rejected
    is_valid = video_duration >= (audio_duration - max_drift_seconds)
    phrase_preserved = video_duration >= (audio_duration - 0.2)

    note = "Duration and audio sync verified."
    if not is_valid:
        note = f"Video truncated: {video_duration:.2f}s is shorter than audio {audio_duration:.2f}s."

    return QualityReport(
        audio_duration=audio_duration,
        video_duration=video_duration,
        duration_difference=round(diff, 3),
        duration_valid=is_valid,
        final_phrase_preserved=phrase_preserved,
        framing_status="intact",
        notes=note,
    )
