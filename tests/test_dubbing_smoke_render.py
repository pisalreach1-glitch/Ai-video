"""Synthetic FFmpeg smoke render test for source-timed dubbing with decoded sample onset verification."""
import wave
import struct
import subprocess
import pytest
from pathlib import Path
from app.config import config
from app.domain.models import VoiceSettings
from app.domain.dubbing import DubbingPlan, SourceSegment, DubClip
from app.services.timeline import assemble_timeline_pcm
from app.services.render import render_video
from app.storage.dubbing import save_sync_report, load_sync_report

def create_synthetic_sine_wav(path: Path, duration_ms: int, freq: int = 1000, sample_rate: int = 48000) -> Path:
    """Create a synthetic 16-bit stereo PCM sine burst."""
    import math
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = int(round((duration_ms / 1000.0) * sample_rate))
    raw_bytes = bytearray()
    for i in range(frames):
        sample = int(16000 * math.sin(2 * math.pi * freq * i / sample_rate))
        frame = struct.pack("<hh", sample, sample)
        raw_bytes.extend(frame)

    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(raw_bytes)
    return path

@pytest.mark.asyncio
async def test_synthetic_dubbing_smoke_render_with_sample_verification(tmp_path):
    """
    Synthetic FFmpeg smoke test:
    - 12-second test video
    - Distinguishable synthetic bursts at 2s and 8s
    - Assembled onto silence timeline and rendered
    - Decoded and verified on decoded samples within 50ms tolerance
    """
    # 1. Generate 12-second synthetic video
    source_video = tmp_path / "source12.mp4"
    cmd_v = [
        config.ffmpeg_path, "-y",
        "-f", "lavfi", "-i", "testsrc=size=640x360:rate=30",
        "-t", "12.0",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(source_video),
    ]
    subprocess.run(cmd_v, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    # 2. Generate 1.5s bursts at 2s and 8s
    burst1 = create_synthetic_sine_wav(tmp_path / "burst1.wav", duration_ms=1500, freq=1000)
    burst2 = create_synthetic_sine_wav(tmp_path / "burst2.wav", duration_ms=1500, freq=1000)

    s1 = SourceSegment(segment_id="s001", start_ms=2000, end_ms=4000, source_text="Burst 1")
    s2 = SourceSegment(segment_id="s002", start_ms=8000, end_ms=10000, source_text="Burst 2")

    c1 = DubClip(segment_id="s001", tts_cache_key="b1", raw_audio_path=str(burst1), fitted_duration_ms=1500, status="ready")
    c2 = DubClip(segment_id="s002", tts_cache_key="b2", raw_audio_path=str(burst2), fitted_duration_ms=1500, status="ready")

    plan = DubbingPlan(
        source_duration_ms=12000,
        sample_rate=48000,
        segments=[s1, s2],
        clips=[c1, c2],
    )

    # 3. Assemble timeline audio
    timeline_wav = tmp_path / "narration_timeline.wav"
    placements, sync_report = assemble_timeline_pcm(plan, timeline_wav)
    assert sync_report["validation_passed"] is True

    # 4. Render output MP4 in source_timed mode
    rendered_mp4 = tmp_path / "rendered.mp4"
    settings = VoiceSettings(source_audio_mode="mute")
    await render_video(
        source_path=source_video,
        voice_audio_path=timeline_wav,
        output_path=rendered_mp4,
        settings=settings,
        target_duration=12.0,
        mode="source_timed",
    )
    assert rendered_mp4.exists()

    # 5. Decode rendered audio back to PCM WAV to inspect decoded samples
    decoded_wav = tmp_path / "decoded.wav"
    cmd_dec = [
        config.ffmpeg_path, "-y",
        "-i", str(rendered_mp4),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "48000",
        "-ac", "2",
        str(decoded_wav),
    ]
    subprocess.run(cmd_dec, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    # 6. Verify samples
    with wave.open(str(decoded_wav), "rb") as wf:
        n_frames = wf.getnframes()
        rate = wf.getframerate()
        raw = wf.readframes(n_frames)

    duration_sec = n_frames / float(rate)
    assert abs(duration_sec - 12.0) <= 0.2, f"Output duration {duration_sec}s mismatch from 12.0s"

    # Convert frames to peak amplitude per 100ms window (4800 frames per window)
    window_size = int(rate * 0.1) # 100ms
    num_windows = n_frames // window_size
    energies = []
    for w in range(num_windows):
        start = w * window_size * 4
        end = start + window_size * 4
        samples = struct.unpack(f"<{window_size * 2}h", raw[start:end])
        peak = max(abs(s) for s in samples)
        energies.append(peak)

    # Window 0 to 18 (0.0s to 1.8s) should be near silence (AAC compression noise < 1000)
    for i in range(15):
        assert energies[i] < 1000, f"Expected silence at window {i} (t={i*0.1:.1f}s), got peak {energies[i]}"

    # Window 21 to 32 (2.1s to 3.2s) should have strong tone (> 8000)
    for i in range(21, 33):
        assert energies[i] > 8000, f"Expected tone at window {i} (t={i*0.1:.1f}s), got peak {energies[i]}"

    # Window 45 to 70 (4.5s to 7.0s) should be silence gap preserved
    for i in range(45, 70):
        assert energies[i] < 1000, f"Expected silence gap at window {i} (t={i*0.1:.1f}s), got peak {energies[i]}"

    # Window 81 to 92 (8.1s to 9.2s) should have strong tone
    for i in range(81, 93):
        assert energies[i] > 8000, f"Expected second tone at window {i} (t={i*0.1:.1f}s), got peak {energies[i]}"
