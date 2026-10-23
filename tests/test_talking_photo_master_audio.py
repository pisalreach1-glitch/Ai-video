"""Tests for master audio checksum validation and mux stream mapping."""
import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
import pytest
from app.features.talking_photo.long_render import mux_master_audio
from app.features.talking_photo.pipeline import TalkingPhotoPipeline
from app.domain.features import QueueTask, JobFeature
from app.storage.database import Database
from app.storage.jobs import JobStorage
from app.features.voice_clone.storage import VoiceCloneStorage
from app.features.talking_photo.storage import TalkingPhotoStorage, TalkingPhotoSettings

@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_tp_master.sqlite3"
    return Database(db_file)

@pytest.mark.asyncio
async def test_mux_master_audio_invokes_correct_stream_mapping(tmp_path):
    """Verify mux_master_audio uses -map 0:v:0 and -map 1:a:0 to keep audio and video strictly synchronized."""
    video_track = tmp_path / "raw_video.mp4"
    video_track.write_text("fake video")
    master_audio = tmp_path / "master.wav"
    master_audio.write_text("fake audio")
    output_mp4 = tmp_path / "final.mp4"

    recorded_cmds = []

    async def mock_run_process(cmd, **kwargs):
        recorded_cmds.append(cmd)
        # Create dummy output file so existence check passes
        output_mp4.touch()
        res = MagicMock()
        res.returncode = 0
        res.stderr = ""
        return res

    with patch("app.features.talking_photo.long_render.run_process", side_effect=mock_run_process), \
         patch("app.features.talking_photo.long_render.measure_audio_duration", new=AsyncMock(return_value=125.0)):
        res_path = await mux_master_audio(
            video_track=video_track,
            master_audio=master_audio,
            output_mp4=output_mp4,
            preview_limit=5.0,
        )

    assert res_path == output_mp4
    assert len(recorded_cmds) == 1
    cmd = recorded_cmds[0]

    # Verify stream maps
    assert "-map" in cmd
    map_idx_1 = cmd.index("-map")
    assert cmd[map_idx_1 + 1] == "0:v:0"
    map_idx_2 = cmd.index("-map", map_idx_1 + 2)
    assert cmd[map_idx_2 + 1] == "1:a:0"

    # Verify duration limit for preview is 5.0s
    assert "-t" in cmd
    t_idx = cmd.index("-t")
    assert cmd[t_idx + 1] == "5.000"

@pytest.mark.asyncio
async def test_pipeline_rejects_corrupted_master_audio(tmp_path, temp_db):
    """Verify pipeline rejects rendering if master audio file checksum differs from active approval."""
    job_store = JobStorage(temp_db)
    vc_store = VoiceCloneStorage(temp_db)
    tp_store = TalkingPhotoStorage(temp_db)

    user_id = 12345
    job = job_store.create_job(user_id=user_id, chat_id=12345, feature=JobFeature.TALKING_PHOTO.value)
    job_id = job.job_id

    # Create reference and artifact
    ref = vc_store.save_reference(
        owner_user_id=user_id,
        job_id=job_id,
        wav_path=str(tmp_path / "ref.wav"),
        sha256="ref_hash",
        duration_seconds=5.0,
    )

    art = vc_store.create_artifact(
        job_id=job_id,
        owner_user_id=user_id,
        reference_id=ref.reference_id,
        reference_sha256=ref.sha256,
        text="អត្ថបទ",
        text_sha256="text_hash",
        request_digest="req_001",
        artifact_id="art_001",
    )

    # Create dummy master audio file
    master_file = tmp_path / "master.wav"
    master_file.write_bytes(b"original authentic master audio data")
    expected_hash = hashlib.sha256(b"original authentic master audio data").hexdigest()

    vc_store.update_artifact_completed(
        artifact_id=art.artifact_id,
        wav_path=str(master_file),
        wav_sha256=expected_hash,
        duration_seconds=10.0,
    )

    # Create active approval with expected hash
    vc_store.approve_audio(
        job_id=job_id,
        artifact_id=art.artifact_id,
        request_digest="req_001",
        wav_sha256=expected_hash,
        owner_user_id=user_id,
    )

    # Now simulate file tampering/corruption
    master_file.write_bytes(b"tampered or different audio content")

    # Create TP revision pointing to this master file
    st = TalkingPhotoSettings()
    img_file = tmp_path / "face.png"
    img_file.touch()

    rev = tp_store.create_revision(
        job_id=job_id,
        image_path=str(img_file),
        original_voice_path=str(master_file),
        settings=st,
        input_digest="hash",
        audio_source="cloned_voice",
        approved_audio_artifact_id=art.artifact_id,
    )

    pipeline = TalkingPhotoPipeline()

    task = QueueTask(
        job_id=job_id,
        revision_id=rev.revision_id,
        feature=JobFeature.TALKING_PHOTO.value,
        task_type="preview",
        user_id=user_id,
    )
    mock_worker_pool = MagicMock()
    mock_worker_pool.is_cancelled.return_value = False

    with patch("app.features.talking_photo.pipeline.job_storage", job_store), \
         patch("app.features.talking_photo.pipeline.talking_photo_storage", tp_store), \
         patch("app.features.voice_clone.storage.voice_clone_storage", vc_store):
        with pytest.raises(RuntimeError, match="Master audio checksum mismatch"):
            await pipeline.run(task, mock_worker_pool)
