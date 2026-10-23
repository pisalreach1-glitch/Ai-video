"""Source audio timeline chunking for long-form speech conversion."""
from dataclasses import dataclass
from pathlib import Path
from typing import List
from app.config import config
from app.jobs.processes import run_process
from app.features.voice_conversion.media import validate_audio_file

@dataclass(frozen=True)
class AudioChunk:
    chunk_id: str
    index: int
    start_seconds: float
    end_seconds: float
    duration_seconds: float

def compute_timeline_chunks(
    total_duration: float,
    max_chunk_sec: float = 30.0,
    overlap_sec: float = 1.0,
) -> List[AudioChunk]:
    """
    Split long speech timeline into overlapping chunks to ensure continuous prosody.
    For short audio (<= max_chunk_sec), returns a single chunk.
    """
    if total_duration <= 0:
        return []

    if total_duration <= max_chunk_sec:
        return [AudioChunk(
            chunk_id="chunk_001",
            index=1,
            start_seconds=0.0,
            end_seconds=total_duration,
            duration_seconds=total_duration,
        )]

    chunks = []
    idx = 1
    current_start = 0.0

    while current_start < total_duration:
        current_end = min(total_duration, current_start + max_chunk_sec)
        dur = current_end - current_start
        chunks.append(AudioChunk(
            chunk_id=f"chunk_{idx:03d}",
            index=idx,
            start_seconds=round(current_start, 3),
            end_seconds=round(current_end, 3),
            duration_seconds=round(dur, 3),
        ))
        if current_end >= total_duration:
            break
        current_start += (max_chunk_sec - overlap_sec)
        idx += 1

    return chunks

async def extract_audio_chunk(
    source_wav: Path,
    chunk: AudioChunk,
    output_wav: Path,
) -> Path:
    """Extract an audio slice for model processing."""
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        config.ffmpeg_path,
        "-y",
        "-ss", f"{chunk.start_seconds:.3f}",
        "-t", f"{chunk.duration_seconds:.3f}",
        "-i", str(source_wav),
        "-c:a", "pcm_s16le",
        str(output_wav),
    ]
    res = await run_process(cmd, timeout=30.0)
    if res.returncode != 0 or not output_wav.exists():
        raise RuntimeError(f"Failed to extract audio chunk {chunk.chunk_id}: {res.stderr[:200]}")
    return output_wav
