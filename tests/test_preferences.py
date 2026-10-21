"""Test user preferences saving, restoring, and job snapshot independence."""
import pytest
from app.domain.models import VoiceSettings

def test_preferences_save_and_retrieve(temp_preferences):
    """User preferences can be saved and retrieved accurately."""
    user_id = 777
    prefs = VoiceSettings(
        voice="km-KH-PisethNeural",
        speed="+15%",
        subtitles_enabled=False,
        subtitle_color="yellow",
        subtitle_position="middle",
        source_audio_mode="low_mix",
        aspect_ratio="9:16",
        framing_mode="fill",
    )
    temp_preferences.save_preferences(user_id, prefs)

    retrieved = temp_preferences.get_preferences(user_id)
    assert retrieved.voice == "km-KH-PisethNeural"
    assert retrieved.speed == "+15%"
    assert retrieved.subtitles_enabled is False
    assert retrieved.subtitle_color == "yellow"
    assert retrieved.subtitle_position == "middle"
    assert retrieved.source_audio_mode == "low_mix"
    assert retrieved.aspect_ratio == "9:16"
    assert retrieved.framing_mode == "fill"

def test_preferences_multi_user_isolation(temp_preferences):
    """User preferences remain strictly isolated between different users."""
    u1, u2 = 1001, 2002
    temp_preferences.save_preferences(u1, VoiceSettings(voice="km-KH-PisethNeural"))
    temp_preferences.save_preferences(u2, VoiceSettings(voice="km-KH-SreymomNeural"))

    assert temp_preferences.get_preferences(u1).voice == "km-KH-PisethNeural"
    assert temp_preferences.get_preferences(u2).voice == "km-KH-SreymomNeural"

def test_preferences_restore_defaults(temp_preferences):
    """Restoring preferences resets user defaults to system defaults."""
    user_id = 888
    temp_preferences.save_preferences(user_id, VoiceSettings(voice="km-KH-PisethNeural", speed="+15%"))
    assert temp_preferences.get_preferences(user_id).voice == "km-KH-PisethNeural"

    restored = temp_preferences.restore_preferences(user_id)
    assert restored.voice == "km-KH-SreymomNeural"
    assert restored.speed == "+0%"
    assert temp_preferences.get_preferences(user_id).voice == "km-KH-SreymomNeural"

def test_job_settings_snapshot_independence(temp_job_storage, temp_preferences):
    """Job revision snapshot remains independent of user's saved preferences."""
    user_id = 999
    chat_id = 999

    temp_preferences.save_preferences(user_id, VoiceSettings(speed="+0%"))
    job = temp_job_storage.create_job(user_id=user_id, chat_id=chat_id)
    rev = temp_job_storage.create_revision(job.job_id, "Test text", temp_preferences.get_preferences(user_id))

    # Mutate revision setting
    rev.settings.speed = "+15%"
    temp_job_storage.update_revision(job.job_id, rev.revision_id, settings=rev.settings)

    # Saved preferences must remain untouched at +0%
    assert temp_preferences.get_preferences(user_id).speed == "+0%"
    assert temp_job_storage.get_revision(job.job_id, rev.revision_id).settings.speed == "+15%"
