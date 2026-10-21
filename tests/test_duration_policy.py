"""Test duration policies (trim, extend final frame, loop)."""
import pytest
from app.domain.models import VoiceSettings, MediaInfo
from app.services.media import build_video_filter, probe_media
from app.services.render import render_video

def test_video_filter_longer_source():
    """When video is longer than audio, it is simply trimmed to audio duration."""
    info = MediaInfo(width=1080, height=1920, duration=10.0, has_audio=True)
    settings = VoiceSettings(duration_policy="extend")
    v_filter, _, _ = build_video_filter(info, settings, target_duration=5.0)

    assert "trim=duration=5.0" in v_filter
    assert "tpad" not in v_filter
    assert "loop" not in v_filter

def test_video_filter_shorter_source_extend():
    """When video is shorter than audio, extend policy adds tpad."""
    info = MediaInfo(width=1080, height=1920, duration=2.0, has_audio=True)
    settings = VoiceSettings(duration_policy="extend")
    v_filter, _, _ = build_video_filter(info, settings, target_duration=4.5)

    assert "tpad=stop_mode=clone" in v_filter
    assert "trim=duration=4.5" in v_filter

def test_video_filter_shorter_source_loop():
    """When video is shorter than audio, loop policy adds loop filter."""
    info = MediaInfo(width=1080, height=1920, duration=2.0, has_audio=True)
    settings = VoiceSettings(duration_policy="loop")
    v_filter, _, _ = build_video_filter(info, settings, target_duration=5.0)

    assert "loop=loop=-1" in v_filter
    assert "trim=duration=5.0" in v_filter

@pytest.mark.asyncio
async def test_short_video_extend_render(session_media_dir, tmp_path):
    """Real render test: 2.0s source video extended to match 3.0s narration."""
    src = session_media_dir["video_with_audio"]
    audio = session_media_dir["audio_sample"] # 3.0s
    out = tmp_path / "extended.mp4"

    settings = VoiceSettings(duration_policy="extend")
    await render_video(
        source_path=src,
        voice_audio_path=audio,
        output_path=out,
        settings=settings,
        target_duration=3.0,
    )

    info = probe_media(out)
    assert abs(info.duration - 3.0) < 0.2
    assert info.has_audio
