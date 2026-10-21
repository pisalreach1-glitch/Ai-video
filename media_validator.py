"""
Media validation utility for Video Bot.
Detects:
- Corrupt media or truncated files -> CorruptMediaError
- Missing audio stream -> NoAudioStreamError
Extracts stream metadata (duration, width, height, audio codec).
"""

import json
import logging
from dataclasses import dataclass
from typing import Optional, Tuple
from pathlib import Path

from utils import get_ffmpeg_path
from process_runner import ProcessRunner
from errors import CorruptMediaError, NoAudioStreamError

logger = logging.getLogger(__name__)


@dataclass
class MediaInfo:
    duration: float
    width: int
    height: int
    has_audio: bool
    has_video: bool
    audio_codec: Optional[str] = None
    video_codec: Optional[str] = None


def probe_media(file_path: str, timeout: float = 30.0) -> MediaInfo:
    """
    Probes media file using FFmpeg/ffprobe.
    Raises CorruptMediaError if file is invalid/corrupt.
    Raises NoAudioStreamError if file has no audio stream.
    """
    path = Path(file_path)
    if not path.exists() or path.stat().st_size == 0:
        raise CorruptMediaError(f"Media file does not exist or is empty: {file_path}")

    ffmpeg = get_ffmpeg_path()
    # Use ffmpeg -i to probe streams in stderr (standard across all ffmpeg builds)
    cmd = [ffmpeg, "-i", str(path)]
    try:
        proc_out = ProcessRunner.run(cmd, timeout=timeout)
        stderr = proc_out.stderr
    except Exception as e:
        raise CorruptMediaError(f"Failed to probe media file: {e}")

    # Check for corrupt media signatures
    corrupt_patterns = [
        "moov atom not found",
        "Invalid data found when processing input",
        "could not find codec parameters",
        "EBML header parsing failed",
        "error reading header"
    ]
    for pattern in corrupt_patterns:
        if pattern.lower() in stderr.lower():
            raise CorruptMediaError(f"Corrupt or incomplete media ({pattern}): {file_path}")

    # Parse duration
    import re
    dur_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", stderr)
    duration = 0.0
    if dur_match:
        dh, dm, ds = dur_match.groups()
        duration = float(dh) * 3600.0 + float(dm) * 60.0 + float(ds)

    # Parse video stream & resolution
    has_video = False
    width = 1080
    height = 1920
    video_codec = None
    v_match = re.search(r"Stream #\d+:\d+.*Video:\s*([a-zA-Z0-9_\-]+).*, (\d{3,5})x(\d{3,5})", stderr)
    if v_match:
        has_video = True
        video_codec = v_match.group(1)
        width = int(v_match.group(2))
        height = int(v_match.group(3))

    # Parse audio stream
    has_audio = False
    audio_codec = None
    a_match = re.search(r"Stream #\d+:\d+.*Audio:\s*([a-zA-Z0-9_\-]+)", stderr)
    if a_match:
        has_audio = True
        audio_codec = a_match.group(1)

    if not has_video and not has_audio:
        raise CorruptMediaError(f"Media file contains neither video nor audio streams: {file_path}")

    return MediaInfo(
        duration=duration,
        width=width,
        height=height,
        has_audio=has_audio,
        has_video=has_video,
        audio_codec=audio_codec,
        video_codec=video_codec
    )


def validate_video_with_audio(video_path: str, timeout: float = 30.0) -> MediaInfo:
    """
    Validates that a video is readable and contains an audio stream.
    Throws CorruptMediaError if video cannot be decoded.
    Throws NoAudioStreamError if video lacks audio.
    """
    info = probe_media(video_path, timeout=timeout)
    if not info.has_audio:
        raise NoAudioStreamError(f"Video '{video_path}' does not contain an audio track.")
    return info
