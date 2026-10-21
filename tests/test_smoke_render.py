"""Smoke test: end-to-end rendering on synthetic media with subtitle burning."""
import pytest
from app.domain.models import VoiceSettings
from app.services.render import render_video, validate_final_mp4
from app.services.subtitles import generate_ass
from app.services.media import probe_media

@pytest.mark.asyncio
async def test_smoke_render_full_pipeline(session_media_dir, tmp_path):
    """
    Smoke test:
    1. Generates ASS subtitle file with Khmer text.
    2. Renders video with subtitles burned, audio mixed, and framing applied.
    3. Validates output MP4: decodable, H.264/AAC, yuv420p, correct duration.
    """
    src = session_media_dir["video_with_audio"]
    audio = session_media_dir["audio_sample"]
    ass_path = tmp_path / "smoke.ass"
    out_mp4 = tmp_path / "smoke_final.mp4"

    events = [
        {"start": 0.2, "end": 1.2, "text": "តេស្តផ្សែង (Smoke Test)"},
        {"start": 1.5, "end": 2.5, "text": "អក្សរខ្មែររត់បានជោគជ័យ"},
    ]
    generate_ass(
        events=events,
        output_path=ass_path,
        font_name="Khmer OS Battambang",
        color="yellow",
        position="bottom",
        res_x=1080,
        res_y=1920,
    )

    settings = VoiceSettings(
        subtitles_enabled=True,
        subtitle_color="yellow",
        subtitle_position="bottom",
        source_audio_mode="mute",
        aspect_ratio="9:16",
        framing_mode="fit",
        duration_policy="extend",
    )

    await render_video(
        source_path=src,
        voice_audio_path=audio,
        output_path=out_mp4,
        settings=settings,
        target_duration=2.5,
        subtitles_ass_path=ass_path,
    )

    assert out_mp4.exists()
    assert out_mp4.stat().st_size > 0

    info = validate_final_mp4(out_mp4, expected_duration=2.5)
    assert info.width == 1080
    assert info.height == 1920
    assert info.has_audio
    assert abs(info.duration - 2.5) < 0.2
