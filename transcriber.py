import os
import logging
from typing import List, Dict, Optional

# បិទការព្រមាន Symlink លើ Windows របស់ HuggingFace
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

# កែសម្រួលភាពត្រូវគ្នាជាមួយ PyAV (av) កំណែថ្មីដែលលុប 'metadata_errors'
try:
    import av
    _orig_av_open = av.open
    def _safe_av_open(*args, **kwargs):
        kwargs.pop("metadata_errors", None)
        return _orig_av_open(*args, **kwargs)
    av.open = _safe_av_open
except ImportError:
    pass

from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)

class AudioTranscriber:
    def __init__(self, model_size: str = "base", device: str = "cpu", compute_type: str = "int8"):
        """
        AI Speech-to-Text Transcriber ប្រើ Faster-Whisper
        - device="cpu", compute_type="int8": ដំណើរការលឿន ស្រាល និងមិនទាមទារ CUDA DLL
        """
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.detected_language = 'km'
        self.model = self._load_model(device, compute_type)

    def _load_model(self, device: str, compute_type: str):
        try:
            logger.info(f"កំពុងផ្ទុកម៉ូដែល Whisper: {self.model_size} ({device}, {compute_type})...")
            model = WhisperModel(self.model_size, device=device, compute_type=compute_type)
            logger.info("ម៉ូដែល Whisper រួចរាល់សម្រាប់ការប្រើប្រាស់!")
            return model
        except Exception as e:
            logger.warning(f"មិនអាចផ្ទុកលើ {device} ({e}) បានទេ! កំពុងប្ដូរទៅ CPU int8...")
            self.device = "cpu"
            self.compute_type = "int8"
            return WhisperModel(self.model_size, device="cpu", compute_type="int8")

    def transcribe(self, audio_or_video_path: str, language: Optional[str] = None) -> List[Dict]:
        """
        បំប្លែងសំឡេងជាអក្សរ និងទាញយក timestamp កម្រិតពាក្យនីមួយៗ (Word-level timestamps)
        """
        try:
            return self._do_transcribe(audio_or_video_path, language)
        except Exception as e:
            err_str = str(e).lower()
            if "cublas" in err_str or "cuda" in err_str:
                logger.warning(f"CUDA Error ({e})! កំពុងដំណើរការឡើងវិញលើ CPU...")
                self.device = "cpu"
                self.compute_type = "int8"
                self.model = WhisperModel(self.model_size, device="cpu", compute_type="int8")
                return self._do_transcribe(audio_or_video_path, language)
            raise

    def _do_transcribe(self, audio_or_video_path: str, language: Optional[str] = None) -> List[Dict]:
        logger.info(f"កំពុងដំណើរការ Transcribing: {audio_or_video_path} (Language: {language})")
        
        # បង្ខំ AI ឱ្យផ្ដោតលើអក្សរខ្មែរសុទ្ធ មិនឱ្យច្រឡំទៅអក្សរឥណ្ឌា/Telugu
        initial_prompt = None
        if language == "km":
            initial_prompt = "សួស្តី នេះគឺជាវីដេអូនាយាយជាភាសាខ្មែរ អក្សរខ្មែរពិតប្រាកដ។"

        segments, info = self.model.transcribe(
            audio_or_video_path,
            beam_size=5,
            word_timestamps=True,
            language="km" if (not language or language == "km") else language,
            initial_prompt="សួស្តី នេះជាវីដេអូនាយាយភាសាខ្មែរពិតប្រាកដ។",
            vad_filter=True,
            condition_on_previous_text=False,
            no_speech_threshold=0.55,
            compression_ratio_threshold=2.4
        )

        # Regex កម្ចាត់អក្សរថៃ (Thai), ឡាវ (Lao), ឥណ្ឌា (Indic), ចិន (Chinese) ដែល Whisper Hallucinate 100%
        import re
        foreign_hallucination_regex = re.compile(r'[ऀ-ൿ฀-๿຀-໿一-鿿]')

        all_words: List[Dict] = []
        last_word = ""
        repeat_count = 0

        for segment in segments:
            if segment.words:
                for word_info in segment.words:
                    word_clean = word_info.word.strip()
                    # សម្អាតអក្សរថៃ/ឡាវ/ចិន ដែល Whisper hallucinate ចេញជាដាច់ខាត
                    word_clean = foreign_hallucination_regex.sub("", word_clean).strip()

                    # ទប់ស្កាត់ពាក្យដដែលៗរាប់សិបដង (Repetitive Hallucination filter)
                    if word_clean == last_word and len(word_clean) <= 4:
                        repeat_count += 1
                        if repeat_count > 2:
                            continue
                    else:
                        last_word = word_clean
                        repeat_count = 0

                    if word_clean:
                        all_words.append({
                            "word": word_clean,
                            "start": word_info.start,
                            "end": word_info.end,
                            "probability": getattr(word_info, "probability", 1.0)
                        })

        logger.info(f"ដំណើរការចប់! រកឃើញ {len(all_words)} ពាក្យ។ ភាសាក្នុងវីដេអូ: {info.language}")
        self.detected_language = getattr(info, "language", "km") or "km"
        return all_words

    def extract_visual_story_scenes(self, words: List[Dict], user_prompt: Optional[str] = None) -> List[Dict]:
        """Fallback visual story scenes when Gemini is offline or unavailable."""
        try:
            from gemini_transcriber import GeminiTranscriber
            return GeminiTranscriber(api_key="").extract_visual_story_scenes(words)
        except Exception:
            total_duration = max([w.get("end", 0) for w in words]) if words else 30
            return [
                {
                    "layout": "polaroid",
                    "start": round(total_duration * 0.15, 2),
                    "end": round(total_duration * 0.40, 2),
                    "topic": "ចំណុចសំខាន់ (Key Point)",
                    "highlightWord": words[0]["word"] if words else "Highlight",
                    "imagePrompt": "minimalist aesthetic vertical cinematic photography",
                    "sound": "whoosh"
                }
            ]
