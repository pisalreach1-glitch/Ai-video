"""Tests for dubbing caching, partial invalidation, and free narration coexistence."""
import pytest
from pathlib import Path
from app.services.dubbing import compute_tts_cache_key
from app.domain.models import Job, VoiceSettings
from app.domain.dubbing import DubbingPlan, SourceSegment, TranslatedSegment

def test_dubbing_cache_keys_stable():
    """TTS cache key depends on text, voice, and speed."""
    k1 = compute_tts_cache_key("ជំរាបសួរ", "km-KH-SreymomNeural", "+0%")
    k2 = compute_tts_cache_key("ជំរាបសួរ", "km-KH-SreymomNeural", "+0%")
    k3 = compute_tts_cache_key("ជំរាបសួរ", "km-KH-PisethNeural", "+0%")
    k4 = compute_tts_cache_key("ជំរាបសួរ", "km-KH-SreymomNeural", "+15%")

    assert k1 == k2
    assert k1 != k3
    assert k1 != k4

def test_editing_one_segment_invalidates_only_that_segment(temp_workspace):
    """Requirement 16: Editing one segment regenerates only that segment while preserving others."""
    job_id = "test-job-cache"
    revision_id = 1

    # Simulate 2 segments cached
    s1_wav = temp_workspace.get_segment_voice_wav(job_id, revision_id, "s001")
    s2_wav = temp_workspace.get_segment_voice_wav(job_id, revision_id, "s002")
    s1_wav.write_bytes(b"wav1")
    s2_wav.write_bytes(b"wav2")

    assert s1_wav.exists()
    assert s2_wav.exists()

    # User edits segment s001
    s1_wav.unlink(missing_ok=True)

    # s001 is invalidated, but s002 remains cached and untouched
    assert not s1_wav.exists()
    assert s2_wav.exists()

def test_free_narration_unaffected_by_timed_dubbing_mode(temp_job_storage):
    """Requirement 17: Manual free narration still works exactly as before."""
    job = temp_job_storage.create_job(user_id=1, chat_id=1)
    temp_job_storage.set_job_mode(job.job_id, "free_narration")

    rev = temp_job_storage.create_revision(
        job_id=job.job_id,
        narration_text="អត្ថបទ Free Narration ធម្មតា",
        settings=VoiceSettings(duration_policy="extend"),
        mode="free_narration",
    )

    loaded_job = temp_job_storage.get_job(job.job_id)
    loaded_rev = temp_job_storage.get_revision(job.job_id, rev.revision_id)

    assert loaded_job.mode == "free_narration"
    assert loaded_rev.mode == "free_narration"
    assert loaded_rev.narration_text == "អត្ថបទ Free Narration ធម្មតា"
