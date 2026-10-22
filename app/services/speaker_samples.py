"""Utilities for selecting representative source-video preview windows for speakers and segments."""
from __future__ import annotations

from app.domain.speakers import SpeakerTurn


def review_window(
    start_ms: int,
    end_ms: int,
    source_duration_ms: int,
    context_ms: int = 750,
) -> tuple[int, int]:
    """
    Expands a speech segment with contextual padding around it while respecting
    source video duration boundaries [0, source_duration_ms].
    """
    if not (0 <= start_ms < end_ms <= source_duration_ms):
        raise ValueError("invalid_source_window")
    if context_ms < 0:
        raise ValueError("negative_context")
    return (
        max(0, start_ms - context_ms),
        min(source_duration_ms, end_ms + context_ms),
    )


def select_speaker_sample_window(
    speaker_id: str,
    turns: list[SpeakerTurn],
    source_duration_ms: int,
    context_ms: int = 750,
) -> tuple[int, int]:
    """
    Selects a representative turn for the speaker, preferring clear turns with duration
    between 3 and 10 seconds, and applies review_window padding.
    """
    spk_turns = [t for t in turns if t.speaker_id == speaker_id]
    if not spk_turns:
        raise ValueError(f"No turns found for speaker {speaker_id}")

    # Score turns: prefer durations around 4000-8000 ms
    best_turn = spk_turns[0]
    best_score = float("-inf")
    for t in spk_turns:
        dur = t.duration_ms
        # Ideal duration ~5000ms
        score = -abs(dur - 5000)
        if score > best_score:
            best_score = score
            best_turn = t

    return review_window(
        start_ms=best_turn.start_ms,
        end_ms=best_turn.end_ms,
        source_duration_ms=source_duration_ms,
        context_ms=context_ms,
    )


def format_ms_to_timecode(ms: int) -> str:
    """Format milliseconds into MM:SS string."""
    seconds = max(0, ms // 1000)
    mins = seconds // 60
    secs = seconds % 60
    return f"{mins:02d}:{secs:02d}"


def format_window_label(start_ms: int, end_ms: int) -> str:
    """Format interval into MM:SS–MM:SS."""
    return f"{format_ms_to_timecode(start_ms)}–{format_ms_to_timecode(end_ms)}"
