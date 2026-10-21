"""Voice discovery, validation, and sample caching."""
import asyncio
import logging
from pathlib import Path
import edge_tts
from app.storage.workspaces import workspace

logger = logging.getLogger(__name__)

# Fallback known km-KH voices in Edge TTS
KNOWN_KM_VOICES = [
    "km-KH-SreymomNeural",
    "km-KH-PisethNeural",
]

_CACHED_VOICES: list[dict] | None = None

async def get_available_voices() -> list[dict]:
    """Discover available Khmer voices from Edge-TTS or return validated defaults."""
    global _CACHED_VOICES
    if _CACHED_VOICES is not None:
        return _CACHED_VOICES

    try:
        all_voices = await edge_tts.list_voices()
        km_voices = [
            v for v in all_voices
            if "km-KH" in v.get("Locale", "") or "Khmer" in v.get("FriendlyName", "")
        ]
        if km_voices:
            _CACHED_VOICES = km_voices
            return _CACHED_VOICES
    except Exception as e:
        logger.warning(f"Could not fetch voices list from Edge-TTS online ({e}), using verified fallback.")

    _CACHED_VOICES = [
        {"ShortName": "km-KH-SreymomNeural", "Gender": "Female", "Locale": "km-KH"},
        {"ShortName": "km-KH-PisethNeural", "Gender": "Male", "Locale": "km-KH"},
    ]
    return _CACHED_VOICES

async def get_or_create_voice_sample(voice_name: str) -> Path:
    """
    Generate and cache a short Khmer sample audio file for a given voice.
    Returns path to the cached MP3 file.
    """
    sample_path = workspace.get_voice_sample_path(voice_name)
    if sample_path.exists() and sample_path.stat().st_size > 0:
        return sample_path

    sample_text = "ជំរាបសួរ! នេះជាគំរូសំឡេងអាន AI សម្រាប់វីដេអូរបស់អ្នក។"
    comm = edge_tts.Communicate(text=sample_text, voice=voice_name)
    await comm.save(str(sample_path))
    return sample_path
