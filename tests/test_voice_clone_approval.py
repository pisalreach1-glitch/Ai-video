"""Tests for Voice Clone audio approvals, transactional updates, and invalidations."""
import pytest
from app.storage.database import Database
from app.storage.jobs import JobStorage
from app.features.voice_clone.storage import VoiceCloneStorage
from app.features.talking_photo.storage import TalkingPhotoStorage, TalkingPhotoSettings
from app.domain.features import JobFeature

@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_vc_approval.sqlite3"
    return Database(db_file)

def test_approve_audio_transactional(temp_db):
    job_store = JobStorage(temp_db)
    vc_store = VoiceCloneStorage(temp_db)
    user_id = 999

    job = job_store.create_job(user_id=user_id, chat_id=123, feature=JobFeature.TALKING_PHOTO.value)
    job_id = job.job_id

    ref = vc_store.save_reference(
        owner_user_id=user_id,
        job_id=job_id,
        wav_path="/path/ref.wav",
        sha256="ref_sha256_abc",
        duration_seconds=12.5,
    )
    assert ref.version == 1

    art = vc_store.create_artifact(
        job_id=job_id,
        owner_user_id=user_id,
        reference_id=ref.reference_id,
        reference_sha256=ref.sha256,
        text="ជំរាបសួរពុកម៉ែបងប្អូនទាំងអស់គ្នា",
        text_sha256="text_hash_1",
        request_digest="req_digest_1",
    )
    vc_store.update_artifact_completed(
        artifact_id=art.artifact_id,
        wav_path="/path/master.wav",
        wav_sha256="wav_hash_master_1",
        duration_seconds=15.0,
    )

    approval = vc_store.approve_audio(
        job_id=job_id,
        artifact_id=art.artifact_id,
        request_digest="req_digest_1",
        wav_sha256="wav_hash_master_1",
        owner_user_id=user_id,
    )

    active = vc_store.get_active_approval(job_id)
    assert active is not None
    assert active.approval_id == approval.approval_id
    assert active.artifact_id == art.artifact_id
    assert active.wav_sha256 == "wav_hash_master_1"
    assert active.invalidated_at is None

def test_invalidate_earlier_approval_on_new_artifact(temp_db):
    job_store = JobStorage(temp_db)
    vc_store = VoiceCloneStorage(temp_db)
    user_id = 888

    job = job_store.create_job(user_id=user_id, chat_id=124, feature=JobFeature.TALKING_PHOTO.value)
    job_id = job.job_id

    ref = vc_store.save_reference(
        owner_user_id=user_id,
        job_id=job_id,
        wav_path="/path/ref.wav",
        sha256="ref_sha256_abc",
        duration_seconds=10.0,
    )

    art_a = vc_store.create_artifact(
        job_id=job_id,
        owner_user_id=user_id,
        reference_id=ref.reference_id,
        reference_sha256=ref.sha256,
        text="អត្ថបទទី១",
        text_sha256="sha_txt_1",
        request_digest="req_digest_a",
        artifact_id="art_a",
    )
    vc_store.update_artifact_completed(art_a.artifact_id, "/wav_a.wav", "sha_wav_a", 10.0)
    approval_a = vc_store.approve_audio(job_id, "art_a", "req_digest_a", "sha_wav_a", user_id)

    # Approve artifact B
    art_b = vc_store.create_artifact(
        job_id=job_id,
        owner_user_id=user_id,
        reference_id=ref.reference_id,
        reference_sha256=ref.sha256,
        text="អត្ថបទកែប្រែថ្មី",
        text_sha256="sha_txt_2",
        request_digest="req_digest_b",
        artifact_id="art_b",
    )
    vc_store.update_artifact_completed(art_b.artifact_id, "/wav_b.wav", "sha_wav_b", 12.0)
    approval_b = vc_store.approve_audio(job_id, "art_b", "req_digest_b", "sha_wav_b", user_id)

    # Active approval must be B, and A must be invalidated
    active = vc_store.get_active_approval(job_id)
    assert active.approval_id == approval_b.approval_id
    assert active.artifact_id == "art_b"

    # Query directly to ensure approval_a is marked invalidated
    conn = temp_db.get_connection()
    row_a = conn.execute("SELECT * FROM audio_approvals WHERE approval_id = ?", (approval_a.approval_id,)).fetchone()
    assert row_a["invalidated_at"] is not None

def test_explicit_invalidation_on_text_or_reference_change(temp_db):
    job_store = JobStorage(temp_db)
    vc_store = VoiceCloneStorage(temp_db)
    user_id = 777

    job = job_store.create_job(user_id=user_id, chat_id=125, feature=JobFeature.TALKING_PHOTO.value)
    job_id = job.job_id

    ref = vc_store.save_reference(
        owner_user_id=user_id,
        job_id=job_id,
        wav_path="/path/ref.wav",
        sha256="ref_sha256_abc",
        duration_seconds=8.0,
    )

    art = vc_store.create_artifact(
        job_id=job_id,
        owner_user_id=user_id,
        reference_id=ref.reference_id,
        reference_sha256=ref.sha256,
        text="សួស្តី",
        text_sha256="sha_txt",
        request_digest="req_digest",
        artifact_id="art_to_invalidate",
    )
    vc_store.update_artifact_completed(art.artifact_id, "/wav.wav", "sha_wav", 5.0)
    vc_store.approve_audio(job_id, art.artifact_id, "req_digest", "sha_wav", user_id)

    assert vc_store.get_active_approval(job_id) is not None

    # When user changes text or reference voice, approvals are invalidated
    vc_store.invalidate_approvals(job_id)
    assert vc_store.get_active_approval(job_id) is None

def test_talking_photo_revision_persists_audio_source_and_clone_id(temp_db):
    job_store = JobStorage(temp_db)
    tp_store = TalkingPhotoStorage(temp_db)

    job = job_store.create_job(user_id=101, chat_id=102, feature=JobFeature.TALKING_PHOTO.value)
    job_id = job.job_id

    st = TalkingPhotoSettings()
    rev = tp_store.create_revision(
        job_id=job_id,
        image_path="/path/portrait.jpg",
        original_voice_path="/path/master_audio.wav",
        settings=st,
        input_digest="input_hash",
        audio_source="cloned_voice",
        approved_audio_artifact_id="art_cloned_001",
        audio_approval_id="appr_001",
    )

    assert rev.audio_source == "cloned_voice"
    assert rev.approved_audio_artifact_id == "art_cloned_001"
    assert rev.audio_approval_id == "appr_001"

    fetched = tp_store.get_revision(job_id, rev.revision_id)
    assert fetched.audio_source == "cloned_voice"
    assert fetched.approved_audio_artifact_id == "art_cloned_001"
    assert fetched.audio_approval_id == "appr_001"
