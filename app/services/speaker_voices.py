"""Per-speaker TTS preset resolution and keyed cache utilities."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Set
from typing import Any

from app.domain.speakers import SpeakerAssignment, VoiceChoice


class VoiceSelectionRequired(ValueError):
    """Raised when an utterance cannot be synthesized due to a voice selection issue."""
    pass


def resolve_voice(
    assignment: SpeakerAssignment,
    voice_map: Mapping[str, VoiceChoice],
    available_voice_ids: Set[str],
    *,
    require_confirmed: bool = True,
) -> VoiceChoice:
    """
    Resolves the assigned TTS VoiceChoice for a speaker assignment.

    Raises:
        VoiceSelectionRequired("unknown_speaker"): if assignment has no speaker_id
        VoiceSelectionRequired("missing_voice"): if no choice configured or not confirmed when required
        VoiceSelectionRequired("invalid_voice"): if voice_id is not in available_voice_ids
    """
    if not assignment.speaker_id:
        raise VoiceSelectionRequired("unknown_speaker")

    choice = voice_map.get(assignment.speaker_id)
    if choice is None or (require_confirmed and not choice.confirmed):
        raise VoiceSelectionRequired("missing_voice")

    if choice.voice_id not in available_voice_ids:
        raise VoiceSelectionRequired("invalid_voice")

    return choice


def speaker_tts_cache_key(
    text: str,
    choice: VoiceChoice,
    engine_identity: str = "edge-tts",
) -> str:
    """
    Computes an immutable SHA-256 digest for cached per-speaker TTS synthesis.
    """
    payload = {
        "schema": 1,
        "engine": engine_identity,
        "text": text.strip(),
        "voice": choice.voice_id,
        "rate": choice.rate,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
