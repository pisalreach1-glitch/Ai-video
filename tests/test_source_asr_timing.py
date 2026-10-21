"""Tests for Source ASR extraction, timestamp retention, and pause preservation."""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from app.services.source_asr import group_and_validate_segments, transcribe_source
from app.domain.dubbing import SourceSegment

def test_source_asr_silence_before_speech():
    """Requirement 1: Original speech starts after 2-second silence; segment starts at 2000ms."""
    raw = [
        {"start": 2.05, "end": 4.10, "text": "Hello world", "language": "en"},
    ]
    segments = group_and_validate_segments(raw, video_duration_ms=10000)
    assert len(segments) == 1
    assert segments[0].start_ms == 2050
    assert segments[0].end_ms == 4100
    assert segments[0].source_text == "Hello world"
    assert segments[0].duration_ms == 2050

def test_source_asr_preserves_gap_between_slots():
    """Requirement 2: Two source slots at 2-4s and 8-10s preserve the gap without sequential concatenation."""
    raw = [
        {"start": 2.0, "end": 4.0, "text": "First utterance", "language": "en"},
        {"start": 8.0, "end": 10.0, "text": "Second utterance", "language": "en"},
    ]
    segments = group_and_validate_segments(raw, video_duration_ms=12000)
    assert len(segments) == 2
    assert segments[0].start_ms == 2000
    assert segments[0].end_ms == 4000
    assert segments[1].start_ms == 8000
    assert segments[1].end_ms == 10000

    # 4-second gap between segments
    gap_ms = segments[1].start_ms - segments[0].end_ms
    assert gap_ms == 4000

def test_source_asr_silence_only_returns_empty_and_no_hallucination():
    """Requirement 18: Silence-only video returns empty list and does not fabricate speech."""
    raw = [] # No speech detected
    segments = group_and_validate_segments(raw, video_duration_ms=10000)
    assert segments == []

    # Whitespace only is also discarded
    raw_ws = [{"start": 1.0, "end": 3.0, "text": "   \n  "}]
    segments_ws = group_and_validate_segments(raw_ws, video_duration_ms=10000)
    assert segments_ws == []

def test_source_asr_timestamp_validation_and_bounds():
    """Negative times, inverted timestamps, or times exceeding video duration are sanitized."""
    raw = [
        {"start": -1.0, "end": 2.0, "text": "Negative start clamped", "language": "en"},
        {"start": 5.0, "end": 4.0, "text": "Inverted time discarded", "language": "en"},
        {"start": 9.0, "end": 15.0, "text": "Exceeds video length", "language": "en"},
    ]
    segments = group_and_validate_segments(raw, video_duration_ms=10000)
    assert len(segments) == 2
    # Clamped to 0
    assert segments[0].start_ms == 0
    assert segments[0].end_ms == 2000
    # Clamped to video duration 10000ms
    assert segments[1].start_ms == 9000
    assert segments[1].end_ms == 10000
