"""Test audio mixing, ducking, and source without audio handling."""
import pytest
from app.domain.models import VoiceSettings
from app.services.render import build_audio_filter, render_video
from app.services.media import probe_media

def test_build_audio_filter_modes():
    """Verify audio filter commands for mute vs low_mix."""
    # Mute mode: AI narration only
    f_mute, m_mute = build_audio_filter(source_has_audio=True, source_audio_mode="mute", target_duration=5.0)
    assert "[1:a]volume=1.0" in f_mute
    assert "amix" not in f_mute
    assert m_mute == ["[aout]"]

    # Low mix mode with audio
    f_mix, m_mix = build_audio_filter(source_has_audio=True, source_audio_mode="low_mix", target_duration=5.0)
    assert "[0:a]volume=0.15" in f_mix
    assert "amix=inputs=2" in f_mix
    assert m_mix == ["[aout]"]

    # Low mix mode WITHOUT source audio (falls back gracefully to AI voice)
    f_no_aud, _ = build_audio_filter(source_has_audio=False, source_audio_mode="low_mix", target_duration=5.0)
    assert "[1:a]volume=1.0" in f_no_aud
    assert "amix" not in f_no_aud

@pytest.mark.asyncio
async def test_render_with_low_mix(session_media_dir, tmp_path):
    """Verify rendering with source audio low-mix succeeds and yields audio."""
    src = session_media_dir["video_with_audio"]
    audio = session_media_dir["audio_sample"]
    out = tmp_path / "low_mix.mp4"

    settings = VoiceSettings(source_audio_mode="low_mix")
    await render_video(
        source_path=src,
        voice_audio_path=audio,
        output_path=out,
        settings=settings,
        target_duration=2.0,
    )

    info = probe_media(out)
    assert info.has_audio
    assert info.duration > 0.0

@pytest.mark.asyncio
async def test_render_source_without_audio_handles_gracefully(session_media_dir, tmp_path):
    """Verify source video without audio handles low_mix gracefully without failing."""
    src = session_media_dir["video_no_audio"]
    audio = session_media_dir["audio_sample"]
    out = tmp_path / "no_audio_mix.mp4"

    settings = VoiceSettings(source_audio_mode="low_mix")
    await render_video(
        source_path=src,
        voice_audio_path=audio,
        output_path=out,
        settings=settings,
        target_duration=2.0,
    )

    info = probe_media(out)
    assert info.has_audio
    assert abs(info.duration - 2.0) < 0.2
