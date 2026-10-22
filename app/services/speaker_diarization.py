"""Optional local Pyannote diarization adapter with graceful offline/manual fallbacks."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.config import config
from app.domain.speakers import SpeakerTurn

logger = logging.getLogger(__name__)


class DiarizationUnavailableError(RuntimeError):
    """Raised when pyannote.audio dependencies or HF access token are unavailable."""
    pass


def is_diarization_available() -> bool:
    """Checks whether local pyannote diarization dependencies and model config are present."""
    if not getattr(config, "enable_multi_speaker_dubbing", True):
        return False
    try:
        import torch  # noqa: F401
        import pyannote.audio  # noqa: F401
        return True
    except ImportError:
        return False


async def run_speaker_diarization(
    audio_wav_path: Path,
    hf_token: str | None = None,
    device: str = "cpu",
    model_name: str = "pyannote/speaker-diarization-community-1",
) -> list[SpeakerTurn]:
    """
    Runs speaker diarization on a 16kHz mono WAV audio file using pyannote-audio.
    Extracts anonymous turns (e.g. Speaker A, Speaker B).

    Raises:
        DiarizationUnavailableError: if pyannote dependencies, token, or weights are not available.
    """
    token = hf_token or getattr(config, "hf_token", "")
    if not is_diarization_available():
        raise DiarizationUnavailableError(
            "Local speaker diarization requires 'pyannote.audio' and PyTorch. "
            "Please install optional requirements in 'requirements-speakers.txt'."
        )

    import asyncio

    def _sync_diarize() -> list[SpeakerTurn]:
        import torch
        from pyannote.audio import Pipeline

        target_device = torch.device(device if torch.cuda.is_available() and device == "cuda" else "cpu")
        try:
            pipeline = Pipeline.from_pretrained(model_name, use_auth_token=token or None)
            if pipeline is None:
                raise DiarizationUnavailableError(
                    f"Could not load diarization model '{model_name}'. Check HF_TOKEN."
                )
            pipeline.to(target_device)
            diarization = pipeline(str(audio_wav_path))
        except Exception as e:
            logger.warning(f"Pyannote diarization execution failed: {e}")
            raise DiarizationUnavailableError(f"Diarization inference error: {e}") from e

        raw_turns: list[SpeakerTurn] = []
        speaker_map: dict[str, str] = {}
        speaker_counter = 1

        for turn, _, speaker in diarization.itertracks(yield_label=True):
            if speaker not in speaker_map:
                letter = chr(64 + speaker_counter) if speaker_counter <= 26 else f"S{speaker_counter}"
                speaker_map[speaker] = f"Speaker {letter}"
                speaker_counter += 1

            start_ms = max(0, int(round(turn.start * 1000)))
            end_ms = int(round(turn.end * 1000))
            if end_ms > start_ms:
                raw_turns.append(
                    SpeakerTurn(
                        speaker_id=speaker_map[speaker],
                        start_ms=start_ms,
                        end_ms=end_ms,
                    )
                )

        raw_turns.sort(key=lambda t: t.start_ms)
        return raw_turns

    return await asyncio.to_thread(_sync_diarize)
