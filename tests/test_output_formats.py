"""Test output format aspect ratios (original, 9:16, 1:1) and framing modes (fit/fill)."""
import pytest
from app.domain.models import VoiceSettings
from app.services.render import render_video
from app.services.media import probe_media

@pytest.mark.asyncio
async def test_vertical_9_16_fit_pad(session_media_dir, tmp_path):
    """Verify conversion to 9:16 vertical video with fit padding."""
    src = session_media_dir["video_with_audio"] # 640x360 landscape
    audio = session_media_dir["audio_sample"]
    out = tmp_path / "vertical_fit.mp4"

    settings = VoiceSettings(aspect_ratio="9:16", framing_mode="fit")
    await render_video(
        source_path=src,
        voice_audio_path=audio,
        output_path=out,
        settings=settings,
        target_duration=1.5,
    )

    info = probe_media(out)
    assert info.width == 1080
    assert info.height == 1920
    assert info.aspect_ratio_str == "9:16"

@pytest.mark.asyncio
async def test_square_1_1_fill_crop(session_media_dir, tmp_path):
    """Verify conversion to 1:1 square video with fill cropping."""
    src = session_media_dir["video_with_audio"]
    audio = session_media_dir["audio_sample"]
    out = tmp_path / "square_crop.mp4"

    settings = VoiceSettings(aspect_ratio="1:1", framing_mode="fill")
    await render_video(
        source_path=src,
        voice_audio_path=audio,
        output_path=out,
        settings=settings,
        target_duration=1.5,
    )

    info = probe_media(out)
    assert info.width == 1080
    assert info.height == 1080
    assert info.aspect_ratio_str == "1:1"

@pytest.mark.asyncio
async def test_original_ratio_preserved(session_media_dir, tmp_path):
    """Verify original ratio maintains source dimensions."""
    src = session_media_dir["video_with_audio"] # 640x360
    audio = session_media_dir["audio_sample"]
    out = tmp_path / "original_ratio.mp4"

    settings = VoiceSettings(aspect_ratio="original")
    await render_video(
        source_path=src,
        voice_audio_path=audio,
        output_path=out,
        settings=settings,
        target_duration=1.5,
    )

    info = probe_media(out)
    assert info.width == 640
    assert info.height == 360
