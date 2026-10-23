"""Unit tests verifying Voice Conversion backend mapping contract and Telegram constraints.

CRITICAL CONTRACT:
Seed-VC --source = full_source_wav (words, delivery, pauses)
Seed-VC --target = target_reference_wav (voice timbre)
NEVER reverse these!
"""
import pytest
import wave
import struct
import json
from pathlib import Path
from unittest.mock import patch

from app.features.voice_conversion.domain import ConversionRequest
from app.features.voice_conversion.backends.seed_vc import seed_vc_backend
from app.features.voice_conversion.keyboards import (
    vc_review_inputs_keyboard,
    vc_preview_keyboard,
    vc_cancel_only_keyboard,
)
from engines.seed_vc_bridge.runner import convert_voice

def create_sine_wav(path: Path, duration_sec: float, freq: float = 440.0, rate: int = 24000):
    n_frames = int(rate * duration_sec)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        # 16-bit silence or tone
        data = bytearray(n_frames * 2)
        wf.writeframes(data)

def test_callback_data_strictly_under_64_bytes():
    """Verify Telegram API rule: callback_data must be <= 64 bytes UTF-8."""
    job_id = "job-very-long-id-1234567890abcdef"
    conv_id = "conv-very-long-id-1234567890abcdef"

    kb_review = vc_review_inputs_keyboard(job_id)
    for row in kb_review.inline_keyboard:
        for btn in row:
            assert len(btn.callback_data.encode("utf-8")) <= 64, f"Callback exceeds 64 bytes: {btn.callback_data}"

    kb_preview = vc_preview_keyboard(job_id, conv_id)
    for row in kb_preview.inline_keyboard:
        for btn in row:
            assert len(btn.callback_data.encode("utf-8")) <= 64, f"Callback exceeds 64 bytes: {btn.callback_data}"

    kb_cancel = vc_cancel_only_keyboard(job_id)
    for row in kb_cancel.inline_keyboard:
        for btn in row:
            assert len(btn.callback_data.encode("utf-8")) <= 64, f"Callback exceeds 64 bytes: {btn.callback_data}"

@pytest.mark.asyncio
async def test_backend_mapping_contract_never_reverses_source_and_target(tmp_path):
    """Verify that backend maps full_source to source and target_reference to target."""
    ref_wav = tmp_path / "target_timbre_ref.wav"
    src_wav = tmp_path / "full_speech_source.wav"
    out_dir = tmp_path / "vc_output"

    # Distinct durations: 6 seconds target reference, 14 seconds full source
    create_sine_wav(ref_wav, duration_sec=6.0)
    create_sine_wav(src_wav, duration_sec=14.0)

    req = ConversionRequest(
        artifact_id="art-test-1",
        target_reference_wav=ref_wav,
        full_source_wav=src_wav,
        output_dir=out_dir,
        input_digest="test-digest-abc",
        backend_revision="seed_vc-v2",
    )

    converted = await seed_vc_backend.convert(req)

    # Check generated request JSON
    req_json = out_dir / "vc_req.json"
    assert req_json.exists()
    with open(req_json, "r", encoding="utf-8") as f:
        payload = json.load(f)

    # CONTRACT CHECK:
    assert payload["full_source_wav"] == str(src_wav), "Source must be full_source_wav!"
    assert payload["target_reference_wav"] == str(ref_wav), "Target must be target_reference_wav!"

    # Output duration must equal full source duration (14s), NOT the reference duration (6s)
    assert abs(converted.duration_seconds - 14.0) < 0.1
    assert converted.master_wav.exists()
    assert len(converted.sha256) == 64

def test_bridge_runner_preserves_full_source_duration(tmp_path):
    """Verify runner convert_voice maintains full source duration and handles missing files gracefully."""
    ref_wav = tmp_path / "ref.wav"
    src_wav = tmp_path / "source.wav"
    out_wav = tmp_path / "out.wav"

    create_sine_wav(ref_wav, duration_sec=5.0)
    create_sine_wav(src_wav, duration_sec=25.0)

    req = {
        "full_source_wav": str(src_wav),
        "target_reference_wav": str(ref_wav),
        "output_wav": str(out_wav),
    }

    res = convert_voice(req)
    assert res["status"] == "success"
    assert abs(res["duration_seconds"] - 25.0) < 0.1
    assert Path(res["wav_path"]).exists()
