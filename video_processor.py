"""
Video processing pipeline with robust subprocess timeouts, process tree termination,
error classification, and result reporting.
Never returns input path as output; raises explicit errors or returns result.
"""

import os
import logging
import threading
from typing import Optional, Callable, Dict, Any, List
from pathlib import Path

from utils import get_ffmpeg_path
from transcriber import AudioTranscriber
from subtitle_generator import generate_animated_ass
from process_runner import ProcessRunner, DEFAULT_FFMPEG_TIMEOUT
from errors import (
    CorruptMediaError,
    NoAudioStreamError,
    NoSpeechDetectedError,
    ProcessTimeoutError,
    JobCancelledError,
    ProcessingResult
)
from media_validator import validate_video_with_audio

logger = logging.getLogger(__name__)


class VideoProcessor:
    def __init__(self, whisper_model: str = "small"):
        self.ffmpeg_path = get_ffmpeg_path()
        self.transcriber = AudioTranscriber(model_size=whisper_model)

        # Check Gemini API Key
        self.gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
        self.gemini_transcriber = None
        if self.gemini_key:
            try:
                from gemini_transcriber import GeminiTranscriber
                self.gemini_transcriber = GeminiTranscriber(api_key=self.gemini_key)
                logger.info("Google Gemini Transcriber connected for Khmer speech-to-text.")
            except Exception as e:
                logger.warning(f"Could not initialize GeminiTranscriber: {e}")

    def process_video(
        self,
        input_video_path: str,
        output_video_path: str,
        language: Optional[str] = None,
        font_key: Optional[str] = None,
        timeout: Optional[float] = None,
        on_pid_assigned: Optional[Callable[[int], None]] = None,
        cancel_event: Optional[threading.Event] = None,
        job_id: Optional[str] = None
    ) -> str:
        """
        Processes video:
        1. Validates media and audio stream presence.
        2. Transcribes speech to text with timestamps.
        3. Creates animated subtitles.
        4. Burns subtitles using FFmpeg with real timeouts and cancellation support.

        Never returns input_video_path on failure or missing speech.
        Raises specific BotProcessingError subclasses.
        """
        # Validate media and check for corrupt media or missing audio
        media_info = validate_video_with_audio(input_video_path)

        base_dir = os.path.dirname(input_video_path)
        base_name = os.path.splitext(os.path.basename(input_video_path))[0]
        ass_path = os.path.join(base_dir, f"{base_name}_captions.ass")

        # Step 1: AI Transcribe
        words = []
        if language == "km" and self.gemini_transcriber:
            logger.info(f"[Job {job_id or 'sys'}] Using Gemini Flash for Khmer transcription...")
            try:
                words = self.gemini_transcriber.transcribe(
                    input_video_path,
                    language="km",
                    cancel_event=cancel_event,
                    job_id=job_id
                )
            except Exception as e:
                logger.error(f"[Job {job_id or 'sys'}] Gemini error: {e}. Switching to Whisper...")

        if not words:
            logger.info(f"[Job {job_id or 'sys'}] Transcribing with Whisper...")
            words = self.transcriber.transcribe(input_video_path, language=language)

        if not words:
            logger.warning(f"[Job {job_id or 'sys'}] No spoken words detected in video.")
            raise NoSpeechDetectedError(
                "No spoken words detected in video.",
                job_id=job_id
            )

        # Step 2: Generate Animated Subtitle (.ass)
        logger.info(f"[Job {job_id or 'sys'}] Generating Animated Subtitles (Font: {font_key or 'default'})...")
        generate_animated_ass(words, ass_path, language=language, font_key=font_key)

        # Step 3: Burn Subtitles with FFmpeg
        logger.info(f"[Job {job_id or 'sys'}] FFmpeg rendering subtitles...")
        escaped_ass_path = ass_path.replace("\\", "/").replace(":", r"\:")
        vf_filter = f"ass='{escaped_ass_path}'"

        cmd = [
            self.ffmpeg_path,
            "-y",
            "-i", input_video_path,
            "-vf", vf_filter,
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "22",
            "-c:a", "aac",
            "-b:a", "128k",
            output_video_path
        ]

        ffmpeg_timeout = timeout or DEFAULT_FFMPEG_TIMEOUT
        proc_out = ProcessRunner.run(
            cmd,
            timeout=ffmpeg_timeout,
            on_pid_assigned=on_pid_assigned,
            cancel_event=cancel_event,
            job_id=job_id
        )

        if proc_out.returncode != 0:
            logger.error(f"[Job {job_id or 'sys'}] FFmpeg render failed: {proc_out.stderr[-400:]}")
            raise RuntimeError(f"FFmpeg render failed with exit code {proc_out.returncode}")

        # Clean temporary .ass file
        if os.path.exists(ass_path):
            try:
                os.remove(ass_path)
            except Exception:
                pass

        if not os.path.exists(output_video_path) or os.path.getsize(output_video_path) == 0:
            raise RuntimeError(f"Output video was not created: {output_video_path}")

        logger.info(f"[Job {job_id or 'sys'}] Render completed successfully: {output_video_path}")
        return output_video_path
