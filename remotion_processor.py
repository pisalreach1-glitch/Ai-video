"""
Remotion video rendering pipeline with:
- Configurable real subprocess timeouts (independent of Remotion's internal CLI --timeout).
- Process tree termination on cancellation.
- Degradation to local Whisper when GEMINI_API_KEY is absent.
- Accurate timeline and overlay mapping across silence removal.
- Explicit error handling (never returns input path on error).
"""

import os
import re
import json
import shutil
import logging
import threading
from typing import List, Dict, Optional, Tuple, Callable
from pathlib import Path

import utils
from transcriber import AudioTranscriber
from process_runner import ProcessRunner, DEFAULT_FFMPEG_TIMEOUT, DEFAULT_REMOTION_TIMEOUT
from timecode_utils import map_overlay_to_timeline, calculate_timeline_frames
from errors import (
    CorruptMediaError,
    NoSpeechDetectedError,
    ProcessTimeoutError,
    JobCancelledError
)
from remotion_sandbox import (
    validate_composition_name,
    validate_props_file,
    get_sanitized_render_env
)

logger = logging.getLogger(__name__)


def get_context_emoji(text: str) -> str:
    """Helper emoji for contextual pop."""
    t = text.lower()
    if any(k in t for k in ["លុយ", "ដុល្លារ", "លក់", "ចំណេញ", "ថ្លៃ", "money", "cash", "dollar"]):
        return "💰"
    if any(k in t for k in ["គន្លឹះ", "វិធី", "គំនិត", "មេរៀន", "tip", "idea"]):
        return "💡"
    if any(k in t for k in ["ស្រឡាញ់", "ចិត្ត", "ល្អ", "love", "heart"]):
        return "❤️"
    return ""


def build_smart_cuts(
    words: List[Dict],
    pad_before: float = 0.08,        # Cushion before speech (80ms)
    pad_after: float = 0.10,         # Cushion after speech (100ms)
    silence_threshold: float = 0.28, # Cut silence >= 0.28s
    max_shot_duration: float = 3.6   # Punch-in Zoom alternation interval
) -> List[Dict]:
    """
    Builds smart cuts and dynamic viral camera pacing:
    1. Cuts silence gaps >= 0.28s smoothly.
    2. Keeps 80ms before and 100ms after to prevent clipping words.
    3. Dynamic punch-in zoom (1.0x <-> 1.15x) on natural speech breaks.
    """
    if not words:
        return []

    sorted_words = sorted(words, key=lambda x: float(x.get("start", 0.0)))
    cuts = []
    current_cut = None
    zoom_alt = 0

    for w in sorted_words:
        ws = float(w.get("start", 0.0))
        we = float(w.get("end", ws + 0.1))
        w_text = str(w.get("word", "")).strip()

        if we <= ws or not w_text:
            continue

        item_dict = {
            "start": ws,
            "end": we,
            "text": w_text,
            "emoji": get_context_emoji(w_text),
            "words": w.get("words", [])
        }
        if "sfx" in w:
            item_dict["sfx"] = w["sfx"]

        if current_cut is None:
            current_cut = {
                "start": max(0.0, ws - pad_before),
                "end": we + pad_after,
                "zoom": 1.0,
                "subtitles": [item_dict]
            }
        else:
            prev_end = current_cut["subtitles"][-1]["end"]
            gap = ws - prev_end
            shot_dur = current_cut["end"] - current_cut["start"]

            is_silence_gap = gap >= silence_threshold
            is_shot_expired = shot_dur >= max_shot_duration

            if is_silence_gap:
                current_cut["end"] = min(current_cut["end"], prev_end + pad_after)
                cuts.append(current_cut)
                zoom_alt += 1
                current_cut = {
                    "start": max(0.0, ws - pad_before),
                    "end": we + pad_after,
                    "zoom": 1.15 if (zoom_alt % 2 == 1) else 1.0,
                    "subtitles": [item_dict]
                }
            elif is_shot_expired:
                cut_point = ws
                current_cut["end"] = cut_point
                cuts.append(current_cut)
                zoom_alt += 1
                current_cut = {
                    "start": cut_point,
                    "end": we + pad_after,
                    "zoom": 1.15 if (zoom_alt % 2 == 1) else 1.0,
                    "subtitles": [item_dict]
                }
            else:
                current_cut["end"] = max(current_cut["end"], we + pad_after)
                current_cut["subtitles"].append(item_dict)

    if current_cut:
        cuts.append(current_cut)

    return cuts


class RemotionProcessor:
    def __init__(self, remotion_dir: Optional[str] = None):
        if remotion_dir is None:
            base_project_dir = os.path.dirname(os.path.abspath(__file__))
            self.remotion_dir = os.path.join(base_project_dir, "remotion")
        else:
            self.remotion_dir = os.path.abspath(remotion_dir)

        self.public_dir = os.path.join(self.remotion_dir, "public")
        os.makedirs(self.public_dir, exist_ok=True)
        self.ffmpeg_path = utils.get_ffmpeg_path()

        # Graceful setup: Gemini key is optional!
        self.gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
        self.gemini_transcriber = None
        if self.gemini_key:
            try:
                from gemini_transcriber import GeminiTranscriber
                self.gemini_transcriber = GeminiTranscriber(api_key=self.gemini_key)
                logger.info("Google Gemini Transcriber loaded.")
            except Exception as e:
                logger.warning(f"Could not initialize GeminiTranscriber: {e}")

        # Local Whisper Transcriber for offline/fallback mode
        self.local_transcriber = AudioTranscriber(
            model_size=os.getenv("WHISPER_MODEL", "small"),
            device="cpu",
            compute_type="int8"
        )
        self.last_clean_video: Optional[str] = None
        logger.info("RemotionProcessor ready.")

    def enhance_audio(
        self,
        input_video: str,
        output_video: str,
        cancel_event: Optional[threading.Event] = None,
        job_id: Optional[str] = None
    ) -> str:
        """
        Filters noise, boosts dialogue clarity, and normalizes video to fast-seek H.264 30fps.
        Never returns input_video on failure; raises error.
        """
        # Hardware acceleration check (NVENC)
        cmd_nvenc = [
            self.ffmpeg_path,
            "-y",
            "-i", input_video,
            "-af", "highpass=f=75,afftdn=nf=-25:tn=1,dynaudnorm=f=120:g=15:p=0.92,loudnorm=I=-16:TP=-1.5:LRA=11",
            "-c:v", "h264_nvenc",
            "-preset", "p4",
            "-tune", "hq",
            "-b:v", "8M",
            "-g", "30",
            "-r", "30",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            output_video
        ]
        try:
            logger.info(f"[Job {job_id or 'sys'}] Enhancing audio and normalizing video (NVENC)...")
            res = ProcessRunner.run(cmd_nvenc, timeout=DEFAULT_FFMPEG_TIMEOUT, cancel_event=cancel_event, job_id=job_id)
            if res.returncode == 0 and os.path.exists(output_video) and os.path.getsize(output_video) > 1000:
                return output_video
        except (JobCancelledError, ProcessTimeoutError):
            raise
        except Exception as e:
            logger.info(f"NVENC not available ({e}), falling back to CPU libx264...")

        # CPU fallback (libx264)
        cmd_cpu = [
            self.ffmpeg_path,
            "-y",
            "-i", input_video,
            "-af", "highpass=f=75,afftdn=nf=-25:tn=1,dynaudnorm=f=120:g=15:p=0.92,loudnorm=I=-16:TP=-1.5:LRA=11",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "20",
            "-g", "30",
            "-r", "30",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            output_video
        ]
        res_cpu = ProcessRunner.run(cmd_cpu, timeout=DEFAULT_FFMPEG_TIMEOUT, cancel_event=cancel_event, job_id=job_id)
        if res_cpu.returncode == 0 and os.path.exists(output_video) and os.path.getsize(output_video) > 1000:
            return output_video

        raise RuntimeError(f"Failed to enhance audio and normalize video: {res_cpu.stderr[-300:]}")

    def transcribe_video(
        self,
        input_video_path: str,
        language: Optional[str] = None,
        cancel_event: Optional[threading.Event] = None,
        job_id: Optional[str] = None
    ) -> Tuple[List[Dict], str]:
        """
        Transcribes video speech:
        Uses Gemini if configured, otherwise falls back to local Whisper.
        """
        abs_input = os.path.abspath(input_video_path)
        words: List[Dict] = []
        hook_title = ""

        if self.gemini_transcriber:
            try:
                words = self.gemini_transcriber.transcribe(
                    abs_input,
                    language=language,
                    cancel_event=cancel_event,
                    job_id=job_id
                )
                hook_title = getattr(self.gemini_transcriber, "hook_title", "")
            except Exception as e:
                logger.warning(f"Gemini transcription failed ({e}). Falling back to local Whisper...")

        if not words:
            logger.info(f"[Job {job_id or 'sys'}] Running local Whisper transcription...")
            words = self.local_transcriber.transcribe(abs_input, language=language)
            hook_title = "Trending Highlight"

        return words or [], hook_title

    def process_video(
        self,
        input_video_path: str,
        output_video_path: str,
        language: Optional[str] = None,
        theme: str = "tiktok_viral",
        bgm: str = "lofi",
        show_progress_bar: bool = True,
        words: Optional[List[Dict]] = None,
        hook_title: Optional[str] = None,
        custom_font: Optional[str] = None,
        visual_overlays: Optional[List[Dict]] = None,
        cached_clean_video: Optional[str] = None,
        timeout: Optional[float] = None,
        on_pid_assigned: Optional[Callable[[int], None]] = None,
        cancel_event: Optional[threading.Event] = None,
        job_id: Optional[str] = None
    ) -> str:
        """
        Full Remotion render pipeline:
        1. Speech transcription (if words not already provided).
        2. Audio enhancement and CFR 30fps video normalization.
        3. Smart Cuts generation.
        4. Context SFX events.
        5. Visual overlay mapping across silence cuts.
        6. Remotion CLI rendering with real timeout and process tree termination.
        Never returns input path; returns output_video_path or raises exception.
        """
        abs_input = os.path.abspath(input_video_path)
        abs_output = os.path.abspath(output_video_path)

        # Step 1: Transcribe if not provided
        if words is None:
            words, extracted_hook = self.transcribe_video(
                abs_input,
                language=language,
                cancel_event=cancel_event,
                job_id=job_id
            )
            if hook_title is None:
                hook_title = extracted_hook
        else:
            if hook_title is None:
                hook_title = "Trending Highlight"

        if not words:
            raise NoSpeechDetectedError("No spoken words detected in video.", job_id=job_id)

        # Step 2: Audio Enhancement & CFR 30fps Normalization
        unique_id = job_id or f"{int(os.path.getmtime(abs_input))}_{abs(hash(abs_input)) % 10000}"
        clean_video_path = cached_clean_video

        if not clean_video_path or not os.path.exists(clean_video_path):
            clean_video_path = os.path.join(self.public_dir, f"clean_{unique_id}.mp4")
            self.enhance_audio(
                abs_input,
                clean_video_path,
                cancel_event=cancel_event,
                job_id=job_id
            )

        self.last_clean_video = clean_video_path

        # Step 3: Smart Cuts
        cuts = build_smart_cuts(words)
        if not cuts:
            # Fallback to single uncut segment
            cuts = [{
                "start": 0.0,
                "end": max([w.get("end", 1.0) for w in words]),
                "zoom": 1.0,
                "subtitles": words
            }]

        # Step 4: SFX Events
        sfx_events = []
        timeline_cursor = 0.0
        for idx, cut in enumerate(cuts):
            cut_duration = max(0.2, cut["end"] - cut["start"])
            if idx > 0 and cut.get("zoom", 1.0) > 1.05:
                sfx_events.append({
                    "start": max(0.0, timeline_cursor - 0.05),
                    "sound": "whoosh",
                    "volume": 0.40
                })

            valid_sfx = {
                "whoosh": 0.40, "pop": 0.45, "cash": 0.50, "ding": 0.48,
                "thud": 0.55, "click": 0.42, "camera": 0.45, "buzzer": 0.45,
                "tada": 0.50, "sparkle": 0.45, "riser": 0.42, "heartbeat": 0.50
            }
            for sub in cut.get("subtitles", []):
                sfx_tag = sub.get("sfx")
                if sfx_tag and sfx_tag in valid_sfx:
                    sub_offset = max(0.0, sub["start"] - cut["start"])
                    sfx_events.append({
                        "start": timeline_cursor + sub_offset,
                        "sound": sfx_tag,
                        "volume": valid_sfx[sfx_tag]
                    })
            timeline_cursor += cut_duration

        # Step 5: Copy video to public/ for Remotion staticFile()
        public_filename = f"clip_{unique_id}.mp4"
        public_path = os.path.join(self.public_dir, public_filename)
        shutil.copy2(clean_video_path, public_path)

        props_filename = f"props_{unique_id}.json"
        props_path = os.path.join(self.remotion_dir, props_filename)

        # Map Visual Overlays across silence removal cuts
        mapped_overlays = []
        if visual_overlays:
            for vo in visual_overlays:
                vo_copy = dict(vo)
                orig_s = float(vo.get("start", 0))
                orig_e = float(vo.get("end", orig_s + 3.5))
                tl_s, tl_e = map_overlay_to_timeline(orig_s, orig_e, cuts)
                vo_copy["start"] = tl_s
                vo_copy["end"] = tl_e
                mapped_overlays.append(vo_copy)

        props_data = {
            "videoSrc": public_filename,
            "cuts": cuts,
            "sfxEvents": sfx_events,
            "hookTitle": hook_title,
            "fps": 30,
            "theme": theme,
            "customFont": custom_font,
            "bgm": bgm,
            "showProgressBar": show_progress_bar,
            "visualOverlays": mapped_overlays
        }

        # Validate props and composition before rendering
        validate_composition_name("ShortComposition")
        validate_props_file(props_data, allowed_roots=[Path(self.remotion_dir), Path(self.public_dir)])

        with open(props_path, "w", encoding="utf-8") as f:
            json.dump(props_data, f, ensure_ascii=False, indent=2)

        # Step 6: Render video with Remotion CLI
        npx_cmd = "npx.cmd" if os.name == "nt" else "npx"
        cmd = [
            npx_cmd,
            "remotion",
            "render",
            "src/index.ts",
            "ShortComposition",
            abs_output,
            f"--props={props_filename}",
            "--overwrite",
            "--crf=23",
            "--concurrency=4",
            "--offthreadvideo-cache-size-in-bytes=2147483648",
            "--timeout=60000",
            "--bundle-cache",
            "--x264-preset=veryfast",
            "--gl=angle",
            "--pixel-format=yuv420p"
        ]

        logger.info(f"[Job {job_id or 'sys'}] Executing Remotion render command...")
        render_timeout = timeout or DEFAULT_REMOTION_TIMEOUT

        try:
            sanitized_env = get_sanitized_render_env()
            proc_out = ProcessRunner.run(
                cmd,
                cwd=self.remotion_dir,
                timeout=render_timeout,
                on_pid_assigned=on_pid_assigned,
                cancel_event=cancel_event,
                env=sanitized_env,
                job_id=job_id
            )

            if proc_out.returncode != 0:
                logger.error(f"[Job {job_id or 'sys'}] Remotion Render Error: {proc_out.stderr[-500:]}")
                raise RuntimeError(f"Remotion Error: {proc_out.stderr[-500:]}")

            if not os.path.exists(abs_output) or os.path.getsize(abs_output) == 0:
                raise RuntimeError(f"Rendered video file was not created: {abs_output}")

            logger.info(f"[Job {job_id or 'sys'}] Remotion Render succeeded: {abs_output}")
            return abs_output

        finally:
            for temp_f in [public_path, props_path]:
                if temp_f and os.path.exists(temp_f):
                    try:
                        os.remove(temp_f)
                    except Exception:
                        pass
