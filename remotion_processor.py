import os
import json
import logging
import subprocess
import time
import shutil
from typing import Optional, List, Dict
from gemini_transcriber import GeminiTranscriber
import utils

logger = logging.getLogger(__name__)

def get_context_emoji(text: str) -> str:
    """ចាប់យក Emoji តាមអត្ថន័យពាក្យជាក់ស្ដែង (មិនដាក់បង្ខំគ្រប់ឃ្លាឡើយ)"""
    if any(k in text for k in ["លុយ", "ដុល្លារ", "លក់", "ចំណេញ", "ថ្លៃ", "ទិញ", "ចំណូល", "ទ្រព្យ"]):
        return "💰"
    if any(k in text for k in ["ក្ដៅ", "ខ្លាំង", "ល្បី", "អស្ចារ្យ", "ពេញនិយម"]):
        return "🔥"
    if any(k in text for k in ["គន្លឹះ", "វិធី", "គំនិត", "សម្ងាត់", "ចំណេះ", "មេរៀន"]):
        return "💡"
    if any(k in text for k in ["កុំ", "ខុស", "បញ្ហា", "ប្រយ័ត្ន", "ខាត", "គ្រោះថ្នាក់", "ចាញ់"]):
        return "⚠️"
    if any(k in text for k in ["ជោគជ័យ", "កំពូល", "ស្តេច", "មេ", "លេខ១", "ឈ្នះ"]):
        return "👑"
    if any(k in text for k in ["លឿន", "រហ័ស", "ទាន់ចិត្ត", "ភ្លាម"]):
        return "⚡"
    if any(k in text for k in ["ទូរស័ព្ទ", "អនឡាញ", "បច្ចេកវិទ្យា", "AI"]):
        return "📱"
    if any(k in text for k in ["ស្រឡាញ់", "ពេញចិត្ត", "ល្អ", "បេះដូង"]):
        return "❤️"
    return ""

def build_smart_cuts(
    words: List[Dict],
    pad_before: float = 0.08,        # Cushion មុនពេលនិយាយ 80ms (មិនដាច់ព្យាង្គមុខ 100%)
    pad_after: float = 0.10,         # Cushion ក្រោយពេលនិយាយ 100ms (សំឡេងរលូន មិនកំបុត)
    silence_threshold: float = 0.28, # កាត់ Dead Air / Silence Gap >= 0.28s (280ms)
    max_shot_duration: float = 3.6   # Punch-in Zoom (1.0x <-> 1.15x) រៀងរាល់ ~3.6s តាមចង្វាក់ធម្មជាតិ
) -> List[Dict]:
    """
    ក្បួន Smart Cut & Dynamic Viral Video Pacing កម្រិត Professional (MrBeast / Hormozi Style):
    1. កាត់ចន្លោះស្ងាត់ (Dead Space / Silence >= 0.28s) ដោយស្វ័យប្រវត្តិ ធានាថាមិនស្ងាត់ចោល
    2. Cushion មុខ 80ms និងក្រោយ 100ms ការពារមិនឱ្យដាច់ពាក្យ ឬកាត់សំឡេងកំបុត ១០០%
    3. Dynamic Punch-In Jump Cut: ប្តូរមុំកាមេរ៉ាហ្ស៊ូម (1.0x <-> 1.15x) រៀងរាល់ពេលកាត់ចន្លោះស្ងាត់ ឬរៀងរាល់ ~3-4 វិនាទី
       ដែលធ្វើឱ្យវីដេអូរស់រវើក ទាក់ទាញភ្នែក និងមិនមានភាពធុញទ្រាន់!
    """
    if not words:
        return []

    sorted_words = sorted(words, key=lambda x: float(x["start"]))

    cuts = []
    current_cut = None
    zoom_alt = 0

    for w in sorted_words:
        ws = float(w["start"])
        we = float(w["end"])
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
                # 1. កាត់ Dead Air / Silence Gap ចោល៖
                # Shot ចាស់បញ្ចប់ត្រឹម prev_end + pad_after
                current_cut["end"] = min(current_cut["end"], prev_end + pad_after)
                cuts.append(current_cut)
                zoom_alt += 1
                # Shot ថ្មីចាប់ផ្តើមពី ws - pad_before
                current_cut = {
                    "start": max(0.0, ws - pad_before),
                    "end": we + pad_after,
                    "zoom": 1.15 if (zoom_alt % 2 == 1) else 1.0,
                    "subtitles": [item_dict]
                }
            elif is_shot_expired:
                # 2. Jump Cut / Punch-In Zoom តាមចង្វាក់ធម្មជាតិ (គ្មាន Silence Gap)៖
                # កាត់ត្រង់ចន្លោះឃ្លា (ws) យ៉ាងសុក្រឹត ដោយគ្មាន Overlap និងគ្មានបាត់សំឡេង
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
                # 3. និយាយបន្តក្នុង Shot តែមួយដោយរលូន
                current_cut["end"] = max(current_cut["end"], we + pad_after)
                current_cut["subtitles"].append(item_dict)

    if current_cut:
        cuts.append(current_cut)

    logger.info(f"✨ Smart Cuts: បានបង្កើត {len(cuts)} Shots រលូន (Silence Threshold: {silence_threshold}s, Pad: {pad_before}s/{pad_after}s)")
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
        self.gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not self.gemini_key:
            raise ValueError("ត្រូវការ GEMINI_API_KEY នៅក្នុង .env ដើម្បីដំណើរការ Auto-Cut!")
        
        self.transcriber = GeminiTranscriber(api_key=self.gemini_key)
        logger.info("RemotionProcessor ត្រូវបានបង្កើតឡើងដោយជោគជ័យ!")

    def enhance_audio(self, input_video: str, output_video: str) -> str:
        """
        1. កម្ចាត់សំឡេង Noise (កង្ហារ ម៉ាស៊ីនត្រជាក់ Hiss) និងជម្រុញសំឡេងនិយាយឱ្យច្បាស់ណែន (Podcast Studio Clarity)
        2. Normalize វីដេអូទៅជា Fast-Seek H.264 (CFR 30fps + Keyframe GOP 30) ដោយ NVIDIA RTX NVENC (ឬ CPU libx264)
           ដើម្បីធានាថា Remotion អាច Seek គ្រប់ Frame បានរលូន ១០០% និងមិនមាន Error 'No frame found at position'
        """
        # A. សាកល្បងប្រើ Hardware Acceleration (NVIDIA NVENC) ជាចម្បង (~8 វិនាទី)
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
            logger.info("🎙️ កំពុងកាត់សំឡេង Noise និង Normalize វីដេអូទៅ Fast-Seek H.264 30fps (RTX NVENC)...")
            res = subprocess.run(cmd_nvenc, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if res.returncode == 0 and os.path.exists(output_video) and os.path.getsize(output_video) > 1000:
                logger.info("✨ វីដេអូ និងសំឡេងត្រូវបាន Enhance & Fast-Keyframe H.264 ដោយ NVIDIA NVENC ជោគជ័យ!")
                return output_video
            else:
                logger.warning("NVENC render failed, falling back to CPU libx264...")
        except Exception as e:
            logger.warning(f"NVENC exception ({e}), falling back to CPU libx264...")

        # B. CPU Fallback (libx264)
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
        try:
            logger.info("🎙️ កំពុងកាត់សំឡេង Noise និង Normalize វីដេអូដោយ CPU libx264...")
            res = subprocess.run(cmd_cpu, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if res.returncode == 0 and os.path.exists(output_video) and os.path.getsize(output_video) > 1000:
                logger.info("✨ វីដេអូ និងសំឡេងត្រូវបាន Enhance & Fast-Keyframe H.264 ដោយ CPU libx264 ជោគជ័យ!")
                return output_video
        except Exception as e:
            logger.warning(f"CPU libx264 exception: {e}")

        return input_video

    def transcribe_video(self, input_video_path: str, language: str = None):
        """
        ទាញយក Timestamps, ពាក្យសម្ដី និង Viral Hook Title ពី Gemini AI សម្រាប់ពិនិត្យ និងកែសម្រួល
        """
        abs_input = os.path.abspath(input_video_path)
        logger.info("Gemini កំពុងវិភាគសម្ដីនិយាយ រក Viral Hook Title & Context SFX...")
        words = self.transcriber.transcribe(abs_input, language=language)
        hook_title = getattr(self.transcriber, "hook_title", "")
        return words or [], hook_title

    def process_video(
        self,
        input_video_path: str,
        output_video_path: str,
        language: str = None,
        theme: str = "tiktok_viral",
        bgm: str = "lofi",
        show_progress_bar: bool = True,
        words: list = None,
        hook_title: str = None,
        custom_font: str = None,
        visual_overlays: list = None,
        cached_clean_video: str = None
    ) -> str:
        """
        ដំណើរការកាត់តវីដេអូបែបធម្មជាតិ (Natural Smart Cut) និងដាក់អក្សរ Spring Pop:
        1. Gemini ស្ដាប់សំឡេងទាញយក Timestamps, Hook Title & SFX cues (ប្រសិនបើមិនទាន់បាន transcribe)
        2. កាត់សំឡេង Noise ឱ្យច្បាស់បែប Studio ដោយ FFmpeg
        3. បង្កើត Smart Cuts & Dynamic Punch-In Camera Cuts
        4. រៀបចំ SFX Events (Whoosh, Cash, Ding, Thud, Pop)
        5. បញ្ជូនទៅ Remotion (React) ដើម្បី Render Word-by-Word Kinetic Highlighting & Hook Banner
        """
        abs_input = os.path.abspath(input_video_path)
        abs_output = os.path.abspath(output_video_path)

        # ជំហានទី ១: យក Speech Analysis & Viral Hook Extraction
        if words is None:
            logger.info("ជំហានទី ១: Gemini កំពុងវិភាគសម្ដីនិយាយ រក Viral Hook Title & Context SFX...")
            words = self.transcriber.transcribe(abs_input, language=language)
            hook_title = getattr(self.transcriber, "hook_title", "")
        else:
            if hook_title is None:
                hook_title = getattr(self.transcriber, "hook_title", "")

        if not words:
            logger.warning("មិនមានសម្ដីនិយាយក្នុងវីដេអូទេ!")
            return input_video_path

        # ជំហានទី ២: កាត់សំឡេង Noise និងបង្កើនភាពច្បាស់ (Audio Denoising & Studio Boost)
        unique_id = int(time.time() * 1000)
        enhanced_input_path = None

        if cached_clean_video and os.path.exists(cached_clean_video):
            clean_video_path = cached_clean_video
            logger.info(f"⚡ ប្រើប្រាស់ Cached Clean Video ឡើងវិញ (រំលង FFmpeg Enhance): {clean_video_path}")
        else:
            enhanced_input_path = os.path.join(self.public_dir, f"enhanced_{unique_id}.mp4")
            clean_video_path = self.enhance_audio(abs_input, enhanced_input_path)
            self.last_clean_video = clean_video_path

        # ជំហានទី ៣: បង្កើត Smart Cuts បែបធម្មជាតិ (Silence > 0.65s, Buffer 180ms/250ms)
        cuts = build_smart_cuts(words)

        logger.info(f"ជំហានទី ៣: បានរៀបចំ {len(cuts)} Shots ធម្មជាតិ (ពី {len(words)} ឃ្លា)")

        # ជំហានទី ៤: រៀបចំ Context Sound Effects (Whoosh, Ding, Cash, Thud, Pop)
        sfx_events = []
        timeline_cursor = 0.0

        for idx, cut in enumerate(cuts):
            cut_duration = max(0.2, cut["end"] - cut["start"])

            # Camera Transition Whoosh (ពេលកាមេរ៉ា Punch-In Zoom)
            if idx > 0 and cut.get("zoom", 1.0) > 1.05:
                sfx_events.append({
                    "start": max(0.0, timeline_cursor - 0.05),
                    "sound": "whoosh",
                    "volume": 0.40
                })

            # Semantic SFX តាមអត្ថន័យពាក្យ (Cash, Ding, Thud, Pop, Buzzer, Tada, Click, Camera, Sparkle, Riser, Heartbeat)
            valid_sfx = {
                "whoosh": 0.40,
                "pop": 0.45,
                "cash": 0.50,
                "ding": 0.48,
                "thud": 0.55,
                "click": 0.42,
                "camera": 0.45,
                "buzzer": 0.45,
                "tada": 0.50,
                "sparkle": 0.45,
                "riser": 0.42,
                "heartbeat": 0.50,
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

        logger.info(f"ជំហានទី ៤: បានរៀបចំ {len(sfx_events)} Sound Effects (Transitions & Semantic SFX)!")

        # ជំហានទី ៥: ចម្លងវីដេអូទៅ public/ សម្រាប់ Remotion staticFile()
        public_filename = f"clip_{unique_id}.mp4"
        public_path = os.path.join(self.public_dir, public_filename)
        shutil.copy2(clean_video_path, public_path)

        props_filename = f"props_{unique_id}.json"
        props_path = os.path.join(self.remotion_dir, props_filename)

        # Map Visual Overlays ទៅកាន់ Assembled Timeline យ៉ាងសុក្រឹត ១០០%
        mapped_overlays = []
        if visual_overlays:
            def _to_timeline(orig_t: float) -> float:
                accum = 0.0
                for c in cuts:
                    c_dur = max(0.2, c["end"] - c["start"])
                    if orig_t < c["start"]:
                        return accum
                    if c["start"] <= orig_t <= c["end"]:
                        return accum + (orig_t - c["start"])
                    accum += c_dur
                return accum

            for vo in visual_overlays:
                vo_copy = dict(vo)
                orig_s = float(vo.get("start", 0))
                orig_e = float(vo.get("end", orig_s + 3.8))
                tl_s = _to_timeline(orig_s)
                tl_e = _to_timeline(orig_e)
                if tl_e <= tl_s:
                    tl_e = tl_s + 3.5
                vo_copy["start"] = round(tl_s, 2)
                vo_copy["end"] = round(tl_e, 2)
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

        with open(props_path, "w", encoding="utf-8") as f:
            json.dump(props_data, f, ensure_ascii=False, indent=2)

        # ជំហានទី ៦: Render វីដេអូជាមួយ Remotion CLI
        logger.info("ជំហានទី ៦: Remotion កំពុង Render វីដេអូជាមួយ Word-by-Word Highlighting, Hook Banner & SFX...")
        
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

        logger.info(f"Executing: {' '.join(cmd)}")
        try:
            result = subprocess.run(
                cmd,
                cwd=self.remotion_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            if result.returncode != 0:
                logger.error(f"Remotion Render Error: {result.stderr}")
                raise RuntimeError(f"Remotion Error: {result.stderr[-500:]}")

            logger.info(f"Remotion Render ជោគជ័យ ១០០%: {abs_output}")
            return abs_output

        finally:
            for temp_f in [public_path, props_path]:
                if temp_f and os.path.exists(temp_f):
                    try:
                        os.remove(temp_f)
                    except Exception:
                        pass
