"""Tests for deterministic PCM timeline assembly and sync reporting."""
import wave
import pytest
from pathlib import Path
from app.domain.dubbing import DubbingPlan, SourceSegment, DubClip, TranslatedSegment
from app.services.timeline import assemble_timeline_pcm
from tests.test_dubbing_fit import create_synthetic_wav

def test_timeline_places_clips_at_source_times_with_silence_gaps(tmp_path):
    """Requirements 1 & 2: Placed at 2s and 8s, 4-second silence gap preserved."""
    clip1_wav = create_synthetic_wav(tmp_path / "clip1.wav", duration_ms=1500)
    clip2_wav = create_synthetic_wav(tmp_path / "clip2.wav", duration_ms=1800)

    s1 = SourceSegment(segment_id="s001", start_ms=2000, end_ms=4000, source_text="First")
    s2 = SourceSegment(segment_id="s002", start_ms=8000, end_ms=10000, source_text="Second")

    c1 = DubClip(
        segment_id="s001",
        tts_cache_key="k1",
        raw_audio_path=str(clip1_wav),
        fitted_audio_path=str(clip1_wav),
        raw_duration_ms=1500,
        fitted_duration_ms=1500,
        status="ready",
    )
    c2 = DubClip(
        segment_id="s002",
        tts_cache_key="k2",
        raw_audio_path=str(clip2_wav),
        fitted_audio_path=str(clip2_wav),
        raw_duration_ms=1800,
        fitted_duration_ms=1800,
        status="ready",
    )

    plan = DubbingPlan(
        source_duration_ms=12000,
        sample_rate=48000,
        segments=[s1, s2],
        clips=[c1, c2],
    )

    out_wav = tmp_path / "timeline.wav"
    placements, report = assemble_timeline_pcm(plan, out_wav)

    assert len(placements) == 2
    assert placements[0].timeline_start_ms == 2000
    assert placements[0].start_sample == 2000 * 48
    assert placements[0].speech_end_ms == 3500

    assert placements[1].timeline_start_ms == 8000
    assert placements[1].start_sample == 8000 * 48
    assert placements[1].speech_end_ms == 9800

    # Total timeline duration matches source video exactly
    with wave.open(str(out_wav), "rb") as wf:
        total_frames = wf.getnframes()
        rate = wf.getframerate()
        assert total_frames == int(round(12.0 * rate))

    # Verify report
    assert report["source_duration_ms"] == 12000
    assert report["validation_passed"] is True
    assert len(report["issues"]) == 0

def test_timeline_detects_collision(tmp_path):
    """Detects collision if a clip starts before preceding speech finishes."""
    clip1_wav = create_synthetic_wav(tmp_path / "c1.wav", duration_ms=4000)
    clip2_wav = create_synthetic_wav(tmp_path / "c2.wav", duration_ms=2000)

    # s1 runs 1000ms to 5000ms, s2 starts at 3000ms -> Collision!
    s1 = SourceSegment(segment_id="s001", start_ms=1000, end_ms=5000, source_text="First")
    s2 = SourceSegment(segment_id="s002", start_ms=3000, end_ms=6000, source_text="Second")

    c1 = DubClip(segment_id="s001", tts_cache_key="k1", raw_audio_path=str(clip1_wav), fitted_duration_ms=4000, status="ready")
    c2 = DubClip(segment_id="s002", tts_cache_key="k2", raw_audio_path=str(clip2_wav), fitted_duration_ms=2000, status="ready")

    plan = DubbingPlan(source_duration_ms=8000, sample_rate=48000, segments=[s1, s2], clips=[c1, c2])
    placements, report = assemble_timeline_pcm(plan, tmp_path / "collision.wav")

    assert report["validation_passed"] is False
    assert any(i["issue_type"] == "collision" for i in report["issues"])
