"""Tests for per-speaker voice resolution, cache keys, and invalidation rules."""
import pytest
from app.domain.speakers import SpeakerAssignment, VoiceChoice
from app.services.speaker_voices import (
    resolve_voice,
    speaker_tts_cache_key,
    VoiceSelectionRequired,
)


def test_two_speakers_same_preset_retain_separate_identities():
    """Criteria 2: Two speakers using the same preset retain separate identities/assignments."""
    asgn_a = SpeakerAssignment(segment_id="s001", speaker_id="Speaker A", evidence_key="ev1")
    asgn_b = SpeakerAssignment(segment_id="s002", speaker_id="Speaker B", evidence_key="ev2")

    voice_map = {
        "Speaker A": VoiceChoice(voice_id="km-KH-SreymomNeural", confirmed=True),
        "Speaker B": VoiceChoice(voice_id="km-KH-SreymomNeural", confirmed=True),
    }
    available = {"km-KH-SreymomNeural", "km-KH-PisethNeural"}

    choice_a = resolve_voice(asgn_a, voice_map, available)
    choice_b = resolve_voice(asgn_b, voice_map, available)

    assert choice_a.voice_id == choice_b.voice_id
    assert asgn_a.speaker_id != asgn_b.speaker_id


def test_pending_voice_trial_vs_confirmed_export():
    """Criteria 3: Pending voice allowed for trial audition, but blocks when confirmation required."""
    asgn = SpeakerAssignment(segment_id="s001", speaker_id="Speaker A", evidence_key="ev1")
    voice_map = {
        "Speaker A": VoiceChoice(voice_id="km-KH-PisethNeural", confirmed=False),
    }
    available = {"km-KH-SreymomNeural", "km-KH-PisethNeural"}

    # Allowed for audition trial
    trial_choice = resolve_voice(asgn, voice_map, available, require_confirmed=False)
    assert trial_choice.voice_id == "km-KH-PisethNeural"

    # Blocked for full synthesis / final validation
    with pytest.raises(VoiceSelectionRequired) as exc:
        resolve_voice(asgn, voice_map, available, require_confirmed=True)
    assert "missing_voice" in str(exc.value)


def test_missing_and_invalid_voice_handling():
    asgn_unknown = SpeakerAssignment(segment_id="s001", speaker_id=None, evidence_key="ev1")
    asgn_valid = SpeakerAssignment(segment_id="s002", speaker_id="Speaker A", evidence_key="ev2")
    available = {"km-KH-SreymomNeural"}

    with pytest.raises(VoiceSelectionRequired) as exc1:
        resolve_voice(asgn_unknown, {}, available)
    assert "unknown_speaker" in str(exc1.value)

    voice_map = {"Speaker A": VoiceChoice(voice_id="invalid-voice", confirmed=True)}
    with pytest.raises(VoiceSelectionRequired) as exc2:
        resolve_voice(asgn_valid, voice_map, available)
    assert "invalid_voice" in str(exc2.value)


def test_cache_key_invalidation_when_preset_changes():
    """Criteria 13: Changing A's preset changes cache key; B's key remains identical."""
    choice_a1 = VoiceChoice(voice_id="km-KH-SreymomNeural", rate="+0%")
    choice_a2 = VoiceChoice(voice_id="km-KH-PisethNeural", rate="+0%")
    choice_b = VoiceChoice(voice_id="km-KH-SreymomNeural", rate="+0%")

    text_a = "ជម្រាបសួរ"
    text_b = "សុខសប្បាយជាទេ"

    key_a1 = speaker_tts_cache_key(text_a, choice_a1)
    key_a2 = speaker_tts_cache_key(text_a, choice_a2)
    key_b1 = speaker_tts_cache_key(text_b, choice_b)
    key_b2 = speaker_tts_cache_key(text_b, choice_b)

    assert key_a1 != key_a2
    assert key_b1 == key_b2
