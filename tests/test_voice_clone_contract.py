"""Unit tests for VoiceCloneBackend protocol and synthesis assembly."""
import pytest
from pathlib import Path
from app.config import config
from app.jobs.processes import run_process
from app.features.voice_clone.domain import CloneRequest
from app.features.voice_clone.backends.local import local_clone_backend
from app.features.voice_clone.assembly import assemble_audio_chunks

@pytest.mark.asyncio
async def test_backend_capabilities_contract():
    caps = await local_clone_backend.capabilities()
    assert hasattr(caps, "backend_id")
    assert hasattr(caps, "languages")
    assert hasattr(caps, "reference_min_seconds")
    assert hasattr(caps, "max_text_units_per_chunk")
    assert caps.reference_min_seconds == 3.0

@pytest.mark.asyncio
async def test_assemble_chunks_concatenation(tmp_path):
    # Create two synthetic chunks with distinct frequencies
    c1 = tmp_path / "chunk_0.wav"
    c2 = tmp_path / "chunk_1.wav"
    for path, freq in [(c1, 350), (c2, 500)]:
        cmd = [
            config.ffmpeg_path,
            "-y",
            "-f", "lavfi",
            "-i", f"sine=frequency={freq}:duration=1.2",
            "-ar", "48000",
            "-ac", "1",
            "-c:a", "pcm_s16le",
            str(path),
        ]
        await run_process(cmd, timeout=30.0)

    out_master = tmp_path / "assembled_master.wav"
    wav_path, dur, sha256 = await assemble_audio_chunks(
        chunk_paths=[c1, c2],
        output_master_wav=out_master,
        pause_ms=100,
        sample_rate=48000,
    )

    assert wav_path.exists()
    # 1.2 + 0.1 (pause) + 1.2 = ~2.5s
    assert 2.3 <= dur <= 2.7
    assert len(sha256) == 64

@pytest.mark.asyncio
async def test_synthesis_smoke_pipeline(tmp_path):
    ref_wav = tmp_path / "ref.wav"
    cmd = [
        config.ffmpeg_path,
        "-y",
        "-f", "lavfi",
        "-i", "sine=frequency=400:duration=4.0",
        "-ar", "24000",
        "-ac", "1",
        "-c:a", "pcm_s16le",
        str(ref_wav),
    ]
    await run_process(cmd, timeout=30.0)

    req = CloneRequest(
        artifact_id="art_test_123",
        owner_user_id=999,
        reference_wav=ref_wav,
        reference_sha256="dummy_sha",
        text="ឃ្លាទីមួយសម្រាប់តេស្ត។ ឃ្លាទីពីរសម្រាប់តេស្ត។",
        language="km",
        output_dir=tmp_path / "output",
        model_version="1.0.0",
        settings_digest="digest_test",
    )

    output = await local_clone_backend.synthesize(
        req,
        cancel_check=lambda: False,
        on_pid=lambda pid: None,
    )

    assert output.wav_path.exists()
    assert output.duration_seconds > 0.0
    assert output.manifest_path.exists()
    assert len(output.sha256) == 64
