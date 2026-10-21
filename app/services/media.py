"""Media probing, aspect framing, duration policies, and audio mixing with FFmpeg."""
import json
import logging
import re
import subprocess
from pathlib import Path
from typing import Any
from app.config import config
from app.domain.models import MediaInfo, VoiceSettings

logger = logging.getLogger(__name__)

def probe_media(file_path: Path | str) -> MediaInfo:
    """Probe video/audio streams using ffprobe."""
    path = Path(file_path)
    if not path.exists() or path.stat().st_size == 0:
        raise ValueError(f"File does not exist or is empty: {file_path}")

    cmd = [
        config.ffprobe_path,
        "-v", "error",
        "-show_entries", "stream=width,height,codec_type,codec_name,r_frame_rate,duration",
        "-show_entries", "format=duration,size,format_name",
        "-of", "json",
        str(path),
    ]

    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {res.stderr}")

    try:
        data = json.loads(res.stdout)
    except Exception as e:
        raise RuntimeError(f"Could not parse ffprobe output: {e}")

    streams = data.get("streams", [])
    format_info = data.get("format", {})

    width = 0
    height = 0
    has_audio = False
    fps = 30.0

    for stream in streams:
        codec_type = stream.get("codec_type")
        if codec_type == "video" and width == 0:
            width = int(stream.get("width", 0))
            height = int(stream.get("height", 0))
            r_fps = stream.get("r_frame_rate", "30/1")
            try:
                num, den = r_fps.split("/")
                fps = float(num) / float(den) if float(den) > 0 else 30.0
            except Exception:
                fps = 30.0
        elif codec_type == "audio":
            has_audio = True

    duration = 0.0
    if "duration" in format_info:
        try:
            duration = float(format_info["duration"])
        except Exception:
            pass

    if duration <= 0.0:
        for s in streams:
            if "duration" in s:
                try:
                    duration = max(duration, float(s["duration"]))
                except Exception:
                    pass

    return MediaInfo(
        width=width,
        height=height,
        duration=duration,
        has_audio=has_audio,
        fps=fps,
        format_name=format_info.get("format_name", "mp4"),
        size_bytes=int(format_info.get("size", path.stat().st_size)),
    )

def probe_audio_duration(file_path: Path | str) -> float:
    """Probe duration of an audio file in seconds."""
    try:
        info = probe_media(file_path)
        return info.duration
    except Exception:
        return 0.0

def escape_ffmpeg_filter_path(path: Path | str) -> str:
    """Escape Windows file paths for FFmpeg filter arguments."""
    posix_path = Path(path).as_posix()
    # In ffmpeg filter syntax, colons and backslashes must be escaped
    return posix_path.replace(":", "\\:").replace("'", "\\'")

def build_video_filter(
    source_info: MediaInfo,
    settings: VoiceSettings,
    target_duration: float,
    subtitles_ass_path: Path | str | None = None,
    is_preview: bool = False,
    preview_duration: float = 5.0,
    mode: str = "free_narration",
) -> tuple[str, int, int]:
    """
    Construct FFmpeg video filtergraph covering:
    - Duration policy (trim, extend final frame, or loop)
    - Aspect ratio transformation (9:16, 1:1, or original)
    - Framing mode (fit padding or fill cropping)
    - Subtitle burning (libass)
    Returns: (filter_str, target_width, target_height)
    """
    filters: list[str] = []

    # 1. Determine target dimensions
    src_w = source_info.width if source_info.width > 0 else 1080
    src_h = source_info.height if source_info.height > 0 else 1920

    if settings.aspect_ratio == "9:16":
        out_w, out_h = 1080, 1920
    elif settings.aspect_ratio == "1:1":
        out_w, out_h = 1080, 1080
    else:
        # Original ratio: maintain original dimensions (ensuring even dimensions for H.264)
        out_w = src_w if src_w % 2 == 0 else src_w - 1
        out_h = src_h if src_h % 2 == 0 else src_h - 1

    # 2. Aspect ratio scaling / framing
    if settings.aspect_ratio != "original" and (src_w != out_w or src_h != out_h):
        if settings.framing_mode == "fill":
            # Crop to fill
            scale_filter = f"scale={out_w}:{out_h}:force_original_aspect_ratio=increase"
            crop_filter = f"crop={out_w}:{out_h}"
            filters.append(scale_filter)
            filters.append(crop_filter)
        else:
            # Fit with black letterbox / pillarbox padding
            scale_filter = f"scale={out_w}:{out_h}:force_original_aspect_ratio=decrease"
            pad_filter = f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:color=black"
            filters.append(scale_filter)
            filters.append(pad_filter)
    else:
        # Ensure dimensions are divisible by 2 for yuv420p
        filters.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")

    # 3. Duration handling on the video stream
    if mode == "source_timed":
        # In source-timed mode: maintain original video sequence unchanged, never freeze or loop
        filters.append(f"trim=duration={target_duration}")
    elif source_info.duration > 0 and source_info.duration < target_duration:
        diff = target_duration - source_info.duration
        if settings.duration_policy == "loop":
            # Loop filter
            filters.append(f"loop=loop=-1:size=32767:start=0")
            filters.append(f"trim=duration={target_duration}")
        else:
            # Default: extend final frame (tpad)
            filters.append(f"tpad=stop_mode=clone:stop_duration={diff + 0.1}")
            filters.append(f"trim=duration={target_duration}")
    else:
        # Source is longer or equal: trim to target duration
        filters.append(f"trim=duration={target_duration}")

    # Set PTS to ensure clean start
    filters.append("setpts=PTS-STARTPTS")

    # 4. Preview trimming if preview mode
    if is_preview:
        p_dur = min(preview_duration, target_duration)
        filters.append(f"trim=duration={p_dur}")
        filters.append("setpts=PTS-STARTPTS")

    # 5. Burn subtitles if enabled
    if settings.subtitles_enabled and subtitles_ass_path:
        ass_path_obj = Path(subtitles_ass_path)
        if ass_path_obj.exists():
            escaped_ass = escape_ffmpeg_filter_path(ass_path_obj)
            fonts_dir = escape_ffmpeg_filter_path(config.khmer_font_path.parent)
            filters.append(f"subtitles=filename='{escaped_ass}':fontsdir='{fonts_dir}'")

    filter_str = ",".join(filters)
    return filter_str, out_w, out_h
