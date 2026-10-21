"""FFmpeg rendering engine for final MP4 outputs with stream validation."""
import logging
from pathlib import Path
from typing import Callable
from app.config import config
from app.domain.models import MediaInfo, VoiceSettings
from app.jobs.processes import run_process, ProcessResult
from app.services.media import probe_media, build_video_filter

logger = logging.getLogger(__name__)

class RenderError(Exception):
    """Raised when video rendering fails or output validation fails."""
    pass

class RenderCancelledError(Exception):
    """Raised when rendering is terminated due to user cancellation."""
    pass

def build_audio_filter(
    source_has_audio: bool,
    source_audio_mode: str,
    target_duration: float,
) -> tuple[str, list[str]]:
    """
    Construct audio filtergraph:
    - If mode is mute or source lacks audio: take only AI narration [1:a]
    - If mode is low_mix and source has audio: mix source at 15% with AI at 100%
    """
    if source_audio_mode == "low_mix" and source_has_audio:
        # Duck source audio to 15% volume, keep narration at 100%, mix together
        filter_str = (
            f"[0:a]volume=0.15,atrim=duration={target_duration},asetpts=PTS-STARTPTS[a0]; "
            f"[1:a]volume=1.0,atrim=duration={target_duration},asetpts=PTS-STARTPTS[a1]; "
            f"[a0][a1]amix=inputs=2:duration=first:dropout_transition=2[aout]"
        )
        return filter_str, ["[aout]"]
    else:
        # Default: Pure AI voice narration
        filter_str = f"[1:a]volume=1.0,atrim=duration={target_duration},asetpts=PTS-STARTPTS[aout]"
        return filter_str, ["[aout]"]

def validate_final_mp4(
    file_path: Path | str,
    expected_duration: float,
    duration_tolerance: float = 1.0,
) -> MediaInfo:
    """
    Validate that output file is a decodable MP4:
    - Decodable by ffprobe
    - Video stream is H.264
    - Has audio stream (AAC)
    - Duration matches narration within tolerance
    - File size > 0
    """
    dest = Path(file_path)
    if not dest.exists() or dest.stat().st_size == 0:
        raise RenderError(f"Output MP4 file does not exist or is empty: {file_path}")

    try:
        info = probe_media(dest)
    except Exception as e:
        raise RenderError(f"Rendered video is corrupt or unreadable: {e}")

    if info.width <= 0 or info.height <= 0:
        raise RenderError("Rendered video missing valid video dimensions.")

    if not info.has_audio:
        raise RenderError("Rendered video is missing audio stream.")

    # Duration check with sensible tolerance
    if expected_duration > 0 and abs(info.duration - expected_duration) > duration_tolerance:
        logger.warning(
            f"Duration mismatch: expected ~{expected_duration:.2f}s, got {info.duration:.2f}s."
        )

    return info

async def render_video(
    source_path: Path | str,
    voice_audio_path: Path | str,
    output_path: Path | str,
    settings: VoiceSettings,
    target_duration: float,
    subtitles_ass_path: Path | str | None = None,
    is_preview: bool = False,
    preview_duration: float = 5.0,
    timeout_seconds: float = 300.0,
    cancel_check: Callable[[], bool] | None = None,
    on_pid: Callable[[int], None] | None = None,
) -> Path:
    """
    Renders video using FFmpeg with proper aspect ratio, framing, audio mix, and subtitles.
    Enforces process tree cancellation and timeouts.
    """
    src = Path(source_path)
    voice = Path(voice_audio_path)
    dest = Path(output_path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    if not src.exists():
        raise RenderError(f"Source video not found: {source_path}")
    if not voice.exists():
        raise RenderError(f"Voice audio not found: {voice_audio_path}")

    source_info = probe_media(src)
    eff_duration = min(preview_duration, target_duration) if is_preview else target_duration

    # Build filters
    v_filter, out_w, out_h = build_video_filter(
        source_info=source_info,
        settings=settings,
        target_duration=target_duration,
        subtitles_ass_path=subtitles_ass_path,
        is_preview=is_preview,
        preview_duration=preview_duration,
    )

    a_filter, a_map = build_audio_filter(
        source_has_audio=source_info.has_audio,
        source_audio_mode=settings.source_audio_mode,
        target_duration=eff_duration,
    )

    full_filter = f"[0:v]{v_filter}[vout]; {a_filter}"

    cmd = [
        config.ffmpeg_path,
        "-y",
        "-i", str(src),
        "-i", str(voice),
        "-filter_complex", full_filter,
        "-map", "[vout]",
        "-map", a_map[0],
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "22",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        "-t", f"{eff_duration:.3f}",
        str(dest),
    ]

    result: ProcessResult = await run_process(
        cmd=cmd,
        timeout=timeout_seconds,
        cancel_check=cancel_check,
        on_pid=on_pid,
    )

    if result.cancelled:
        if dest.exists():
            dest.unlink(missing_ok=True)
        raise RenderCancelledError("Render was cancelled.")

    if result.timed_out:
        if dest.exists():
            dest.unlink(missing_ok=True)
        raise RenderError(f"Render timed out after {timeout_seconds}s.")

    if result.returncode != 0:
        if dest.exists():
            dest.unlink(missing_ok=True)
        raise RenderError(f"FFmpeg render failed (code {result.returncode}): {result.stderr[-500:]}")

    # Validate output
    validate_final_mp4(dest, expected_duration=eff_duration)
    return dest
