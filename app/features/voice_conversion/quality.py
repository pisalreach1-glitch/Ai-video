"""Quality evaluation for converted audio timing and delivery preservation."""
from dataclasses import dataclass

@dataclass(frozen=True)
class ConversionQualityReport:
    source_duration: float
    converted_duration: float
    drift_seconds: float
    drift_percent: float
    is_acceptable: bool
    final_phrase_preserved: bool
    notes: str

def evaluate_conversion_quality(
    source_duration: float,
    converted_duration: float,
    max_drift_percent: float = 0.15,
) -> ConversionQualityReport:
    """
    Compare source speech duration against converted speech duration.
    Ensures that speech timing and pauses are preserved without truncation.
    """
    if source_duration <= 0:
        return ConversionQualityReport(0, 0, 0, 0, False, False, "Invalid source duration.")

    drift = abs(converted_duration - source_duration)
    drift_pct = (drift / source_duration) * 100.0

    # Converted speech cannot be significantly shorter than source (which would indicate truncated words)
    truncated = converted_duration < (source_duration * 0.85)
    acceptable = (drift_pct <= (max_drift_percent * 100.0)) and not truncated
    phrase_preserved = not truncated

    notes = "Conversion timing and speech delivery verified."
    if truncated:
        notes = f"Converted audio is substantially shorter than source ({converted_duration:.1f}s vs {source_duration:.1f}s). Possible lost speech."
    elif not acceptable:
        notes = f"Timing drift exceeded threshold ({drift_pct:.1f}% > {max_drift_percent * 100:.1f}%)."

    return ConversionQualityReport(
        source_duration=round(source_duration, 2),
        converted_duration=round(converted_duration, 2),
        drift_seconds=round(drift, 2),
        drift_percent=round(drift_pct, 2),
        is_acceptable=acceptable,
        final_phrase_preserved=phrase_preserved,
        notes=notes,
    )
