"""Long render assembly and master audio muxing for Talking Photo."""
import logging
from pathlib import Path
from typing import Callable
from app.config import config
from app.jobs.processes import run_process
from app.features.talking_photo.media import measure_audio_duration

logger = logging.getLogger(__name__)

async def mux_master_audio(
    video_track: Path,
    master_audio: Path,
    output_mp4: Path,
    on_pid: Callable[[int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    preview_limit: float | None = None,
) -> Path:
    """
    Mux the animated video track with the complete original master speech audio.
    Ensures that the final phrase of >= 120s speech is never truncated.
    Produces standard H.264 / AAC, yuv420p, faststart MP4.
    """
    output_mp4.parent.mkdir(parents=True, exist_ok=True)
    audio_dur = await measure_audio_duration(master_audio)

    # Base cmd
    cmd = [
        config.ffmpeg_path,
        "-y",
        "-i", str(video_track),
        "-i", str(master_audio),
    ]

    if preview_limit and preview_limit > 0:
        target_dur = min(audio_dur, preview_limit)
        cmd.extend(["-t", f"{target_dur:.3f}"])
    else:
        # Full render: ensure coverage reaches full audio duration
        cmd.extend(["-t", f"{audio_dur:.3f}"])

    cmd.extend([
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "fast",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        str(output_mp4),
    ])

    res = await run_process(cmd, timeout=300.0, on_pid=on_pid, cancel_check=cancel_check)
    if cancel_check and cancel_check():
        raise RuntimeError("Muxing cancelled.")

    if res.returncode != 0 or not output_mp4.exists():
        raise RuntimeError(f"Failed to mux master audio with video: {res.stderr[:200]}")

    return output_mp4
