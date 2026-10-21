"""Audio extraction, transcription, and translation services using Gemini 2.5 Flash and Faster-Whisper."""
import os
import re
import asyncio
import logging
from pathlib import Path
from app.config import config
from app.jobs.processes import run_process
from app.storage.workspaces import workspace

logger = logging.getLogger(__name__)

async def extract_audio_from_video(video_path: Path, output_audio: Path) -> Path:
    """Extract audio from source video into 16kHz MP3 for AI transcription."""
    output_audio.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        config.ffmpeg_path,
        "-y",
        "-i", str(video_path),
        "-vn",
        "-acodec", "libmp3lame",
        "-ar", "16000",
        "-ac", "1",
        str(output_audio),
    ]
    res = await run_process(cmd, timeout=60.0)
    if res.returncode != 0 or not output_audio.exists():
        raise RuntimeError(f"Failed to extract audio from video: {res.stderr[:200]}")
    return output_audio

async def _translate_with_gemini_audio(audio_path: Path, video_duration: float, api_key: str) -> str:
    """Transcribe and translate audio directly with Gemini 2.5 Flash."""
    from google import genai
    from google.genai import types

    def _sync_call() -> str:
        client = genai.Client(api_key=api_key)
        uploaded = client.files.upload(file=str(audio_path))
        try:
            prompt = (
                "You are an expert video translator and professional voiceover scriptwriter.\n"
                "Listen carefully to the spoken dialogue, commentary, and narration in this audio.\n"
                "1. Accurately understand all speech, dialogue, and context.\n"
                "2. Translate and adapt all the spoken content into natural, fluent, engaging Khmer (ភាសាខ្មែរ) suitable for voiceover narration.\n"
                f"3. The original video is {video_duration:.1f} seconds long. Ensure the translated Khmer narration flows smoothly and matches this pacing.\n"
                "4. If there is NO speech or only background music/silence, output ONLY: NO_SPEECH_DETECTED\n"
                "5. Output ONLY the translated Khmer narration text. Do NOT include English, romanization, timestamps, speaker tags, or markdown explanations."
            )
            model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
            res = client.models.generate_content(
                model=model_name,
                contents=[uploaded, prompt],
                config=types.GenerateContentConfig(
                    temperature=0.2,
                )
            )
            return (res.text or "").strip()
        finally:
            try:
                client.files.delete(name=uploaded.name)
            except Exception:
                pass

    raw_result = await asyncio.to_thread(_sync_call)
    cleaned = re.sub(r"^```(?:txt|text|khmer)?\s*", "", raw_result, flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.MULTILINE).strip()
    return cleaned

async def _translate_with_whisper_fallback(audio_path: Path, video_duration: float, api_key: str | None) -> str:
    """Fallback transcription with local Faster-Whisper and text translation with Gemini."""
    def _sync_whisper():
        from faster_whisper import WhisperModel
        model = WhisperModel(os.getenv("WHISPER_MODEL", "base"), device="cpu", compute_type="int8")
        segments, info = model.transcribe(str(audio_path), beam_size=5)
        text = " ".join(s.text for s in segments).strip()
        return text, getattr(info, "language", "en")

    transcript, det_lang = await asyncio.to_thread(_sync_whisper)
    if not transcript:
        return "NO_SPEECH_DETECTED"

    if det_lang == "km":
        return transcript

    if api_key:
        from google import genai
        def _sync_translate() -> str:
            client = genai.Client(api_key=api_key)
            prompt = (
                f"Translate this video transcript to natural, fluent Khmer (ភាសាខ្មែរ) for video voiceover.\n"
                f"Video duration is {video_duration:.1f} seconds.\n"
                f"Output ONLY the Khmer translation text without markdown or commentary:\n\n{transcript}"
            )
            res = client.models.generate_content(
                model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
                contents=prompt,
            )
            return (res.text or "").strip()

        khmer_text = await asyncio.to_thread(_sync_translate)
        khmer_text = re.sub(r"^```(?:txt|text|khmer)?\s*", "", khmer_text, flags=re.MULTILINE)
        khmer_text = re.sub(r"\s*```$", "", khmer_text, flags=re.MULTILINE).strip()
        return khmer_text

    return transcript

async def translate_video_to_khmer(
    video_path: Path,
    video_duration: float,
    job_id: str,
) -> str:
    """
    Transcribe and translate video audio into natural, fluent Khmer narration text.
    Primary: Google Gemini 2.5 Flash (via google.genai audio upload).
    Fallback: Local Faster-Whisper + Gemini text translation.
    """
    audio_path = workspace.get_input_dir(job_id) / "extracted_audio.mp3"
    await extract_audio_from_video(video_path, audio_path)

    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key:
        try:
            res = await _translate_with_gemini_audio(audio_path, video_duration, gemini_key)
            if res and res != "NO_SPEECH_DETECTED":
                return res
            if res == "NO_SPEECH_DETECTED":
                return "NO_SPEECH_DETECTED"
        except Exception as e:
            logger.warning(f"[Job {job_id}] Gemini direct audio translation failed: {e}. Trying Whisper fallback...")

    # Fallback to local Faster-Whisper transcription + Gemini text translation
    try:
        return await _translate_with_whisper_fallback(audio_path, video_duration, gemini_key)
    finally:
        # Clean up temporary extracted audio file
        audio_path.unlink(missing_ok=True)
