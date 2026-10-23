"""Tests for cross-feature isolation between Video Voiceover and Talking Photo."""
import pytest
from app.domain.features import JobFeature
from app.domain.states import JobState
from app.storage.database import Database
from app.storage.jobs import JobStorage
from app.storage.sessions import SessionStorage
from app.features.talking_photo.states import TalkingPhotoSteps
from app.features.talking_photo.storage import TalkingPhotoStorage, TalkingPhotoSettings

@pytest.fixture
def temp_storage(tmp_path):
    db = Database(tmp_path / "test_iso.sqlite3")
    return JobStorage(db), SessionStorage(db), TalkingPhotoStorage(db)

def test_feature_isolation_between_video_and_photo_jobs(temp_storage):
    job_store, session_store, tp_store = temp_storage
    user_id = 500
    chat_id = 600

    # User starts a video voiceover job
    video_job = job_store.create_job(user_id=user_id, chat_id=chat_id, feature=JobFeature.VIDEO_VOICEOVER.value)
    session_store.set_session(user_id, chat_id, active_job_id=video_job.job_id, wizard_state="awaiting_video_source")

    assert video_job.feature == JobFeature.VIDEO_VOICEOVER.value

    # User now clicks to create a Talking Photo job
    photo_job = job_store.create_job(user_id=user_id, chat_id=chat_id, feature=JobFeature.TALKING_PHOTO.value)
    session_store.set_session(user_id, chat_id, active_job_id=photo_job.job_id, wizard_state="waiting_photo")

    assert photo_job.feature == JobFeature.TALKING_PHOTO.value
    # Previous video job is still safe in database
    refetched_video = job_store.get_job(video_job.job_id)
    assert refetched_video is not None
    assert refetched_video.feature == JobFeature.VIDEO_VOICEOVER.value
    assert refetched_video.status == JobState.AWAITING_SOURCE

    # Both jobs exist in active jobs list for this user
    active_jobs = job_store.get_user_active_jobs(user_id, chat_id)
    assert len(active_jobs) == 2
    features = {j.feature for j in active_jobs}
    assert JobFeature.VIDEO_VOICEOVER.value in features
    assert JobFeature.TALKING_PHOTO.value in features

    # Filtering by feature returns only the corresponding job
    video_only = job_store.get_user_active_job(user_id, chat_id, feature=JobFeature.VIDEO_VOICEOVER.value)
    assert video_only.job_id == video_job.job_id

    photo_only = job_store.get_user_active_job(user_id, chat_id, feature=JobFeature.TALKING_PHOTO.value)
    assert photo_only.job_id == photo_job.job_id

def test_photo_revisions_isolated_from_video_revisions(temp_storage):
    job_store, session_store, tp_store = temp_storage
    user_id = 700
    chat_id = 800

    photo_job = job_store.create_job(user_id=user_id, chat_id=chat_id, feature=JobFeature.TALKING_PHOTO.value)
    st = TalkingPhotoSettings(face_size=512)
    tp_rev = tp_store.create_revision(
        job_id=photo_job.job_id,
        image_path="/path/photo.png",
        original_voice_path="/path/voice.ogg",
        settings=st,
    )

    # Video voiceover revision query for this job should be empty
    assert job_store.get_revision(photo_job.job_id, 1) is None
    # Talking photo revision exists
    assert tp_store.get_revision(photo_job.job_id, tp_rev.revision_id) is not None
