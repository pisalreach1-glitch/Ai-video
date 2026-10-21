"""Tests for duration fitting, tempo limits, and overlong clip handling."""
import wave
import pytest
from pathlib import Path
from app.domain.dubbing import SourceSegment, DubClip
from app.services.audio_fit import fit_clip, measure_wav_duration_ms

def create_synthetic_wav(path: Path, duration_ms: int, sample_rate: int = 48000) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = int(round((duration_ms / 1000.0) * sample_rate))
    # 16-bit stereo PCM
    data = b"\x00\x00\x00\x00" * frames
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(data)
    return path

@pytest.mark.asyncio
async def test_mild_overlong_clip_fits_with_allowed_tempo(tmp_path):
    """Requirement 3: A 2160ms clip in a 2000ms slot fits with an allowed mild tempo change (1.08 <= 1.15)."""
    wav_path = create_synthetic_wav(tmp_path / "raw_2160.wav", duration_ms=2160)
    measured = measure_wav_duration_ms(wav_path)
    assert measured == 2160

    source_seg = SourceSegment(segment_id="s001", start_ms=0, end_ms=2000, source_text="Test utterance")
    clip = DubClip(
        segment_id="s001",
        tts_cache_key="test",
        raw_audio_path=str(wav_path),
        raw_duration_ms=2160,
    )

    fitted = await fit_clip(clip, source_seg, max_tempo=1.15)
    assert fitted.status == "ready"
    assert fitted.tempo_factor == pytest.approx(1.08, abs=0.02)
    assert fitted.fitted_duration_ms <= 2010

@pytest.mark.asyncio
async def test_excessive_overlong_clip_becomes_too_long_never_truncated(tmp_path):
    """Requirement 4: A 3200ms clip in a 2000ms slot becomes too_long / needs_review; never truncate it."""
    wav_path = create_synthetic_wav(tmp_path / "raw_3200.wav", duration_ms=3200)
    source_seg = SourceSegment(segment_id="s002", start_ms=0, end_ms=2000, source_text="Long utterance")
    clip = DubClip(
        segment_id="s002",
        tts_cache_key="test2",
        raw_audio_path=str(wav_path),
        raw_duration_ms=3200,
    )

    fitted = await fit_clip(clip, source_seg, max_tempo=1.15)
    assert fitted.status == "too_long"
    # Full audio is preserved without truncation
    assert fitted.raw_duration_ms == 3200
    assert fitted.fitted_duration_ms == 3200

@pytest.mark.asyncio
async def test_shorter_clip_leaves_trailing_silence_natural_speed(tmp_path):
    """Requirement 5: A shorter clip (e.g. 1200ms in 2000ms slot) leaves trailing silence rather than slowing speech."""
    wav_path = create_synthetic_wav(tmp_path / "raw_1200.wav", duration_ms=1200)
    source_seg = SourceSegment(segment_id="s003", start_ms=1000, end_ms=3000, source_text="Short utterance")
    clip = DubClip(
        segment_id="s003",
        tts_cache_key="test3",
        raw_audio_path=str(wav_path),
        raw_duration_ms=1200,
    )

    fitted = await fit_clip(clip, source_seg, max_tempo=1.15)
    assert fitted.status == "ready"
    assert fitted.tempo_factor == 1.0 # Kept natural speed
    assert fitted.fitted_duration_ms == 1200
