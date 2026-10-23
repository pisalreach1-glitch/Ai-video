"""Unit tests for Voice Conversion snapshot persistence, approval, and checksum verification."""
import pytest
import hashlib
import wave
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.storage.jobs import job_storage
from app.features.voice_conversion.storage import voice_conversion_storage
from app.features.voice_conversion.handlers import cb_approve_and_render_full, cb_play_converted_audio
from app.features.talking_photo.storage import talking_photo_storage
from app.features.talking_photo.pipeline import talking_photo_pipeline
from app.domain.features import QueueTask, JobFeature

def create_sample_wav(path: Path, duration_sec: float = 2.0, rate: int = 24000) -> str:
    n_frames = int(rate * duration_sec)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(bytearray(n_frames * 2))
    return hashlib.sha256(path.read_bytes()).hexdigest()

def test_voice_conversion_storage_crud(tmp_path):
    """Verify storing, completing, and querying voice conversion records in database."""
    user_id = 998877

    # Ensure clean job
    job = job_storage.create_job(user_id=user_id, chat_id=12345, feature="talking_photo")
    job_id = job.job_id

    ref_wav = tmp_path / "ref.wav"
    src_wav = tmp_path / "src.wav"
    ref_sha = create_sample_wav(ref_wav, 5.0)
    src_sha = create_sample_wav(src_wav, 10.0)

    conv = voice_conversion_storage.create_conversion(
        job_id=job_id,
        owner_user_id=user_id,
        target_reference_path=str(ref_wav),
        target_reference_sha256=ref_sha,
        target_reference_duration=5.0,
        full_source_path=str(src_wav),
        full_source_sha256=src_sha,
        full_source_duration=10.0,
        request_digest="digest-test-01",
        backend_id="seed_vc",
    )

    assert conv.conversion_id.startswith("vc_")
    assert conv.state == "pending"

    # Mark completed
    conv_wav = tmp_path / "converted.wav"
    conv_sha = create_sample_wav(conv_wav, 10.0)
    voice_conversion_storage.update_conversion_completed(
        conversion_id=conv.conversion_id,
        converted_wav_path=str(conv_wav),
        converted_wav_sha256=conv_sha,
        converted_duration=10.0,
        manifest_path=str(tmp_path / "manifest.json"),
    )

    latest = voice_conversion_storage.get_latest_conversion_for_job(job_id)
    assert latest is not None
    assert latest.state == "ready"
    assert latest.converted_wav_sha256 == conv_sha
    assert latest.converted_duration == 10.0

@pytest.mark.asyncio
async def test_vc_approval_enqueues_final_talking_photo_task(tmp_path):
    """Verify approving conversion queues final talking photo render with converted audio."""
    user_id = 554433
    job = job_storage.create_job(user_id=user_id, chat_id=12345, feature="talking_photo")
    job_id = job.job_id

    ref_wav = tmp_path / "ref.wav"
    src_wav = tmp_path / "src.wav"
    create_sample_wav(ref_wav, 5.0)
    create_sample_wav(src_wav, 10.0)

    conv = voice_conversion_storage.create_conversion(
        job_id=job_id,
        owner_user_id=user_id,
        target_reference_path=str(ref_wav),
        target_reference_sha256="dummy_ref",
        target_reference_duration=5.0,
        full_source_path=str(src_wav),
        full_source_sha256="dummy_src",
        full_source_duration=10.0,
        request_digest="digest-appr",
        backend_id="seed_vc",
    )

    # Create dummy talking photo revision
    talking_photo_storage.create_revision(
        job_id=job_id,
        image_path=str(tmp_path / "portrait.png"),
        original_voice_path=str(src_wav),
        audio_source="converted_voice",
    )

    cb = AsyncMock()
    cb.data = f"vc_appr:{job_id}"
    cb.from_user.id = user_id
    cb.answer = AsyncMock()
    cb.message = AsyncMock()
    cb.message.answer = AsyncMock()
    cb.message.edit_reply_markup = AsyncMock()
    state = AsyncMock()

    await cb_approve_and_render_full(cb, state)

    # Queue should contain a "final" task for talking_photo
    conn = job_storage.db.get_connection()
    row = conn.execute("SELECT * FROM render_queue WHERE job_id = ?", (job_id,)).fetchone()
    assert row is not None
    assert row["task_type"] == "final"
    assert row["feature"] == JobFeature.TALKING_PHOTO.value
    conn.execute("DELETE FROM render_queue WHERE job_id = ?", (job_id,))

@pytest.mark.asyncio
async def test_tp_pipeline_detects_converted_audio_tampering(tmp_path):
    """Verify that tampering with converted master audio raises checksum mismatch error."""
    user_id = 776655
    job = job_storage.create_job(user_id=user_id, chat_id=12345, feature="talking_photo")
    job_id = job.job_id

    master_wav = tmp_path / "master.wav"
    orig_sha = create_sample_wav(master_wav, duration_sec=4.0)

    conv = voice_conversion_storage.create_conversion(
        job_id=job_id,
        owner_user_id=user_id,
        target_reference_path=str(tmp_path / "ref.wav"),
        target_reference_sha256="ref_sha",
        target_reference_duration=4.0,
        full_source_path=str(tmp_path / "src.wav"),
        full_source_sha256="src_sha",
        full_source_duration=4.0,
        request_digest="tamper-digest",
        backend_id="seed_vc",
    )
    voice_conversion_storage.update_conversion_completed(
        conversion_id=conv.conversion_id,
        converted_wav_path=str(master_wav),
        converted_wav_sha256=orig_sha,
        converted_duration=4.0,
        manifest_path=str(tmp_path / "manifest.json"),
    )

    talking_photo_storage.create_revision(
        job_id=job_id,
        image_path=str(tmp_path / "portrait.png"),
        original_voice_path=str(master_wav),
        audio_source="converted_voice",
    )

    # Now tamper with master_wav
    master_wav.write_bytes(b"corrupted_or_different_audio_bytes")

    task = QueueTask(
        job_id=job_id,
        revision_id=1,
        feature="talking_photo",
        task_type="final",
        user_id=user_id,
        input_digest="tamper-digest",
    )

    worker_pool = AsyncMock()
    worker_pool.get_bot.return_value = None
    worker_pool.is_cancelled.return_value = False

    # Pipeline should raise checksum mismatch
    with pytest.raises(RuntimeError, match="Master audio checksum mismatch"):
        await talking_photo_pipeline.run(task, worker_pool)
