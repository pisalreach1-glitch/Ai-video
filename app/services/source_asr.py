"""Source audio extraction and timed speech transcription using Faster-Whisper."""
from __future__ import annotations
import asyncio
import logging
import math
from pathlib import Path
from typing import Callable, Any
from app.config import config
from app.domain.dubbing import SourceSegment
from app.jobs.processes import run_process
from app.storage.workspaces import workspace

logger = logging.getLogger(__name__)

async def extract_source_audio(video_path: Path, output_wav: Path) -> Path:
    """Extract source audio as 16kHz mono 16-bit PCM WAV for source ASR."""
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        config.ffmpeg_path,
        "-y",
        "-i", str(video_path),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        str(output_wav),
    ]
    res = await run_process(cmd, timeout=120.0)
    if res.returncode != 0 or not output_wav.exists():
        raise RuntimeError(f"Failed to extract source audio: {res.stderr[:200]}")
    return output_wav

def group_and_validate_segments(
    raw_segments: list[dict[str, Any]],
    video_duration_ms: int,
    max_pause_merge_ms: int = 350,
    max_text_len: int = 120,
) -> list[SourceSegment]:
    """
    Validate timestamps, remove invalid/empty spans, and group contiguous speech
    without crossing meaningful pauses (> 350ms).
    """
    valid: list[dict[str, Any]] = []
    for s in raw_segments:
        text = str(s.get("text", "")).strip()
        if not text:
            continue
        start_ms = max(0, int(round(float(s.get("start", 0.0)) * 1000)))
        end_ms = int(round(float(s.get("end", 0.0)) * 1000))

        if video_duration_ms > 0:
            end_ms = min(end_ms, video_duration_ms)

        if end_ms <= start_ms:
            continue

        valid.append({
            "start_ms": start_ms,
            "end_ms": end_ms,
            "text": text,
            "words": s.get("words"),
            "language": s.get("language", "en"),
        })

    if not valid:
        return []

    # Sort strictly by start_ms
    valid.sort(key=lambda x: x["start_ms"])

    grouped: list[dict[str, Any]] = []
    for item in valid:
        if not grouped:
            grouped.append(item)
            continue

        prev = grouped[-1]
        gap_ms = item["start_ms"] - prev["end_ms"]
        combined_len = len(prev["text"]) + len(item["text"]) + 1

        # Merge only if gap is tiny and combined sentence is not too long
        if 0 <= gap_ms <= max_pause_merge_ms and combined_len <= max_text_len:
            prev["end_ms"] = max(prev["end_ms"], item["end_ms"])
            prev["text"] = f"{prev['text']} {item['text']}".strip()
            if item.get("words") and prev.get("words"):
                prev["words"].extend(item["words"])
        else:
            grouped.append(item)

    # Assign stable IDs s001, s002, ...
    result: list[SourceSegment] = []
    for i, g in enumerate(grouped, start=1):
        seg_id = f"s{i:03d}"
        result.append(SourceSegment(
            segment_id=seg_id,
            start_ms=g["start_ms"],
            end_ms=g["end_ms"],
            source_text=g["text"],
            source_language=g.get("language", "en"),
            words=g.get("words"),
            timing_origin="local_asr",
            needs_review=False,
        ))

    return result

def _patch_pyav_if_needed() -> None:
    """Ensure older PyAV versions without metadata_errors keyword argument do not crash."""
    try:
        import av
        if hasattr(av, "open") and not getattr(av, "_patched_metadata_errors", False):
            orig_open = av.open
            def safe_open(*args, **kwargs):
                kwargs.pop("metadata_errors", None)
                return orig_open(*args, **kwargs)
            av.open = safe_open
            av._patched_metadata_errors = True
    except Exception:
        pass

def _sync_transcribe(
    audio_path: str,
    video_duration_ms: int,
    model_name: str,
    device: str,
    compute_type: str,
) -> list[dict[str, Any]]:
    """Synchronous transcription using faster_whisper."""
    _patch_pyav_if_needed()
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise RuntimeError("faster-whisper is not installed. Please install requirements-dubbing.txt.")

    model = WhisperModel(model_name, device=device, compute_type=compute_type)
    segments, info = model.transcribe(
        audio_path,
        beam_size=5,
        word_timestamps=True,
        vad_filter=True,
    )

    detected_lang = getattr(info, "language", "en")
    extracted = []
    for seg in segments:
        words_data = None
        if hasattr(seg, "words") and seg.words:
            words_data = [
                {
                    "word": w.word,
                    "start": round(w.start, 3),
                    "end": round(w.end, 3),
                    "probability": round(w.probability, 3),
                }
                for w in seg.words
            ]
        extracted.append({
            "start": seg.start,
            "end": seg.end,
            "text": seg.text,
            "words": words_data,
            "language": detected_lang,
        })
    return extracted

async def transcribe_source(
    video_path: Path,
    video_duration: float,
    job_id: str,
    cancel_check: Callable[[], bool] | None = None,
) -> list[SourceSegment]:
    """
    Extract source audio and transcribe timed utterances using Faster-Whisper.
    Returns list of SourceSegment with canonical millisecond timestamps.
    """
    if cancel_check and cancel_check():
        raise RuntimeError("Transcription cancelled before start.")

    audio_wav = workspace.get_source_audio_path(job_id)
    await extract_source_audio(video_path, audio_wav)

    if cancel_check and cancel_check():
        audio_wav.unlink(missing_ok=True)
        raise RuntimeError("Transcription cancelled.")

    video_duration_ms = int(round(video_duration * 1000))

    try:
        raw_items = await asyncio.to_thread(
            _sync_transcribe,
            str(audio_wav),
            video_duration_ms,
            config.source_asr_model,
            config.source_asr_device,
            config.source_asr_compute_type,
        )
    finally:
        # Keep source_audio.wav for caching or remove if cancelled
        if cancel_check and cancel_check():
            audio_wav.unlink(missing_ok=True)

    segments = group_and_validate_segments(raw_items, video_duration_ms)
    return segments
