"""Unit tests verifying Voice Conversion support for long source audio (>= 120s).

Ensures:
- Full source speech >= 120 seconds is not truncated to short target reference duration.
- Final spoken phrase is preserved.
- Timeline chunking covers start to end.
- Lossless assembly produces valid master WAV.
"""
import pytest
import wave
from pathlib import Path

from app.features.voice_conversion.chunking import compute_timeline_chunks
from app.features.voice_conversion.assembly import assemble_converted_audio
from app.features.voice_conversion.quality import evaluate_conversion_quality
from engines.seed_vc_bridge.runner import convert_voice

def create_test_wav(path: Path, duration_sec: float, rate: int = 24000):
    n_frames = int(rate * duration_sec)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(bytearray(n_frames * 2))

def test_long_source_timeline_chunks_covers_final_phrase():
    """Verify that a 125-second speech is split into overlapping chunks ending at 125.0s."""
    total_dur = 125.0
    chunks = compute_timeline_chunks(total_duration=total_dur, max_chunk_sec=30.0, overlap_sec=1.0)
    assert len(chunks) >= 4
    # First chunk starts at 0.0
    assert chunks[0].start_seconds == 0.0
    # Last chunk must end at the exact total duration (preserves final phrase)
    assert chunks[-1].end_seconds == total_dur

@pytest.mark.asyncio
async def test_lossless_chunk_assembly(tmp_path):
    """Verify assembling two 5-second audio chunks results in a valid 10-second master."""
    chunk1 = tmp_path / "chunk1.wav"
    chunk2 = tmp_path / "chunk2.wav"
    master = tmp_path / "assembled_master.wav"

    create_test_wav(chunk1, duration_sec=5.0)
    create_test_wav(chunk2, duration_sec=5.0)

    out_p, dur, sha256 = await assemble_converted_audio([chunk1, chunk2], master)
    assert out_p.exists()
    assert 9.8 <= dur <= 10.2
    assert len(sha256) == 64

def test_quality_evaluation_catches_truncation():
    """Verify that quality evaluation flags any audio cut short."""
    # Scenario A: 120s source and 120s converted (passed)
    report_good = evaluate_conversion_quality(source_duration=120.0, converted_duration=120.0)
    assert report_good.is_acceptable is True
    assert report_good.final_phrase_preserved is True

    # Scenario B: 120s source mistakenly truncated to 15s reference (failed)
    report_bad = evaluate_conversion_quality(source_duration=120.0, converted_duration=15.0)
    assert report_bad.is_acceptable is False
    assert report_bad.final_phrase_preserved is False
    assert "substantially shorter" in report_bad.notes

def test_120_second_source_not_truncated_to_short_reference(tmp_path):
    """Verify 120s source with 10s reference retains >= 120s in output."""
    short_ref = tmp_path / "short_ref_10s.wav"
    long_source = tmp_path / "long_source_120s.wav"
    out_master = tmp_path / "out_master.wav"

    create_test_wav(short_ref, duration_sec=10.0)
    create_test_wav(long_source, duration_sec=120.0)

    req = {
        "full_source_wav": str(long_source),
        "target_reference_wav": str(short_ref),
        "output_wav": str(out_master),
    }

    res = convert_voice(req)
    assert res["status"] == "success"
    assert abs(res["duration_seconds"] - 120.0) < 0.2
    assert res["duration_seconds"] > 119.0
