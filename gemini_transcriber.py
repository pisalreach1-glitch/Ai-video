def group_into_natural_phrases(words, min_dur=0.9, max_dur=2.4, max_chars=32, max_gap=0.45):
    """
    បង្រួមពាក្យខ្លីៗជាឃ្លាធម្មជាតិ (២ ទៅ ៤ ពាក្យ) ដែលងាយស្រួលអាន និងមិនលោតលឿនពេក:
    - កំណត់ឱ្យឃ្លានីមួយៗបង្ហាញលើអេក្រង់យ៉ាងហោចណាស់ 1.0 ទៅ 2.4 វិនាទី
    - ជៀសវាងការកាត់តែ ១ ពាក្យកំបុតៗ ដែលមើលមិនទាន់
    """
    if not words:
        return []
    
    phrases = []
    curr = None

    for w in words:
        w_text = str(w.get("word", "")).strip()
        sfx = w.get("sfx")

        # Strip any <sfx .../> or XML/HTML tags from text
        sfx_match = re.search(r'<sfx\s+name=["\']?(\w+)["\']?\s*/?>', w_text, re.IGNORECASE)
        if sfx_match and not sfx:
            sfx = sfx_match.group(1).lower()
        w_text = re.sub(r'<[^>]+>', '', w_text).strip()
        w_text = re.sub(r'\s+', ' ', w_text).strip()
        ws = float(w.get("start", 0))
        we = float(w.get("end", ws + 0.8))
        sfx = w.get("sfx")

        if not w_text or we <= ws:
            continue

        if curr is None:
            curr = {
                "word": w_text,
                "start": ws,
                "end": we,
                "sfx": sfx,
                "words": [{"text": w_text, "start": ws, "end": we}]
            }
        else:
            gap = ws - curr["end"]
            dur = we - curr["start"]
            combined_len = len(curr["word"]) + len(w_text) + 1

            if gap <= max_gap and (dur <= min_dur or (dur <= max_dur and combined_len <= max_chars)):
                curr["word"] = curr["word"] + " " + w_text
                curr["end"] = we
                if "words" not in curr:
                    curr["words"] = []
                curr["words"].append({"text": w_text, "start": ws, "end": we})
                if sfx and not curr.get("sfx"):
                    curr["sfx"] = sfx
            else:
                phrases.append(curr)
                curr = {
                    "word": w_text,
                    "start": ws,
                    "end": we,
                    "sfx": sfx,
                    "words": [{"text": w_text, "start": ws, "end": we}]
                }

    if curr:
        phrases.append(curr)

    return phrases


import os
import json
import logging
import re
import subprocess
from typing import List, Dict, Optional
from google import genai
from google.genai import types
import utils

logger = logging.getLogger(__name__)

def parse_timecode(tc: str, max_dur: float = 3600.0) -> float:
    """បំប្លែង Timecode (00:01:23.456 ឬ 01:28:10 ឬ 00:01.456 ឬ 01:32:150) ទៅជា Float Seconds យ៉ាងសុក្រឹត"""
    tc = tc.strip().replace(",", ".")
    parts = tc.split(":")
    if len(parts) == 3:
        p0, p1, p2 = float(parts[0]), float(parts[1]), float(parts[2])
        if p0 == 0:
            return p1 * 60.0 + p2
        if p0 * 3600 > max_dur or p2 > 60:
            frac = p2 / 1000.0 if p2 >= 100 else p2 / 100.0 if p2 >= 10 else p2 / 10.0
            return p0 * 60.0 + p1 + frac
        return p0 * 3600.0 + p1 * 60.0 + p2
    elif len(parts) == 2:
        return float(parts[0]) * 60.0 + float(parts[1])
    else:
        return float(parts[0])

def parse_srt_or_arrow_transcript(raw_text: str, max_dur: float = 3600.0):
    """
    វិភាគអត្ថបទ SRT / Timestamp Arrow (00:00.000 --> 00:02.500) យ៉ាងសុក្រឹត និងរហ័ស
    គាំទ្រគ្រប់ទម្រង់ SRT, WebVTT, និង Arrow Delimiters
    """
    hook_title = ""
    detected_lang = "km"
    segments = []

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

    # Regular expression សម្រាប់ចាប់ Timecode Arrow
    time_arrow_pattern = re.compile(
        r"(?:\[)?(\d{1,2}:\d{2}(?::\d{2,3})?(?:[,\.]\d{1,3})?)\s*(?:-->|->|—>|–>|to)\s*(\d{1,2}:\d{2}(?::\d{2,3})?(?:[,\.]\d{1,3})?)(?:\])?(?:\s*[:\|]\s*(.*))?",
        re.IGNORECASE
    )

    i = 0
    while i < len(clean_lines):
        line = clean_lines[i]

        # បើជាលេខរៀង SRT (1, 2, 3...)
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
                st = parse_timecode(st_str, max_dur)
                et = parse_timecode(et_str, max_dur)
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
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = genai.Client(api_key=api_key)
        self.ffmpeg_path = utils.get_ffmpeg_path()
        logger.info("Google Gemini Transcriber ត្រូវបានរៀបចំរួចរាល់!")

    def extract_audio(self, video_path: str, output_audio_path: str) -> str:
        """ទាញយក Audio ជា MP3 ស្រាល និងលឿនចេញពី Video"""
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
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            return output_audio_path
        except subprocess.CalledProcessError as e:
            err_msg = e.stderr.decode("utf-8", errors="ignore") if e.stderr else ""
            if "moov atom not found" in err_msg or "Invalid data found" in err_msg:
                raise RuntimeError("ឯកសារវីដេអូមិនពេញលេញ ឬខូចខាតកំឡុងពេលទាញយក (Incomplete Video: moov atom missing)។ សូមផ្ញើវីដេអូម្ដងទៀត!")
            elif "does not contain any stream" in err_msg or "Output file is empty" in err_msg:
                raise RuntimeError("វីដេអូនេះគ្មានសំឡេងនិយាយទេ (No Audio Track Found)!")
            raise RuntimeError(f"មិនអាចទាញយកសំឡេងពីវីដេអូបានទេ ({err_msg[-150:].strip()})")

    def transcribe(self, video_or_audio_path: str, language: Optional[str] = "km") -> List[Dict]:
        """
        ប្រើប្រាស់ Gemini 2.5 Flash ដើម្បីបំប្លែងសំឡេងខ្មែរទៅជាអក្សរខ្មែរសុទ្ធ ១០០% ជាមួយ Timestamps
        """
        base_dir = os.path.dirname(video_or_audio_path)
        base_name = os.path.splitext(os.path.basename(video_or_audio_path))[0]
        temp_audio_path = os.path.join(base_dir, f"{base_name}_gemini_audio.mp3")
        created_temp_audio = False

        if video_or_audio_path.lower().endswith((".mp4", ".mov", ".mkv", ".webm", ".avi")):
            logger.info("កំពុងទាញយក Audio ពី Video...")
            self.extract_audio(video_or_audio_path, temp_audio_path)
            upload_target = temp_audio_path
            created_temp_audio = True
        else:
            upload_target = video_or_audio_path

        # វាស់ប្រវែង Audio / Video Duration ជាក់ស្តែង (ពិតប្រាកដ) តាមរយៈ FFmpeg
        audio_duration_sec = 0.0
        try:
            d_cmd = [self.ffmpeg_path, "-i", upload_target]
            d_res = subprocess.run(d_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            d_m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", d_res.stderr)
            if d_m:
                dh, dm, ds = d_m.groups()
                audio_duration_sec = float(dh) * 3600 + float(dm) * 60 + float(ds)
                logger.info(f"⏱️ ប្រវែង Duration សំឡេងជាក់ស្តែង: {audio_duration_sec:.2f} វិនាទី")
        except Exception as d_err:
            logger.warning(f"⚠️ មិនអាចវាស់ Duration: {d_err}")

        uploaded_file = None
        try:
            try:
                logger.info("កំពុង Upload Audio ទៅកាន់ Google Gemini...")
                import concurrent.futures
                up_exec = concurrent.futures.ThreadPoolExecutor(max_workers=1)
                try:
                    up_fut = up_exec.submit(self.client.files.upload, file=upload_target)
                    uploaded_file = up_fut.result(timeout=25)
                    logger.info(f"Upload ជោគជ័យ: {uploaded_file.name}")
                finally:
                    up_exec.shutdown(wait=False, cancel_futures=True)
            except Exception as up_err:
                logger.warning(f"⚠️ Upload Audio ទៅ Gemini យឺត ឬមានបញ្ហា ({up_err})! ប្ដូរទៅ Local Whisper ភ្លាមៗ...")
                return self._fallback_local_transcribe(upload_target, language)

            lang_hint = f"in {language}." if (language and language not in ["auto", "all"]) else "in the natural spoken language. Automatically detect if the audio is in Khmer (ភាសាខ្មែរ), English, Chinese (中文), Thai (ไทย), Vietnamese, French, Japanese, or mixed multilingual speech."

            dur_constraint = ""
            if audio_duration_sec > 0:
                mins = int(audio_duration_sec // 60)
                secs = int(audio_duration_sec % 60)
                tc_end = f"{mins:02d}:{secs:02d}.999"
                dur_constraint = (
                    f"CRITICAL DURATION CONSTRAINTS:\n"
                    f"- The total audio duration is EXACTLY {audio_duration_sec:.1f} seconds ({mins}m {secs}s).\n"
                    f"- All timestamps MUST strictly correspond to the REAL audio speech. The last subtitle MUST end at or before {tc_end}.\n"
                    f"- DO NOT estimate or artificially pace timestamps. Start and end times must match the exact mouth/vocalization timing.\n\n"
                )

            prompt = (
                "You are an elite Hollywood video editor and audio transcriber specializing in viral TikTok/Reels captions (CapCut & MrBeast style).\n"
                f"Your task is to transcribe this audio with ultra-precise mouth-synchronized timestamps {lang_hint}\n\n"
                f"{dur_constraint}"
                "FORMAT SPECIFICATION (Standard SRT / Timestamps 00:00.000 --> 00:02.500):\n"
                "Output the transcript in standard timestamp format:\n"
                "HOOK: <short catchy viral title in 3-5 words>\n"
                "LANG: <detected language code, e.g. km, en, zh, th>\n\n"
                "1\n"
                "00:00.100 --> 00:01.300\n"
                "បងៗទាំងអស់គ្នា\n\n"
                "2\n"
                "00:01.350 --> 00:02.600\n"
                "ហួយសាច់គោអ្នកទាំងអស់គ្នា [sfx:cash]\n\n"
                "3\n"
                "00:02.650 --> 00:04.100\n"
                "ទិញទៅឥឡូវហ្នឹង [sfx:pop]\n\n"
                "CRITICAL RULES FOR ULTRA-PRECISE MOUTH-SYNC (CAPCUT STYLE):\n"
                "1. RAPID SHORT-FORM PHRASES (2 to 4 words per segment): Every segment MUST be short and punchy (1.0 to 1.8 seconds max duration). NEVER group more than 4 words into a single line! When the speaker finishes a 2-4 word breath/clause, start the next segment immediately so the on-screen text keeps up with their mouth!\n"
                "2. EXACT ONSET TIMESTAMPS: The start time MUST match the exact millisecond the speaker begins vocalizing the first syllable (or 50ms early when lips move). Do NOT start late.\n"
                "3. PRECISE TO MILLISECONDS: Use exact milliseconds (e.g. 00:01.230, 00:02.850). Do NOT round everything to .000 or .500.\n"
                "4. NATURAL KHMER PHRASING: In Khmer text, write naturally with proper phrasing (e.g. 'សួស្តីបងប្អូនទាំងអស់គ្នា', 'ថ្ងៃនេះ ខ្ញុំមកបង្ហាញពីវិធីរកលុយ'). Do NOT add artificial spaces between every single syllable.\n"
                "5. OPTIONAL SFX: Tag high-impact words with [sfx:cash], [sfx:ding], [sfx:buzzer], [sfx:tada], [sfx:click], [sfx:camera], [sfx:sparkle], [sfx:riser], [sfx:heartbeat], [sfx:thud], [sfx:pop]."
            )

            import concurrent.futures

            def _call_model(m_name):
                return self.client.models.generate_content(
                    model=m_name,
                    contents=[uploaded_file, prompt],
                    config=types.GenerateContentConfig(
                        temperature=0.1
                    )
                )

            models_to_try = [
                "gemini-3-flash-preview",
                "gemini-3.5-flash",
                "gemini-2.5-flash-lite",
                "gemini-3.1-flash-lite",
                "gemini-2.5-flash"
            ]

            response = None
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=len(models_to_try))
            try:
                for model_name in models_to_try:
                    try:
                        logger.info(f"Google Gemini កំពុងដំណើរការជាមួយម៉ូដែល: {model_name}...")
                        future = executor.submit(_call_model, model_name)
                        # កំណត់ Timeout 90 វិនាទី (គ្រប់គ្រាន់សម្រាប់វីដេអូ 2-5 នាទី មិនបោះបង់ចោលកណ្តាលទី)
                        response = future.result(timeout=45)
                        if response and response.text:
                            logger.info(f"✨ ជោគជ័យជាមួយម៉ូដែល: {model_name}!")
                            break
                    except concurrent.futures.TimeoutError:
                        logger.warning(f"⚠️ {model_name} លើសពី 90 វិនាទី (Timeout)! កំពុងប្ដូរទៅជម្រើសបន្ទាប់...")
                    except Exception as m_err:
                        logger.warning(f"⚠️ {model_name} ជួបបញ្ហា ({str(m_err)[:100]}). កំពុងប្ដូរទៅម៉ូដែលបន្ទាប់...")
            finally:
                # wait=False ការពារកុំឱ្យគាំង Thread ដាច់ខាត!
                executor.shutdown(wait=False, cancel_futures=True)

            # ប្រសិនបើគ្រប់ម៉ូដែល Cloud អស់ Quota ឬ Timeout -> ដំណើរការដោយ Local Whisper ភ្លាមៗ
            if not response or not response.text:
                logger.warning("🚨 Gemini Cloud យឺត ឬអស់ Quota! កំពុងប្ដូរទៅ Local Faster-Whisper ល្បឿនលឿនភ្លាមៗ...")
                return self._fallback_local_transcribe(upload_target, language)

            raw_text = response.text.strip()
            # សម្អាត markdown block បើមាន
            raw_text = re.sub(r"^```(?:srt|txt|json)?\s*", "", raw_text, flags=re.MULTILINE)
            raw_text = re.sub(r"\s*```$", "", raw_text, flags=re.MULTILINE).strip()

            self.hook_title = ""
            self.detected_language = "km"
            words_data = []

            # 1. ព្យាយាម Parse តាមទម្រង់ SRT / Timestamp Arrow (00:00.000 --> 00:02.500)
            hook_t, det_lang, srt_segments = parse_srt_or_arrow_transcript(raw_text, max_dur=audio_duration_sec or 3600.0)
            if srt_segments:
                logger.info(f"✨ Parse SRT / Timestamp Arrow បានជោគជ័យ: រកឃើញ {len(srt_segments)} segments!")
                self.hook_title = hook_t
                self.detected_language = det_lang
                words_data = srt_segments
            else:
                # 2. Fallback: Parse តាម JSON ប្រសិនបើ Model ឆ្លើយតបជា JSON
                try:
                    parsed_json = json.loads(raw_text)
                    if isinstance(parsed_json, dict):
                        self.hook_title = str(parsed_json.get("hook_title", "")).strip()
                        self.detected_language = str(parsed_json.get("language", "auto")).lower().strip()
                        words_data = parsed_json.get("segments", []) or parsed_json.get("words", [])
                    elif isinstance(parsed_json, list):
                        words_data = parsed_json
                    logger.info(f"✨ Parse JSON បានជោគជ័យ: រកឃើញ {len(words_data)} segments!")
                except Exception as json_err:
                    logger.warning(f"Parse SRT & JSON warnings: {json_err}")

            cleaned_words = []
            for item in words_data:
                w = str(item.get("word", "")).strip()
                sfx = item.get("sfx")

                # Strip any <sfx .../> or XML/HTML tags from text
                sfx_match = re.search(r'<sfx\s+name=["\']?(\w+)["\']?\s*/?>', w, re.IGNORECASE)
                if sfx_match and not sfx:
                    sfx = sfx_match.group(1).lower()
                w = re.sub(r'<[^>]+>', '', w).strip()
                w = re.sub(r'\s+', ' ', w).strip()
                s = float(item.get("start", 0.0))
                e = float(item.get("end", s + 0.8))
                # Lead-in anticipation 60ms ឱ្យអក្សរលេចឡើងដំណាលគ្នានឹងចលនាបបូរមាត់
                s = max(0.0, s - 0.06)
                sfx = item.get("sfx")

                # Keyword-based SFX reinforcement (ស្វែងរក Sound Effect ដោយស្វ័យប្រវត្តិតាមពាក្យខ្មែរ)
                if not sfx:
                    w_lower = w.lower()
                    if any(k in w_lower for k in ["លុយ", "ដុល្លារ", "លក់", "ចំណេញ", "ថ្លៃ", "ទិញ", "ចំណូល", "ទ្រព្យ", "money", "cash", "dollar", "profit", "rich", "income", "sales"]):
                        sfx = "cash"
                    elif any(k in w_lower for k in ["គន្លឹះ", "វិធី", "គំនិត", "មេរៀន", "យុទ្ធសាស្ត្រ", "tip", "idea", "secret", "how to", "technique", "smart"]):
                        sfx = "ding"
                    elif any(k in w_lower for k in ["កុំ", "ខុស", "ហាម", "ប្រយ័ត្ន", "ខាត", "គ្រោះថ្នាក់", "ចាញ់", "no", "don't", "dont", "never", "wrong", "mistake", "stop", "danger"]):
                        sfx = "buzzer"
                    elif any(k in w_lower for k in ["ជោគជ័យ", "ឈ្នះ", "លេខ១", "រួចរាល់", "អបអរ", "កំពូល", "win", "success", "winner", "congrats", "celebrate", "perfect"]):
                        sfx = "tada"
                    elif any(k in w_lower for k in ["ជំហាន", "ចុច", "ទូរស័ព្ទ", "app", "វេបសាយ", "កូដ", "click", "download", "link", "phone", "website", "code"]):
                        sfx = "click"
                    elif any(k in w_lower for k in ["មើល", "ឃើញ", "រូបភាព", "ថត", "ភស្តុតាង", "look", "see", "watch", "photo", "camera", "proof"]):
                        sfx = "camera"
                    elif any(k in w_lower for k in ["សម្ងាត់", "អស្ចារ្យ", "ពិសេស", "វេទមន្ត", "ស្រស់ស្អាត", "magic", "amazing", "incredible", "beautiful", "wow"]):
                        sfx = "sparkle"
                    elif any(k in w_lower for k in ["តើ", "ហេតុអ្វី", "យ៉ាងណា", "អាថ៌កំបាំង", "why", "how", "what", "mystery", "question"]):
                        sfx = "riser"
                    elif any(k in w_lower for k in ["ភ័យ", "បេះដូង", "រំភើប", "តក់ស្លុត", "ខ្លាច", "fear", "heart", "shock", "scary"]):
                        sfx = "heartbeat"
                    elif any(k in w_lower for k in ["សំខាន់", "ចាំបាច់", "ធ្ងន់ធ្ងរ", "ច្បាស់", "important", "critical", "must"]):
                        sfx = "thud"

                if audio_duration_sec > 0:
                    if s >= audio_duration_sec:
                        continue
                    e = min(e, audio_duration_sec)

                if w and e > s:
                    word_obj = {
                        "word": w,
                        "start": s,
                        "end": e
                    }
                    if sfx:
                        word_obj["sfx"] = sfx
                    cleaned_words.append(word_obj)

            logger.info(f"Gemini បំប្លែងបានជោគជ័យ! រកឃើញ {len(cleaned_words)} ឃ្លា (Hook: {self.hook_title or 'N/A'})")
            # ប្រសិនបើបាន Parse ចេញពី SRT ផ្ទាល់ មិនត្រូវ merge ឱ្យវែងឡើយ ដើម្បីឱ្យអក្សរលោតទាន់មាត់អ្នកនិយាយ ១០០%
            if srt_segments:
                return cleaned_words
            return group_into_natural_phrases(cleaned_words)

        except Exception as overall_err:
            logger.warning(f"🚨 ដំណើរការ Gemini Cloud ជួបបញ្ហា ({overall_err})! ប្ដូរទៅ Local Faster-Whisper ដោយស្វ័យប្រវត្តិ...")
            return self._fallback_local_transcribe(upload_target, language)
        finally:
            # លុបឯកសារបណ្ដោះអាសន្នចេញ
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



    def extract_visual_story_scenes(self, words: List[Dict]) -> List[Dict]:
        """
        វិភាគអត្ថបទ Subtitle ជាក់ស្តែង ដើម្បីជ្រើសរើសប្លង់ Motion Explainer & Real B-Roll ច្នៃប្រឌិតខ្ពស់
        (មិនច្រំដែល មិនបង្ខំ STEP 1, 2, 3 និងមិនចម្លងគំរូ Tech ដដែលៗ)៖
        - "polaroid": រូបថតពិតក្នុងស៊ុម Polaroid ពណ៌ស ផ្អៀងតិចៗបែបសិល្បៈ + Caption ខាងក្រោម (ស័ក្តិសមបំផុតសម្រាប់ម្ហូប, មនុស្ស, វត្ថុ, អនុស្សាវរីយ៍)
        - "cinematic_broll": រូបថតពិតកម្រិតច្បាស់ពេញអេក្រង់ កាត់ប្តូរបែបភាពយន្ត Ken Burns + ស្លាក Pill បាតក្រោម
        - "glass_pill": ស្លាកកញ្ចក់ថ្លា Minimalist Glassmorphism អណ្តែតនៅជ្រុងលើ (គន្លឹះ, Feedback, ចំណាំ) មិនបាំងមុខអ្នកនិយាយ
        - "kinetic_stamp": អក្សររំលេចធំៗលោតបែប Dynamic Highlighter បុកខ្លាំងលើឃ្លាភ្ញាក់ផ្អើល ឬអារម្មណ៍សំខាន់
        - "floating_card": កាតទំនើបបែប Notion Card ពេលរៀបរាប់គ្រឿងផ្សំ ឬឧបករណ៍
        - "comparison": ការប្រៀបធៀប A vs B ពេលមានការផ្ទុយគ្នាជាក់ស្តែង
        """
        if not words:
            return []

        transcript_lines = []
        for w in words:
            transcript_lines.append(f"[{w.get('start', 0):.2f}s - {w.get('end', 0):.2f}s]: {w.get('word', '')}")
        full_transcript = "\n".join(transcript_lines)
        total_duration = max([w.get('end', 0) for w in words]) if words else 30

        # Tasteful dynamic scene count (2 to 4 scenes for high retention, not clutter)
        if total_duration < 25:
            target_scenes = 2
        elif total_duration < 55:
            target_scenes = 3
        else:
            target_scenes = 4

        prompt = f"""You are an award-winning creative video director (like Vox, Johnny Harris, Ali Abdaal, and elite TikTok/Reels creators).
Here is the word-by-word transcript of a vertical short-form video in Khmer (or multilingual):
{full_transcript}

Video duration: {total_duration:.1f} seconds.

CREATIVE MISSION:
1. Deeply understand the TRUE TOPIC & EMOTION of this video (e.g. Cooking/Food/Recipes, Lifestyle/Personal story, Business/Finance, Health/Fitness, Humor, Education, etc.).
2. Generate exactly {target_scenes} UNIQUE, HIGHLY CREATIVE, AND VISUALLY DIVERSE Motion Explainer scenes that perfectly match what the speaker is saying at that exact second!
3. CRITICAL ANTI-REPETITION RULES:
   - DO NOT USE THE SAME ARCHETYPE TWICE IN A ROW! Alternate styles for maximum visual engagement.
   - DO NOT force "STEP 1, STEP 2, STEP 3" unless the speaker is literally giving a numbered step-by-step tutorial! For stories, food, or lifestyle, leave "step_badge" as empty string "".
   - NEVER generate generic corporate tech terms like 'Ads Manager', 'GA4', or 'export.csv' unless the speaker is explicitly teaching digital marketing!
   - NO AI FANTASY ART! All photos must be realistic real-world photography.

AVAILABLE 3 VISUAL LAYOUTS ONLY:
1. "split_screen": Split-Screen (50/50: Top 50% is real B-Roll photo with smooth Ken Burns zoom, Bottom 50% is speaker talking head with glowing divider line). PERFECT for showing food, dish, action, or item while keeping the speaker visible.
2. "cinematic_broll": Fullscreen 100% realistic photography cutaway with cinematic slow zoom and sleek lower caption pill.
3. "talking_head": Fullscreen speaker video with dynamic animated subtitles.

FIELDS TO OUTPUT FOR EACH SCENE:
- "start" and "end": float timestamps (duration 3.0s to 4.2s per scene, spaced out across the video timeline, no overlaps).
- "layout": one of ["split_screen", "cinematic_broll", "talking_head"].
- "step_badge": "" (or "STEP 1" ONLY IF explicitly a numbered tutorial).
- "topic": concise descriptive Khmer phrase for what is happening.
- "highlight_word": the single punchiest Khmer keyword/punchline.
- "headline_prefix": short prefix in Khmer if applicable, or "".
- "headline_suffix": short suffix in Khmer if applicable, or "".
- "caption": warm caption text for Polaroid (e.g. "កាជ្យូវទឹកខ្មៅពិសេស 🦑" or "រសជាតិឆ្ងាញ់ប្លែក").
- "pill_category": category for glass pill (e.g. "💡 គន្លឹះពិសេស", "⭐ FEEDBACK អតិថិជន", "📌 ចំណាំ").
- "pill_text": clean 1-line text for glass pill.
- "floating_icon": one of ["food", "feedback", "star", "heart", "fire", "bulb", "sparkle", "money", "chart"].
- "accent_color": vibrant hex color (e.g. "#FFE600" yellow, "#10B981" mint, "#F43F5E" coral, "#06B6D4" cyan, "#F59E0B" amber).
- "search_query": 2 to 4 concrete descriptive English photography search keywords to fetch real stock photography (e.g. "cooked squid dish Asian dinner", "happy customer message phone", "delicious spicy seafood meal").

Output strictly a valid JSON array of objects.
Do not wrap in markdown code blocks, just raw JSON.
"""
        response = None
        for m_name in ["gemini-3-flash-preview", "gemini-3.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-flash"]:
            try:
                response = self.client.models.generate_content(
                    model=m_name,
                    contents=prompt
                )
                if response and response.text:
                    break
            except Exception as evss_err:
                logger.warning(f"Scene extraction {m_name} warning: {evss_err}")

        try:
            if not response or not response.text:
                raise RuntimeError("All Gemini models failed for scene extraction")
            raw_text = response.text.strip()
            if "```" in raw_text:
                raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text, flags=re.MULTILINE)
                raw_text = re.sub(r"```$", "", raw_text, flags=re.MULTILINE).strip()
            scenes = json.loads(raw_text)
            logger.info(f"✨ Gemini បានបង្កើត {len(scenes)} Motion Explainer Scenes ច្នៃប្រឌិតខ្ពស់ និងមិនច្រំដែល!")
            return scenes
        except Exception as e:
            logger.error(f"Error in extract_visual_story_scenes: {e}")
            fallback_scenes = []
            interval = total_duration / (target_scenes + 1)
            # Diverse archetypes for fallback
            fallback_archetypes = ["split_screen", "cinematic_broll"]
            # Extract sample text snippets from words
            all_text = " ".join([w.get("word", "") for w in words])
            for i in range(1, target_scenes + 1):
                st = round(i * interval, 1)
                arch = fallback_archetypes[(i - 1) % len(fallback_archetypes)]
                w_idx = min(len(words) - 1, int(len(words) * (i / (target_scenes + 1))))
                sample_word = words[w_idx].get("word", "ចំណុចពិសេស") if words else "ចំណុចពិសេស"
                fallback_scenes.append({
                    "start": st,
                    "end": min(total_duration, round(st + 3.8, 1)),
                    "layout": arch,
                    "step_badge": "",
                    "topic": sample_word,
                    "highlight_word": sample_word,
                    "headline_prefix": "",
                    "headline_suffix": "",
                    "caption": sample_word,
                    "pill_category": "💡 គន្លឹះសំខាន់",
                    "pill_text": sample_word,
                    "floating_icon": "sparkle" if i % 2 == 0 else "star",
                    "accent_color": "#FFE600" if i % 2 == 1 else "#10B981",
                    "search_query": "lifestyle creative moments"
                })
            return fallback_scenes


    def _fallback_local_transcribe(self, audio_or_video_path: str, language: Optional[str] = "km") -> List[Dict]:
        """ដំណើរការដោយ Local Faster-Whisper នៅពេល Gemini Cloud API អស់ Quota (១០០% មិនគិតថ្លៃ និងមិនទាមទារ Quota)"""
        from transcriber import AudioTranscriber
        logger.info("🎙️ កំពុងដំណើរការ Local Whisper Speech-to-Text ជំនួស...")
        local_t = AudioTranscriber(model_size="base", device="cpu", compute_type="int8")
        words = local_t.transcribe(audio_or_video_path, language=language)

        cleaned_words = []
        foreign_filter = re.compile(r'[\u0E00-\u0E7F\u0E80-\u0EFF\u4E00-\u9FFF\u0900-\u0D7F]')
        for w_obj in words:
            w = str(w_obj.get("word", "")).strip()
            s = float(w_obj.get("start", 0.0))
            e = float(w_obj.get("end", s + 0.8))

            if not w or e <= s:
                continue

            # Strip any Thai, Lao, Chinese, or Indic hallucination
            if foreign_filter.search(w):
                continue

            # Skip gibberish / repetition loops like "-4", "ฆ่า", etc.
            if re.match(r'^(?:-?\d+\s*)+$', w) or len(w) <= 1:
                continue

            sfx = None
            if any(k in w for k in ["លុយ", "ដុល្លារ", "លក់", "ចំណេញ", "ថ្លៃ", "ទិញ", "ចំណូល", "ទ្រព្យ"]):
                sfx = "cash"
            elif any(k in w for k in ["គន្លឹះ", "វិធី", "គំនិត", "មេរៀន", "យុទ្ធសាស្ត្រ"]):
                sfx = "ding"
            elif any(k in w for k in ["កុំ", "ខុស", "ហាម", "ប្រយ័ត្ន", "ខាត", "គ្រោះថ្នាក់", "ចាញ់", "កុំធ្វើ"]):
                sfx = "buzzer"
            elif any(k in w for k in ["ជោគជ័យ", "ឈ្នះ", "លេខ១", "រួចរាល់", "អបអរ", "កំពូល"]):
                sfx = "tada"
            elif any(k in w for k in ["ជំហាន", "ចុច", "ទូរស័ព្ទ", "App", "វេបសាយ", "កូដ"]):
                sfx = "click"
            elif any(k in w for k in ["មើល", "ឃើញ", "រូបភាព", "ថត", "ភស្តុតាង"]):
                sfx = "camera"
            elif any(k in w for k in ["សម្ងាត់", "អស្ចារ្យ", "ពិសេស", "វេទមន្ត", "ស្រស់ស្អាត"]):
                sfx = "sparkle"
            elif any(k in w for k in ["តើ", "ហេតុអ្វី", "យ៉ាងណា", "អាថ៌កំបាំង"]):
                sfx = "riser"
            elif any(k in w for k in ["ភ័យ", "បេះដូង", "រំភើប", "តក់ស្លុត", "ខ្លាច"]):
                sfx = "heartbeat"
            elif any(k in w for k in ["សំខាន់", "ចាំបាច់", "ធ្ងន់ធ្ងរ", "ច្បាស់"]):
                sfx = "thud"

            item = {"word": w, "start": s, "end": e}
            if sfx:
                item["sfx"] = sfx
            cleaned_words.append(item)

        logger.info(f"✨ Local Whisper បំប្លែងបានជោគជ័យ! រកឃើញ {len(cleaned_words)} ពាក្យ (ជាមួយ Auto SFX)")
        return group_into_natural_phrases(cleaned_words)
