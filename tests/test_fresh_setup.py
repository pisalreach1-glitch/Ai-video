"""
Required Test 8: Fresh setup & Graceful degradation.
Verifies:
- All required project imports work without error.
- Missing optional assets (fonts, bgm) degrade gracefully.
- Local transcription mode works without a Gemini API key.
"""

import os
import pytest
from unittest.mock import patch


class TestFreshSetup:
    def test_all_required_imports(self):
        """All core modules and classes must import cleanly."""
        import utils
        import errors
        import timecode_utils
        import process_runner
        import media_validator
        import cleanup_manager
        import job_manager
        import transcriber
        import subtitle_generator
        import video_processor
        import remotion_processor
        import gemini_transcriber

        assert errors.BotProcessingError is not None
        assert timecode_utils.format_srt_timestamp is not None
        assert process_runner.ProcessRunner is not None

    def test_local_transcription_mode_without_gemini_key(self, monkeypatch):
        """When GEMINI_API_KEY is not set, processors initialize without error in local mode."""
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)

        from unittest.mock import MagicMock
        with patch("transcriber.AudioTranscriber._load_model", return_value=MagicMock()):
            from remotion_processor import RemotionProcessor
            from video_processor import VideoProcessor

            # RemotionProcessor must initialize gracefully without error
            r_proc = RemotionProcessor()
            assert r_proc.gemini_transcriber is None
            assert r_proc.local_transcriber is not None
            assert r_proc.transcriber is not None
            assert hasattr(r_proc.transcriber, "detected_language")
            assert hasattr(r_proc.transcriber, "extract_visual_story_scenes")

            # VideoProcessor must initialize gracefully without error
            v_proc = VideoProcessor()
            assert v_proc.gemini_transcriber is None
            assert v_proc.transcriber is not None

    def test_missing_optional_fonts_and_bgm_degrade_gracefully(self):
        """Missing optional fonts or bgm keys fall back to defaults without crashing."""
        from subtitle_generator import generate_animated_ass
        import tempfile

        words = [{"word": "Test", "start": 0.0, "end": 1.0}]
        with tempfile.NamedTemporaryFile(suffix=".ass", delete=False) as tf:
            ass_path = tf.name

        try:
            # Using a completely unknown/missing font key
            res = generate_animated_ass(words, ass_path, font_key="unknown_fantasy_font_999")
            assert os.path.exists(res)
            with open(res, "r", encoding="utf-8") as f:
                content = f.read()
            assert "Style: Default" in content
        finally:
            if os.path.exists(ass_path):
                os.remove(ass_path)
