"""Tests for timeline subtitle cue transformation and formatting."""
import pytest
from pathlib import Path
from app.domain.dubbing import DubbingPlan, Placement, DubClip, SourceSegment, TranslatedSegment
from app.services.subtitles import build_timeline_subtitles, parse_srt_events

def test_subtitle_cues_transformed_with_tempo_and_offsets(tmp_path):
    """Requirement 9: Fitted TTS subtitle cues use transformed times and stay inside source slots."""
    # Placement at 4000ms. Local TTS cue at 0.0s - 1.0s. Tempo factor 1.10.
    # Expected timeline cue: 4.0s + 0.0/1.10 = 4.0s. End: 4.0s + 1.0/1.10 = 4.909s.
    placement = Placement(
        segment_id="s001",
        timeline_start_ms=4000,
        slot_end_ms=6000,
        speech_end_ms=5000,
        start_sample=4000 * 48,
        sample_count=1000 * 48,
    )
    clip = DubClip(
        segment_id="s001",
        tts_cache_key="k1",
        raw_audio_path="test.wav",
        raw_duration_ms=1100,
        fitted_duration_ms=1000,
        tempo_factor=1.10,
        tts_events=[
            {"start": 0.0, "end": 1.0, "text": "ជំរាបសួរ"},
        ],
        status="ready",
    )
    plan = DubbingPlan(
        source_duration_ms=10000,
        segments=[SourceSegment(segment_id="s001", start_ms=4000, end_ms=6000, source_text="Hello")],
        clips=[clip],
        placements=[placement],
    )

    out_srt = tmp_path / "timed.srt"
    out_ass = tmp_path / "timed.ass"
    events = build_timeline_subtitles(plan, out_srt, out_ass)

    assert len(events) == 1
    assert events[0]["start"] == 4.0
    assert events[0]["end"] == pytest.approx(4.909, abs=0.01)
    assert events[0]["text"] == "ជំរាបសួរ"

    # Check generated SRT file
    parsed = parse_srt_events(out_srt)
    assert len(parsed) == 1
    assert parsed[0]["start"] == 4.0
    assert parsed[0]["end"] == pytest.approx(4.909, abs=0.01)
    assert "ជំរាបសួរ" in parsed[0]["text"]

    # Check ASS file contains Style and Dialogue
    ass_content = out_ass.read_text(encoding="utf-8")
    assert "[Script Info]" in ass_content
    assert "[V4+ Styles]" in ass_content
    assert "Dialogue:" in ass_content
    assert "ជំរាបសួរ" in ass_content
