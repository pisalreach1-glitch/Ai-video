"""Tests for Talking Photo media validation, audio normalization, and long duration support."""
import pytest
from pathlib import Path
from PIL import Image
from app.config import config
from app.jobs.processes import run_process
from app.features.talking_photo.media import (
    validate_portrait_image,
    normalize_voice_recording,
    measure_audio_duration,
)

@pytest.fixture
def sample_image(tmp_path):
    img_path = tmp_path / "portrait.png"
    img = Image.new("RGB", (256, 256), color=(100, 150, 200))
    img.save(img_path)
    return img_path

@pytest.mark.asyncio
async def test_validate_portrait_image(sample_image, tmp_path):
    # Valid image
    is_valid, err, w, h = await validate_portrait_image(sample_image)
    assert is_valid is True
    assert err == ""
    assert w == 256
    assert h == 256

    # Image too small (<128)
    small_path = tmp_path / "small.png"
    img_small = Image.new("RGB", (64, 64), color=(50, 50, 50))
    img_small.save(small_path)
    is_valid_s, err_s, _, _ = await validate_portrait_image(small_path)
    assert is_valid_s is False
    assert "តូចពេក" in err_s

    # Corrupt image
    corrupt_path = tmp_path / "corrupt.png"
    corrupt_path.write_bytes(b"not an image file content")
    is_valid_c, err_c, _, _ = await validate_portrait_image(corrupt_path)
    assert is_valid_c is False

@pytest.mark.asyncio
async def test_audio_normalization_and_duration_measurement(tmp_path):
    # Generate 2-second sine wave audio
    raw_audio = tmp_path / "input_voice.ogg"
    cmd = [
        config.ffmpeg_path,
        "-y",
        "-f", "lavfi",
        "-i", "sine=frequency=440:duration=2.0",
        "-c:a", "libopus",
        str(raw_audio),
    ]
    await run_process(cmd, timeout=30.0)
    assert raw_audio.exists()

    master_wav = tmp_path / "master_audio.wav"
    inference_wav = tmp_path / "inference.wav"

    dur = await normalize_voice_recording(
        source_voice_path=raw_audio,
        master_audio_wav=master_wav,
        inference_wav=inference_wav,
    )

    assert master_wav.exists()
    assert inference_wav.exists()
    assert abs(dur - 2.0) < 0.2

@pytest.mark.asyncio
async def test_long_audio_duration_support_120s(tmp_path):
    """Verify that complete 120-second speech audio is normalized and measured without truncation."""
    raw_audio = tmp_path / "long_voice.ogg"
    cmd = [
        config.ffmpeg_path,
        "-y",
        "-f", "lavfi",
        "-i", "sine=frequency=300:duration=120.0",
        "-c:a", "libopus",
        str(raw_audio),
    ]
    await run_process(cmd, timeout=60.0)
    assert raw_audio.exists()

    master_wav = tmp_path / "long_master.wav"
    inference_wav = tmp_path / "long_inference.wav"

    dur = await normalize_voice_recording(
        source_voice_path=raw_audio,
        master_audio_wav=master_wav,
        inference_wav=inference_wav,
    )

    # Master audio must span >= 120.0s
    assert dur >= 119.8
