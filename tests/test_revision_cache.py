"""Test revision cache invalidation and reuse rules."""
import pytest
from app.domain.models import VoiceSettings

def test_tts_cache_invalidation_on_text_voice_speed():
    """Text, voice, or speed changes must invalidate the TTS cache key."""
    s1 = VoiceSettings(voice="km-KH-SreymomNeural", speed="+0%")
    s2 = VoiceSettings(voice="km-KH-PisethNeural", speed="+0%")
    s3 = VoiceSettings(voice="km-KH-SreymomNeural", speed="+15%")

    text_a = "ជំរាបសួរ"
    text_b = "ជំរាបសួរ អ្នកទាំងអស់គ្នា"

    # Base key
    k1 = s1.tts_key(text_a)

    # Different voice
    assert s2.tts_key(text_a) != k1

    # Different speed
    assert s3.tts_key(text_a) != k1

    # Different text
    assert s1.tts_key(text_b) != k1

def test_tts_cache_preserved_on_subtitle_and_framing():
    """Changes to subtitle color/position or framing must preserve the TTS cache key."""
    s1 = VoiceSettings(subtitle_color="white", subtitle_position="bottom", aspect_ratio="original")
    s2 = VoiceSettings(subtitle_color="yellow", subtitle_position="middle", aspect_ratio="9:16")

    text = "អត្ថបទដដែល"
    # TTS audio can be reused
    assert s1.tts_key(text) == s2.tts_key(text)

    # But overall render key must differ
    assert s1.render_key(text) != s2.render_key(text)

def test_revision_id_incrementing(temp_job_storage):
    """Each revision created for a job increments revision_id."""
    job = temp_job_storage.create_job(user_id=1, chat_id=1)

    r1 = temp_job_storage.create_revision(job.job_id, "Text 1", VoiceSettings())
    assert r1.revision_id == 1

    r2 = temp_job_storage.create_revision(job.job_id, "Text 2", VoiceSettings())
    assert r2.revision_id == 2

    # Job current_revision_id is updated to latest
    updated_job = temp_job_storage.get_job(job.job_id)
    assert updated_job.current_revision_id == 2
