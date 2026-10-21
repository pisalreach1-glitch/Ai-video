import os
import subprocess
import logging
from typing import Optional
from utils import get_ffmpeg_path
from transcriber import AudioTranscriber
from subtitle_generator import generate_animated_ass

logger = logging.getLogger(__name__)

class VideoProcessor:
    def __init__(self, whisper_model: str = "small"):
        self.ffmpeg_path = get_ffmpeg_path()
        self.transcriber = AudioTranscriber(model_size=whisper_model)
        
        # ពិនិត្យមើល Gemini API Key
        self.gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
        self.gemini_transcriber = None
        if self.gemini_key:
            try:
                from gemini_transcriber import GeminiTranscriber
                self.gemini_transcriber = GeminiTranscriber(api_key=self.gemini_key)
                logger.info("Google Gemini Transcriber បានភ្ជាប់រួចរាល់ សម្រាប់ភាសាខ្មែរ!")
            except Exception as e:
                logger.warning(f"មិនអាចបង្កើត GeminiTranscriber: {e}")

    def process_video(
        self,
        input_video_path: str,
        output_video_path: str,
        language: Optional[str] = None,
        font_key: Optional[str] = None
    ) -> str:
        """
        ដំណើរការវីដេអូពេញលេញ៖
        1. ស្ដាប់សំឡេងទាញយក Timestamp (AI Speech-to-Text) ប្រើ Gemini (សម្រាប់ខ្មែរ) ឬ Whisper
        2. បង្កើត Subtitle លោតតាមពាក្យ (Animated ASS Captions)
        3. Burn Subtitle ចូលក្នុងវីដេអូដោយប្រើ FFmpeg
        """
        base_dir = os.path.dirname(input_video_path)
        base_name = os.path.splitext(os.path.basename(input_video_path))[0]
        ass_path = os.path.join(base_dir, f"{base_name}_captions.ass")

        # ជំហានទី ១: AI Transcribe
        words = []
        if language == "km" and self.gemini_transcriber:
            logger.info("ជំហានទី ១: កំពុងប្រើ Google Gemini Flash សម្រាប់ភាសាខ្មែរ...")
            try:
                words = self.gemini_transcriber.transcribe(input_video_path, language="km")
            except Exception as e:
                logger.error(f"Gemini error: {e}។ កំពុងប្ដូរទៅ Whisper...")

        if not words:
            logger.info("ជំហានទី ១: AI Whisper កំពុងវិភាគពាក្យ និងសំឡេង...")
            words = self.transcriber.transcribe(input_video_path, language=language)

        if not words:
            logger.warning("មិនរកឃើញសម្ដីនិយាយក្នុងវីដេអូទេ!")
            return input_video_path

        # ជំហានទី ២: បង្កើត Animated Subtitle (.ass)
        logger.info(f"ជំហានទី ២: កំពុងរៀបចំ Animated Subtitles (Font: {font_key or 'default'})...")
        generate_animated_ass(words, ass_path, language=language, font_key=font_key)

        # ជំហានទី ៣: Burn Subtitles ចូលវីដេអូដោយ FFmpeg
        logger.info("ជំហានទី ៣: FFmpeg កំពុង Render វីដេអូ...")
        
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

        logger.info(f"Running FFmpeg: {' '.join(cmd)}")
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        if result.returncode != 0:
            logger.error(f"FFmpeg error: {result.stderr}")
            raise RuntimeError(f"FFmpeg ជួបបញ្ហាពេល Render: {result.stderr[-400:]}")

        # សម្អាត file .ass បណ្ដោះអាសន្ន
        if os.path.exists(ass_path):
            try:
                os.remove(ass_path)
            except Exception:
                pass

        logger.info(f"Render វីដេអូបានជោគជ័យ: {output_video_path}")
        return output_video_path
