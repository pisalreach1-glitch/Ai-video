"""Unit tests for voice clone reference transcript handling and distinct target text."""
import pytest
from app.storage.database import Database
from app.storage.jobs import JobStorage
from app.features.voice_clone.storage import VoiceCloneStorage
from app.features.voice_clone.domain import CloneRequest
from app.domain.features import JobFeature

@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_ref_transcript.sqlite3"
    return Database(db_file)

def test_save_and_update_reference_transcript(temp_db):
    job_store = JobStorage(temp_db)
    vc_store = VoiceCloneStorage(temp_db)

    user_id = 1001
    job = job_store.create_job(user_id=user_id, chat_id=2001, feature=JobFeature.TALKING_PHOTO.value)

    ref = vc_store.save_reference(
        owner_user_id=user_id,
        job_id=job.job_id,
        wav_path="/path/to/ref.wav",
        sha256="ref_hash_abc",
        duration_seconds=8.0,
        reference_text="ជំរាបសួរ ខ្ញុំបាទឈ្មោះសុខ",
    )
    assert ref.reference_text == "ជំរាបសួរ ខ្ញុំបាទឈ្មោះសុខ"

    # User corrects the transcript
    vc_store.update_reference_text(ref.reference_id, "ជំរាបសួរ ខ្ញុំបាទឈ្មោះសុខ សប្បាយចិត្តណាស់")
    updated = vc_store.get_reference(ref.reference_id)
    assert updated is not None
    assert updated.reference_text == "ជំរាបសួរ ខ្ញុំបាទឈ្មោះសុខ សប្បាយចិត្តណាស់"

def test_distinct_reference_transcript_and_target_text(temp_db):
    job_store = JobStorage(temp_db)
    vc_store = VoiceCloneStorage(temp_db)

    user_id = 1002
    job = job_store.create_job(user_id=user_id, chat_id=2002, feature=JobFeature.TALKING_PHOTO.value)

    ref_text = "នេះជាសំឡេងគំរូដើមរបស់ខ្ញុំ"
    target_text = "នេះជាអត្ថបទថ្មីស្រឡាងដែលខ្ញុំចង់ឱ្យ AI អាន"

    ref = vc_store.save_reference(
        owner_user_id=user_id,
        job_id=job.job_id,
        wav_path="/path/to/ref.wav",
        sha256="ref_hash_xyz",
        duration_seconds=10.0,
        reference_text=ref_text,
    )

    art = vc_store.create_artifact(
        job_id=job.job_id,
        owner_user_id=user_id,
        reference_id=ref.reference_id,
        reference_sha256=ref.sha256,
        text=target_text,
        text_sha256="target_hash_xyz",
        request_digest="req_digest_123",
        reference_text=ref_text,
    )

    assert art.text == target_text
    assert art.reference_text == ref_text
    assert art.text != art.reference_text
