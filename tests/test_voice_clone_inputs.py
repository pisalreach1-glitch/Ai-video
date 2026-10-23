"""Unit tests for Voice Clone reference audio validation and normalization."""
import pytest
from pathlib import Path
from app.config import config
from app.jobs.processes import run_process
from app.features.voice_clone.validation import validate_reference_audio, normalize_reference_audio

@pytest.mark.asyncio
async def test_validate_and_normalize_valid_reference(tmp_path):
    raw_audio = tmp_path / "sample_voice.ogg"
    # Generate 5.0 second test tone
    cmd = [
        config.ffmpeg_path,
        "-y",
        "-f", "lavfi",
        "-i", "sine=frequency=440:duration=5.0",
        "-c:a", "libopus",
        str(raw_audio),
    ]
    await run_process(cmd, timeout=30.0)

    dur, sr, ch = await validate_reference_audio(raw_audio, min_duration=3.0, max_duration=120.0)
    assert 4.8 <= dur <= 5.2
    assert sr > 0
    assert ch >= 1

    norm_dest = tmp_path / "normalized_ref.wav"
    norm_path, sha256 = await normalize_reference_audio(raw_audio, norm_dest, target_sr=24000)
    assert norm_path.exists()
    assert len(sha256) == 64

@pytest.mark.asyncio
async def test_validate_rejects_too_short_audio(tmp_path):
    raw_audio = tmp_path / "short_voice.ogg"
    cmd = [
        config.ffmpeg_path,
        "-y",
        "-f", "lavfi",
        "-i", "sine=frequency=440:duration=1.5",
        "-c:a", "libopus",
        str(raw_audio),
    ]
    await run_process(cmd, timeout=30.0)

    with pytest.raises(ValueError, match="ខ្លីពេក"):
        await validate_reference_audio(raw_audio, min_duration=3.0, max_duration=120.0)

@pytest.mark.asyncio
async def test_validate_rejects_missing_or_empty_audio(tmp_path):
    missing_path = tmp_path / "non_existent.wav"
    with pytest.raises(ValueError, match="ទទេ ឬមិនត្រឹមត្រូវ"):
        await validate_reference_audio(missing_path)

    empty_path = tmp_path / "empty.wav"
    empty_path.write_bytes(b"")
    with pytest.raises(ValueError, match="ទទេ ឬមិនត្រឹមត្រូវ"):
        await validate_reference_audio(empty_path)
