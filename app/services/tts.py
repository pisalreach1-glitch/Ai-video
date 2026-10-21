"""TTS generation and boundary event capture with Edge-TTS."""
import asyncio
import logging
from pathlib import Path
from typing import Any, Callable
import edge_tts
from app.config import config

logger = logging.getLogger(__name__)

class TTSTimingError(Exception):
    """Raised when Edge-TTS fails to return valid timing events."""
    pass

async def generate_narration(
    text: str,
    voice: str = "km-KH-SreymomNeural",
    rate: str = "+0%",
    output_audio_path: Path | str = "voice.mp3",
    cancel_check: Callable[[], bool] | None = None,
) -> tuple[Path, float, list[dict[str, Any]]]:
    """
    Generate narration MP3 and timing events in a single Edge-TTS pass.
    Returns: (output_path, actual_duration_seconds, timing_events)
    where timing_events is: [{'start': float, 'end': float, 'text': str}, ...]
    """
    dest = Path(output_audio_path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    comm = edge_tts.Communicate(text=text.strip(), voice=voice, rate=rate)
    timing_events: list[dict[str, Any]] = []

    with open(dest, "wb") as audio_file:
        async for chunk in comm.stream():
            if cancel_check and cancel_check():
                audio_file.close()
                if dest.exists():
                    dest.unlink(missing_ok=True)
                raise RuntimeError("TTS generation was cancelled.")

            chunk_type = chunk.get("type")
            if chunk_type == "audio":
                audio_file.write(chunk.get("data", b""))
            elif chunk_type in ("SentenceBoundary", "WordBoundary"):
                # Edge-TTS offset and duration are in 100-nanosecond units (10,000,000 units = 1s)
                raw_offset = chunk.get("offset", 0)
                raw_duration = chunk.get("duration", 0)
                chunk_text = chunk.get("text", "").strip()

                start_sec = raw_offset / 10_000_000.0
                dur_sec = raw_duration / 10_000_000.0
                end_sec = start_sec + dur_sec

                if chunk_text:
                    timing_events.append({
                        "start": round(start_sec, 3),
                        "end": round(end_sec, 3),
                        "text": chunk_text,
                    })

    if not dest.exists() or dest.stat().st_size == 0:
        raise RuntimeError("Generated audio file is empty or missing.")

    # Measure exact audio duration from ffprobe or timing events
    from app.services.media import probe_audio_duration
    actual_duration = probe_audio_duration(dest)
    if actual_duration <= 0.0 and timing_events:
        actual_duration = max(ev["end"] for ev in timing_events)

    if not timing_events:
        # If no boundary event was produced by Edge-TTS (rare service hiccup),
        # raise TTSTimingError so calling code reports failure instead of fabricating timings
        raise TTSTimingError("Edge-TTS did not return subtitle timing events for this text.")

    # Ensure last event does not exceed actual duration
    if timing_events and actual_duration > 0.0:
        if timing_events[-1]["end"] > actual_duration + 0.5:
            timing_events[-1]["end"] = actual_duration

    return dest, actual_duration, timing_events
