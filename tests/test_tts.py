"""Test TTS narration and timing event extraction."""
import pytest
from pathlib import Path
from app.services.voices import get_available_voices
from app.services.tts import generate_narration, TTSTimingError

@pytest.mark.asyncio
async def test_khmer_voice_discovery():
    """Verify that Khmer voices are available and properly discovered."""
    voices = await get_available_voices()
    assert len(voices) >= 2
    voice_names = [v.get("ShortName") for v in voices]
    assert "km-KH-SreymomNeural" in voice_names
    assert "km-KH-PisethNeural" in voice_names

@pytest.mark.asyncio
async def test_tts_generation_live_khmer(tmp_path):
    """
    Test live Edge-TTS narration generation with Khmer text:
    - Generates decodable audio
    - Produces timing events with start <= end
    - Duration is positive
    """
    dest = tmp_path / "test_voice.mp3"
    text = "ជំរាបសួរ។ នេះជាការសាកល្បងសំឡេងអាន AI។"
    audio_path, duration, events = await generate_narration(
        text=text,
        voice="km-KH-SreymomNeural",
        rate="+0%",
        output_audio_path=dest,
    )

    assert audio_path.exists()
    assert audio_path.stat().st_size > 0
    assert duration > 0.0
    assert len(events) >= 1

    for ev in events:
        assert "start" in ev
        assert "end" in ev
        assert "text" in ev
        assert ev["start"] <= ev["end"]
        assert len(ev["text"]) > 0
