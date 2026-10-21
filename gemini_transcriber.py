"""
Google Gemini Transcriber for high-accuracy Speech-to-Text and Timestamp Extraction.
Configured with:
- Strict HTTP/provider timeouts (no indefinite hangs).
- Bounded fallback (no unlimited requests running while timed-out requests linger).
- Explicit error handling for Quota, Network, Corrupt Media, and Audio stream errors.
- Timecode parsing using timecode_utils.
"""

import os
import re
import json
import logging
import threading
from typing import List, Dict, Optional, Tuple
from google import genai
from google.genai import types

import utils
from timecode_utils import parse_timecode
from process_runner import ProcessRunner, DEFAULT_FFMPEG_TIMEOUT
from errors import (
    QuotaExceededError,
    NetworkError,
    CorruptMediaError,
    NoAudioStreamError,
    NoSpeechDetectedError,
    JobCancelledError
)

logger = logging.getLogger(__name__)

GEMINI_REQUEST_TIMEOUT = float(os.getenv("GEMINI_REQUEST_TIMEOUT", "60.0"))


def parse_srt_or_arrow_transcript(raw_text: str, max_dur: float = 3600.0) -> Tuple[str, str, List[Dict]]:
    """
    Parses standard SRT / Timestamp Arrow format (00:00.000 --> 00:02.500).
    Uses strict timecode parsing (legacy syntax disabled by default).
    """
    hook_title = ""
    detected_lang = "km"
    segments: List[Dict] = []

    lines = raw_text.strip().splitlines()
    clean_lines = []
    for l in lines:
        l_str = l.strip()
        if not l_str:
            continue
        hook_match = re.match(r"^HOOK\s*:\s*(.*)$", l_str, re.IGNORECASE)
        lang_match = re.match(r"^LANG\s*:\s*(.*)$", l_str, re.IGNORECASE)
        if hook_match:
            hook_title = hook_match.group(1).strip()
            continue
        if lang_match:
            detected_lang = lang_match.group(1).strip().lower()
            continue
        clean_lines.append(l_str)

    time_arrow_pattern = re.compile(
        r"(?:\[)?(\d{1,2}:\d{2}(?::\d{2})?(?:[,\.]\d{1,3})?)\s*(?:-->|->|—>|–>|to)\s*(\d{1,2}:\d{2}(?::\d{2})?(?:[,\.]\d{1,3})?)(?:\])?(?:\s*[:\|]\s*(.*))?",
        re.IGNORECASE
    )

    i = 0
    while i < len(clean_lines):
        line = clean_lines[i]

        # Skip SRT line numbers (1, 2, 3...)
        if re.match(r"^\d+$", line):
            i += 1
            if i < len(clean_lines):
                line = clean_lines[i]
            else:
                break

        m = time_arrow_pattern.search(line)
        if m:
            st_str, et_str, inline_text = m.groups()
            try:
                st = parse_timecode(st_str, allow_legacy=False, max_dur=max_dur)
                et = parse_timecode(et_str, allow_legacy=False, max_dur=max_dur)
            except Exception:
                try:
                    # Fallback to legacy parser if standard failed
                    st = parse_timecode(st_str, allow_legacy=True, max_dur=max_dur)
                    et = parse_timecode(et_str, allow_legacy=True, max_dur=max_dur)
                except Exception:
                    i += 1
                    continue

            text = ""
            if inline_text and inline_text.strip():
                text = inline_text.strip()
            else:
                i += 1
                text_lines = []
                while i < len(clean_lines) and not time_arrow_pattern.search(clean_lines[i]) and not re.match(r"^\d+$", clean_lines[i]):
                    text_lines.append(clean_lines[i])
                    i += 1
                text = " ".join(text_lines).strip()
                i -= 1

            if text and et > st:
                sfx = None
                sfx_m = re.search(r'\[sfx:(\w+)\]', text, re.IGNORECASE)
                if sfx_m:
                    sfx = sfx_m.group(1).lower()
                    text = re.sub(r'\[sfx:\w+\]', '', text).strip()

                segments.append({
                    "word": text,
                    "start": st,
                    "end": et,
                    "sfx": sfx
                })
        i += 1

    return hook_title, detected_lang, segments


class GeminiTranscriber:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or ""
        self.client = None
        if self.api_key:
            try:
                self.client = genai.Client(
                    api_key=self.api_key,
                    http_options=types.HttpOptions(timeout=GEMINI_REQUEST_TIMEOUT)
                )
            except Exception:
                try:
                    self.client = genai.Client(api_key=self.api_key)
                except Exception as e:
                    logger.warning(f"Could not initialize genai.Client: {e}")

        self.ffmpeg_path = utils.get_ffmpeg_path()
        self.hook_title = ""
        self.detected_language = "km"

    def extract_audio(
        self,
        video_path: str,
        output_audio_path: str,
        cancel_event: Optional[threading.Event] = None,
        job_id: Optional[str] = None
    ) -> str:
        """Extracts lightweight MP3 audio track from video."""
        cmd = [
            self.ffmpeg_path,
            "-y",
            "-i", video_path,
            "-vn",
            "-acodec", "libmp3lame",
            "-ab", "64k",
            "-ar", "16000",
            output_audio_path
        ]
        try:
            proc_out = ProcessRunner.run(
                cmd,
                timeout=DEFAULT_FFMPEG_TIMEOUT,
                cancel_event=cancel_event,
                job_id=job_id
            )
            if proc_out.returncode != 0:
                err_msg = proc_out.stderr
                if "moov atom not found" in err_msg or "Invalid data found" in err_msg:
                    raise CorruptMediaError("Incomplete or corrupt video (moov atom missing).", job_id=job_id)
                elif "does not contain any stream" in err_msg or "Output file is empty" in err_msg:
                    raise NoAudioStreamError("Video contains no audio stream.", job_id=job_id)
                raise RuntimeError(f"FFmpeg audio extraction error: {err_msg[-150:].strip()}")
            return output_audio_path
        except (CorruptMediaError, NoAudioStreamError, JobCancelledError):
            raise
        except Exception as e:
            raise CorruptMediaError(f"Cannot extract audio from video: {e}", job_id=job_id)

    def transcribe(
        self,
        video_or_audio_path: str,
        language: Optional[str] = "km",
        cancel_event: Optional[threading.Event] = None,
        job_id: Optional[str] = None
    ) -> List[Dict]:
        """
        Transcribes audio with Google Gemini.
        Features:
        - Real HTTP request timeout.
        - Bounded fallback without parallel leaking threads.
        - Graceful failover to local Faster-Whisper on Quota or Network errors.
        """
        if cancel_event and cancel_event.is_set():
            raise JobCancelledError("Job was cancelled before transcription started.", job_id=job_id)

        base_dir = os.path.dirname(video_or_audio_path)
        base_name = os.path.splitext(os.path.basename(video_or_audio_path))[0]
        temp_audio_path = os.path.join(base_dir, f"{base_name}_gemini_audio.mp3")
        created_temp_audio = False

        if video_or_audio_path.lower().endswith((".mp4", ".mov", ".mkv", ".webm", ".avi")):
            logger.info(f"[Job {job_id or 'sys'}] Extracting audio track for transcription...")
            self.extract_audio(video_or_audio_path, temp_audio_path, cancel_event=cancel_event, job_id=job_id)
            upload_target = temp_audio_path
            created_temp_audio = True
        else:
            upload_target = video_or_audio_path

        # Measure audio duration
        audio_duration_sec = 0.0
        try:
            d_cmd = [self.ffmpeg_path, "-i", upload_target]
            d_res = ProcessRunner.run(d_cmd, timeout=15.0, job_id=job_id)
            d_m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", d_res.stderr)
            if d_m:
                dh, dm, ds = d_m.groups()
                audio_duration_sec = float(dh) * 3600 + float(dm) * 60 + float(ds)
        except Exception as d_err:
            logger.warning(f"[Job {job_id or 'sys'}] Could not measure duration: {d_err}")

        uploaded_file = None
        try:
            if cancel_event and cancel_event.is_set():
                raise JobCancelledError("Job was cancelled.", job_id=job_id)

            logger.info(f"[Job {job_id or 'sys'}] Uploading audio to Google Gemini...")
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as up_exec:
                up_fut = up_exec.submit(self.client.files.upload, file=upload_target)
                try:
                    uploaded_file = up_fut.result(timeout=30.0)
                except concurrent.futures.TimeoutError:
                    raise NetworkError("Timeout uploading audio to Google Gemini.", job_id=job_id)

            dur_constraint = ""
            if audio_duration_sec > 0:
                mins = int(audio_duration_sec // 60)
                secs = int(audio_duration_sec % 60)
                tc_end = f"{mins:02d}:{secs:02d}.999"
                dur_constraint = (
                    f"CRITICAL DURATION CONSTRAINTS:\n"
                    f"- Total audio duration is EXACTLY {audio_duration_sec:.1f}s ({mins}m {secs}s).\n"
                    f"- All timestamps MUST strictly correspond to REAL speech. Last subtitle ends at or before {tc_end}.\n\n"
                )

            prompt = (
                "You are an elite video editor and audio transcriber specializing in viral captions.\n"
                "Output standard timestamp format:\n"
                "HOOK: <catchy title in 3-5 words>\n"
                "LANG: <detected language code>\n\n"
                f"{dur_constraint}"
                "1\n"
                "00:00.100 --> 00:01.300\n"
                "sample phrase\n\n"
                "CRITICAL RULES:\n"
                "1. RAPID SHORT-FORM PHRASES (2 to 4 words per line, 1.0 to 1.8s duration).\n"
                "2. Millisecond precision.\n"
                "3. Optional SFX tags like [sfx:cash], [sfx:ding], [sfx:buzzer], [sfx:pop]."
            )

            # Bounded fallback: try primary model, then max 1 fallback model
            models_to_try = [
                os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
                "gemini-2.5-flash-lite"
            ]

            response = None
            for model_name in models_to_try:
                if cancel_event and cancel_event.is_set():
                    raise JobCancelledError("Job was cancelled.", job_id=job_id)

                logger.info(f"[Job {job_id or 'sys'}] Calling Gemini model: {model_name}...")
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as gen_exec:
                    future = gen_exec.submit(
                        self.client.models.generate_content,
                        model=model_name,
                        contents=[uploaded_file, prompt],
                        config=types.GenerateContentConfig(
                            temperature=0.1,
                            http_options=types.HttpOptions(timeout=GEMINI_REQUEST_TIMEOUT)
                        )
                    )
                    try:
                        res = future.result(timeout=GEMINI_REQUEST_TIMEOUT)
                        if res and res.text:
                            response = res
                            logger.info(f"[Job {job_id or 'sys'}] Succeeded with model: {model_name}")
                            break
                    except concurrent.futures.TimeoutError:
                        logger.warning(f"[Job {job_id or 'sys'}] Model {model_name} timed out ({GEMINI_REQUEST_TIMEOUT}s).")
                    except Exception as m_err:
                        err_str = str(m_err).lower()
                        if "429" in err_str or "quota" in err_str or "resource_exhausted" in err_str:
                            logger.warning(f"[Job {job_id or 'sys'}] Gemini Quota exceeded ({m_err}). Stopping Cloud retries.")
                            raise QuotaExceededError("Gemini Cloud Quota exceeded.", job_id=job_id)
                        logger.warning(f"[Job {job_id or 'sys'}] Model {model_name} failed: {m_err}")

            if not response or not response.text:
                logger.warning(f"[Job {job_id or 'sys'}] Cloud models unavailable. Falling back to local Faster-Whisper...")
                return self._fallback_local_transcribe(upload_target, language, job_id=job_id)

            raw_text = response.text.strip()
            raw_text = re.sub(r"^```(?:srt|txt|json)?\s*", "", raw_text, flags=re.MULTILINE)
            raw_text = re.sub(r"\s*```$", "", raw_text, flags=re.MULTILINE).strip()

            hook_t, det_lang, srt_segments = parse_srt_or_arrow_transcript(
                raw_text,
                max_dur=audio_duration_sec or 3600.0
            )

            if srt_segments:
                self.hook_title = hook_t
                self.detected_language = det_lang
                return srt_segments

            # Try parsing JSON fallback if present
            try:
                parsed_json = json.loads(raw_text)
                words_data = parsed_json.get("segments", []) or parsed_json.get("words", [])
                if words_data:
                    self.hook_title = str(parsed_json.get("hook_title", "")).strip()
                    self.detected_language = str(parsed_json.get("language", "km")).strip()
                    return words_data
            except Exception:
                pass

            # If no segments parsed from response, fallback to local
            logger.warning(f"[Job {job_id or 'sys'}] Could not parse response. Falling back to local Whisper...")
            return self._fallback_local_transcribe(upload_target, language, job_id=job_id)

        except (JobCancelledError, CorruptMediaError, NoAudioStreamError):
            raise
        except (QuotaExceededError, NetworkError) as net_err:
            logger.warning(f"[Job {job_id or 'sys'}] {net_err.error_code}: Switching to local Whisper...")
            return self._fallback_local_transcribe(upload_target, language, job_id=job_id)
        except Exception as general_err:
            logger.warning(f"[Job {job_id or 'sys'}] Gemini error ({general_err}). Switching to local Whisper...")
            return self._fallback_local_transcribe(upload_target, language, job_id=job_id)
        finally:
            if uploaded_file:
                try:
                    self.client.files.delete(name=uploaded_file.name)
                except Exception:
                    pass
            if created_temp_audio and os.path.exists(temp_audio_path):
                try:
                    os.remove(temp_audio_path)
                except Exception:
                    pass

    def _fallback_local_transcribe(
        self,
        audio_or_video_path: str,
        language: Optional[str] = "km",
        job_id: Optional[str] = None
    ) -> List[Dict]:
        """Runs local Faster-Whisper as reliable local fallback."""
        from transcriber import AudioTranscriber
        logger.info(f"[Job {job_id or 'sys'}] Running local Faster-Whisper fallback...")
        local_t = AudioTranscriber(model_size=os.getenv("WHISPER_MODEL", "base"), device="cpu", compute_type="int8")
        words = local_t.transcribe(audio_or_video_path, language=language)

        if not words:
            raise NoSpeechDetectedError("No spoken words detected in audio.", job_id=job_id)

        self.hook_title = "Trending Highlight"
        self.detected_language = language or "km"
        return words

    def extract_visual_story_scenes(self, words: List[Dict], user_prompt: Optional[str] = None) -> List[Dict]:
        """Extracts visual story scenes for Mode 2 with optional user direction."""
        if not words:
            return []

        transcript_lines = []
        for w in words:
            transcript_lines.append(f"[{w.get('start', 0):.2f}s - {w.get('end', 0):.2f}s]: {w.get('word', '')}")
        full_transcript = "\n".join(transcript_lines)
        total_duration = max([w.get('end', 0) for w in words]) if words else 30

        target_scenes = 2 if total_duration < 25 else 3 if total_duration < 55 else 4
        # Default placeholder scenes if Gemini key is missing or prompt fails
        default_scenes = [
            {
                "layout": "polaroid",
                "start": round(total_duration * 0.15, 2),
                "end": round(total_duration * 0.40, 2),
                "topic": "ចំណុចសំខាន់ (Key Point)",
                "highlightWord": words[0]["word"] if words else "Highlight",
                "imagePrompt": f"minimalist aesthetic vertical cinematic photography {user_prompt or ''}".strip(),
                "sound": "whoosh"
            }
        ]

        if not self.api_key:
            return default_scenes

        try:
            prompt = f"""Generate {target_scenes} visual story scenes for vertical video transcript:\n{full_transcript}\nOutput JSON list only."""
            res = self.client.models.generate_content(
                model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
                contents=[prompt],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.2
                )
            )
            if res and res.text:
                parsed = json.loads(res.text)
                if isinstance(parsed, list):
                    return parsed
        except Exception as e:
            logger.warning(f"Visual scene extraction fallback: {e}")

        return default_scenes
