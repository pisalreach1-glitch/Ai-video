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
    mode: str = "free_narration",
    start_time: float = 0.0,
) -> Path:
    """
    Renders up to 5-second video preview matching the full video's
    voice, subtitles, framing, and audio mix.
    If start_time > 0, produces a rebased excerpt window.
    """
    if start_time <= 0.0:
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
            mode=mode,
        )

    # Rebased excerpt preview around a specific timestamp
    return await render_timed_excerpt(
        source_path=source_path,
        assembled_audio_path=voice_audio_path,
        output_preview_path=output_preview_path,
        settings=settings,
        start_sec=start_time,
        duration_sec=preview_duration,
        subtitles_ass_path=subtitles_ass_path,
        timeout_seconds=timeout_seconds,
        cancel_check=cancel_check,
        on_pid=on_pid,
    )

async def render_timed_excerpt(
    source_path: Path | str,
    assembled_audio_path: Path | str | None,
    output_preview_path: Path | str,
    settings: VoiceSettings,
    start_sec: float,
    duration_sec: float = 5.0,
    subtitles_ass_path: Path | str | None = None,
    timeout_seconds: float = 60.0,
    cancel_check: Callable[[], bool] | None = None,
    on_pid: Callable[[int], None] | None = None,
    variant: str = "dubbed",  # "dubbed" | "original"
) -> Path:
    """
    Renders an excerpt window [start_sec, start_sec + duration_sec] trimming video and audio
    together. Supports:
    - variant='original': Source video + Source audio (no TTS dependency, works before translation).
    - variant='dubbed': Source video + Dubbed audio (respecting source_audio_mode mix) + Rebased subtitles.
    """
    from app.config import config
    from app.jobs.processes import run_process, ProcessResult
    from app.services.media import probe_media, escape_ffmpeg_filter_path

    src = Path(source_path)
    dest = Path(output_preview_path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    source_info = probe_media(src)
    src_w = source_info.width if source_info.width > 0 else 1080
    src_h = source_info.height if source_info.height > 0 else 1920

    if settings.aspect_ratio == "9:16":
        out_w, out_h = 1080, 1920
    elif settings.aspect_ratio == "1:1":
        out_w, out_h = 1080, 1080
    else:
        out_w = src_w if src_w % 2 == 0 else src_w - 1
        out_h = src_h if src_h % 2 == 0 else src_h - 1

    v_filters = []
    if settings.aspect_ratio != "original" and (src_w != out_w or src_h != out_h):
        if settings.framing_mode == "fill":
            v_filters.append(f"scale={out_w}:{out_h}:force_original_aspect_ratio=increase")
            v_filters.append(f"crop={out_w}:{out_h}")
        else:
            v_filters.append(f"scale={out_w}:{out_h}:force_original_aspect_ratio=decrease")
            v_filters.append(f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:color=black")
    else:
        v_filters.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")

    v_filters.append(f"trim=start={start_sec:.3f}:duration={duration_sec:.3f}")
    v_filters.append("setpts=PTS-STARTPTS")

    # Rebase subtitles if present and variant is dubbed
    rebased_ass: Path | None = None
    if variant == "dubbed" and settings.subtitles_enabled and subtitles_ass_path:
        ass_path = Path(subtitles_ass_path)
        if ass_path.exists():
            rebased_ass = dest.parent / f"rebased_{start_sec:.1f}.ass"
            _rebase_ass_file(ass_path, rebased_ass, start_sec, duration_sec)
            escaped_ass = escape_ffmpeg_filter_path(rebased_ass)
            fonts_dir = escape_ffmpeg_filter_path(config.khmer_font_path.parent)
            v_filters.append(f"subtitles=filename='{escaped_ass}':fontsdir='{fonts_dir}'")

    v_filter_str = ",".join(v_filters)

    if variant == "original" or not assembled_audio_path:
        # Original video + Original source audio
        a_filter_str = f"[0:a]atrim=start={start_sec:.3f}:duration={duration_sec:.3f},asetpts=PTS-STARTPTS[aout]"
        full_filter = f"[0:v]{v_filter_str}[vout]; {a_filter_str}"
        cmd = [
            config.ffmpeg_path,
            "-y",
            "-i", str(src),
            "-filter_complex", full_filter,
            "-map", "[vout]",
            "-map", "[aout]",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "22",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-movflags", "+faststart",
            "-t", f"{duration_sec:.3f}",
            str(dest),
        ]
    else:
        audio = Path(assembled_audio_path)
        if settings.source_audio_mode == "low_mix" and source_info.has_audio:
            a_filter_str = (
                f"[1:a]atrim=start={start_sec:.3f}:duration={duration_sec:.3f},asetpts=PTS-STARTPTS[anarr]; "
                f"[0:a]volume=0.15,atrim=start={start_sec:.3f}:duration={duration_sec:.3f},apad,asetpts=PTS-STARTPTS[asrc]; "
                f"[anarr][asrc]amix=inputs=2:duration=first:dropout_transition=0,atrim=0:{duration_sec:.3f}[aout]"
            )
        else:
            a_filter_str = f"[1:a]atrim=start={start_sec:.3f}:duration={duration_sec:.3f},asetpts=PTS-STARTPTS[aout]"

        full_filter = f"[0:v]{v_filter_str}[vout]; {a_filter_str}"
        cmd = [
            config.ffmpeg_path,
            "-y",
            "-i", str(src),
            "-i", str(audio),
            "-filter_complex", full_filter,
            "-map", "[vout]",
            "-map", "[aout]",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "22",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-movflags", "+faststart",
            "-t", f"{duration_sec:.3f}",
            str(dest),
        ]

    try:
        res: ProcessResult = await run_process(
            cmd=cmd,
            timeout=timeout_seconds,
            cancel_check=cancel_check,
            on_pid=on_pid,
        )
        if res.returncode != 0 or not dest.exists():
            raise RuntimeError(f"Preview excerpt render failed: {res.stderr[:200]}")
        return dest
    finally:
        if rebased_ass and rebased_ass.exists():
            rebased_ass.unlink(missing_ok=True)


async def render_full_preview_video(
    source_path: Path | str,
    voice_audio_path: Path | str,
    output_path: Path | str,
    settings: VoiceSettings,
    target_duration: float,
    subtitles_ass_path: Path | str | None = None,
    timeout_seconds: float = 300.0,
    cancel_check: Callable[[], bool] | None = None,
    on_pid: Callable[[int], None] | None = None,
) -> Path:
    """
    Renders a fast-encoding preview of the entire video timeline at preview resolution.
    Used for the full-timeline approval gate before final export.
    """
    return await render_video(
        source_path=source_path,
        voice_audio_path=voice_audio_path,
        output_path=output_path,
        settings=settings,
        target_duration=target_duration,
        subtitles_ass_path=subtitles_ass_path,
        is_preview=False,  # renders full duration
        timeout_seconds=timeout_seconds,
        cancel_check=cancel_check,
        on_pid=on_pid,
        mode="source_timed",
    )

def _rebase_ass_file(src_ass: Path, dest_ass: Path, start_sec: float, dur_sec: float) -> None:
    from timecode_utils import parse_timecode, format_ass_timestamp
    lines = src_ass.read_text(encoding="utf-8").splitlines()
    rebased_lines = []
    end_sec = start_sec + dur_sec

    for line in lines:
        if line.startswith("Dialogue:"):
            parts = line.split(",", 9)
            if len(parts) == 10:
                try:
                    c_start = parse_timecode(parts[1].strip(), allow_legacy=True)
                    c_end = parse_timecode(parts[2].strip(), allow_legacy=True)

                    # Check if cue overlaps window [start_sec, end_sec]
                    if c_end > start_sec and c_start < end_sec:
                        reb_start = max(0.0, c_start - start_sec)
                        reb_end = min(dur_sec, c_end - start_sec)
                        if reb_end > reb_start:
                            parts[1] = format_ass_timestamp(reb_start)
                            parts[2] = format_ass_timestamp(reb_end)
                            rebased_lines.append(",".join(parts))
                        continue
                except Exception:
                    pass
            continue
        rebased_lines.append(line)

    dest_ass.write_text("\n".join(rebased_lines) + "\n", encoding="utf-8")
