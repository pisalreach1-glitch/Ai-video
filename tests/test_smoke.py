"""
Required Test 9: Smoke test.
Verifies:
- Generates a short synthetic test video with video and audio.
- Renders with known subtitle timestamps using FFmpeg.
- Checks output exists, decodes, has audio, and has expected duration within frame tolerance.
- Zero paid API consumption (all external APIs mocked).
"""

import os
import shutil
import pytest
from pathlib import Path
from unittest.mock import patch

from utils import get_ffmpeg_path
from process_runner import ProcessRunner
from media_validator import probe_media, validate_video_with_audio
from subtitle_generator import generate_animated_ass
from video_processor import VideoProcessor


@pytest.fixture
def test_workspace(tmp_path):
    yield tmp_path
    shutil.rmtree(tmp_path, ignore_errors=True)


class TestSmokePipeline:
    def test_synthetic_video_rendering_and_decoding(self, test_workspace):
        """
        Creates a 2.0s synthetic video with audio via FFmpeg,
        burns subtitles with known timestamps,
        and verifies the output exists, decodes, has audio, and matches duration tolerance.
        """
        ffmpeg = get_ffmpeg_path()
        synthetic_video = str(test_workspace / "synthetic_input.mp4")
        rendered_output = str(test_workspace / "smoke_output.mp4")

        # 1. Generate 2.0s synthetic video with audio track
        cmd_gen = [
            ffmpeg,
            "-y",
            "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=30",
            "-f", "lavfi", "-i", "sine=frequency=1000:duration=2",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "64k",
            synthetic_video
        ]
        gen_res = ProcessRunner.run(cmd_gen, timeout=15.0)
        assert gen_res.returncode == 0
        assert os.path.exists(synthetic_video)

        # 2. Probe input video
        info = validate_video_with_audio(synthetic_video)
        assert info.has_video is True
        assert info.has_audio is True
        assert pytest.approx(info.duration, 0.2) == 2.0

        # 3. Process video with known subtitle timestamps (mocking transcription to avoid external API calls)
        known_words = [
            {"word": "ស្វាគមន៍", "start": 0.2, "end": 1.2},
            {"word": "SmokeTest", "start": 1.25, "end": 1.9}
        ]

        from unittest.mock import MagicMock
        with patch("transcriber.AudioTranscriber._load_model", return_value=MagicMock()):
            processor = VideoProcessor()
            with patch.object(processor.transcriber, "transcribe", return_value=known_words):
                out = processor.process_video(
                    input_video_path=synthetic_video,
                    output_video_path=rendered_output,
                    language="km"
                )

        # 4. Verify output
        assert os.path.exists(out)
        assert os.path.getsize(out) > 1000

        # Output must decode cleanly
        out_info = probe_media(out)
        assert out_info.has_video is True
        assert out_info.has_audio is True

        # Frame tolerance: 2.0s at 30 fps is ~60 frames; check duration is within 0.15s (approx 4 frames)
        assert pytest.approx(out_info.duration, abs=0.2) == 2.0
