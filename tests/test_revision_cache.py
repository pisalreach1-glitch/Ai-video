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

def test_revision_audio_carryover(temp_job_storage):
    """Ensure audio metadata can be carried over to new revisions while preview/final paths are cleared."""
    job = temp_job_storage.create_job(user_id=1, chat_id=1)
    r1 = temp_job_storage.create_revision(
        job.job_id, "Text 1", VoiceSettings(),
        audio_path="/tmp/audio1.mp3",
        audio_duration=5.0,
        subtitles_srt="/tmp/sub1.srt",
    )
    assert r1.audio_path == "/tmp/audio1.mp3"
    assert r1.audio_duration == 5.0
    assert r1.preview_path is None

    # Carry over to revision 2 with different subtitle color
    s2 = VoiceSettings(subtitle_color="yellow")
    r2 = temp_job_storage.create_revision(
        job.job_id, "Text 1", s2,
        audio_path=r1.audio_path,
        audio_duration=r1.audio_duration,
        subtitles_srt=r1.subtitles_srt,
    )
    assert r2.revision_id == 2
    assert r2.audio_path == "/tmp/audio1.mp3"
    assert r2.audio_duration == 5.0
    assert r2.preview_path is None

@pytest.mark.asyncio
async def test_verify_callback_job_stale_revision(temp_job_storage, monkeypatch):
    """Ensure verify_callback_job rejects callbacks referencing outdated revisions or disallowed states."""
    from app.handlers.common import verify_callback_job
    from app.domain.states import JobState

    job = temp_job_storage.create_job(user_id=123, chat_id=456)
    r1 = temp_job_storage.create_revision(job.job_id, "Text", VoiceSettings())
    r2 = temp_job_storage.create_revision(job.job_id, "Text", VoiceSettings())
    # Current revision is 2

    class DummyCall:
        from_user = type("User", (), {"id": 123})()
        message = type("Msg", (), {"chat": type("Chat", (), {"id": 456})()})()
        answered = False
        async def answer(self, text="", show_alert=False):
            self.answered = True

    # Monkeypatch global job_storage in common module
    import app.handlers.common
    monkeypatch.setattr(app.handlers.common, "job_storage", temp_job_storage)

    # 1. Matching revision passes
    call_ok = DummyCall()
    assert await verify_callback_job(call_ok, job.job_id, expected_rev=2) is True

    # 2. Stale revision (rev 1 when current is 2) is REJECTED
    call_stale = DummyCall()
    assert await verify_callback_job(call_stale, job.job_id, expected_rev=1) is False
    assert call_stale.answered is True

    # 3. Disallowed state (e.g. COMPLETED or RENDERING) is REJECTED
    temp_job_storage.set_job_status(job.job_id, JobState.COMPLETED)
    call_disallowed = DummyCall()
    assert await verify_callback_job(call_disallowed, job.job_id, expected_rev=2) is False
