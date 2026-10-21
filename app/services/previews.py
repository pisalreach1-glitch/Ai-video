"""Video preview generator producing up to 5-second realistic previews."""
import logging
from pathlib import Path
from typing import Callable
from app.domain.models import VoiceSettings
from app.services.render import render_video

logger = logging.getLogger(__name__)

async def render_preview_video(
    source_path: Path | str,
    voice_audio_path: Path | str,
    output_preview_path: Path | str,
    settings: VoiceSettings,
    target_duration: float,
    subtitles_ass_path: Path | str | None = None,
    preview_duration: float = 5.0,
    timeout_seconds: float = 60.0,
    cancel_check: Callable[[], bool] | None = None,
    on_pid: Callable[[int], None] | None = None,
) -> Path:
    """
    Renders up to 5-second video preview matching the full video's
    voice, subtitles, framing, and audio mix.
    """
    return await render_video(
        source_path=source_path,
        voice_audio_path=voice_audio_path,
        output_path=output_preview_path,
        settings=settings,
        target_duration=target_duration,
        subtitles_ass_path=subtitles_ass_path,
        is_preview=True,
        preview_duration=preview_duration,
        timeout_seconds=timeout_seconds,
        cancel_check=cancel_check,
        on_pid=on_pid,
    )
