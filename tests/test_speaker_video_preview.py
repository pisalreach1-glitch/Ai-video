"""Synthetic FFmpeg integration tests for multi-speaker original and dubbed previews."""
import math
import wave
import struct
import subprocess
import pytest
from pathlib import Path
from app.config import config
from app.domain.models import VoiceSettings
from app.domain.dubbing import DubbingPlan, SourceSegment, DubClip, TranslatedSegment
from app.domain.speakers import SpeakerTurn, SpeakerProfile, SpeakerAssignment, VoiceChoice
from app.services.timeline import assemble_timeline_pcm
from app.services.previews import render_timed_excerpt, render_full_preview_video


def create_sine_wav(path: Path, duration_ms: int, freq: int, sample_rate: int = 48000) -> Path:
    """Create a synthetic 16-bit stereo PCM sine burst at a specific frequency."""
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
async def test_synthetic_speaker_previews_and_full_timeline(tmp_path):
    """
    Section 13 Fixture:
    - 15-second source video with audio
    - Synthetic A/B/A speech turns at 2-4s, 7-9s, 11-13s
    - Speaker A tone: 440 Hz (low pitch)
    - Speaker B tone: 880 Hz (high pitch)
    - Renders original excerpt, dubbed excerpt, and full preview
    - Verifies onset positions, silence gaps, and audio presence
    """
    # 1. Generate 15-second synthetic source video with audio
    source_video = tmp_path / "source15.mp4"
    cmd_v = [
        config.ffmpeg_path, "-y",
        "-f", "lavfi", "-i", "testsrc=size=640x360:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=300:duration=15.0",
        "-t", "15.0",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(source_video),
    ]
    subprocess.run(cmd_v, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    # 2. Test Original video preview before any TTS exists (Criteria 8)
    orig_excerpt = tmp_path / "sample_orig_turn2.mp4"
    settings = VoiceSettings(aspect_ratio="original", source_audio_mode="mute")
    await render_timed_excerpt(
        source_path=source_video,
        assembled_audio_path=None,
        output_preview_path=orig_excerpt,
        settings=settings,
        start_sec=6.5,
        duration_sec=3.0,
        variant="original",
    )
    assert orig_excerpt.exists()
    assert orig_excerpt.stat().st_size > 1000

    # 3. Create synthetic audio clips for A/B/A:
    # A1 (2000-4000ms, 440Hz), B (7000-9000ms, 880Hz), A2 (11000-13000ms, 440Hz)
    wav_a1 = create_sine_wav(tmp_path / "a1.wav", duration_ms=1800, freq=440)
    wav_b = create_sine_wav(tmp_path / "b.wav", duration_ms=1800, freq=880)
    wav_a2 = create_sine_wav(tmp_path / "a2.wav", duration_ms=1800, freq=440)

    s1 = SourceSegment(segment_id="s001", start_ms=2000, end_ms=4000, source_text="Hello from A1", speaker_id="Speaker A")
    s2 = SourceSegment(segment_id="s002", start_ms=7000, end_ms=9000, source_text="Hello from B", speaker_id="Speaker B")
    s3 = SourceSegment(segment_id="s003", start_ms=11000, end_ms=13000, source_text="Hello from A2", speaker_id="Speaker A")

    c1 = DubClip(segment_id="s001", tts_cache_key="k_a1", raw_audio_path=str(wav_a1), fitted_duration_ms=1800, status="ready")
    c2 = DubClip(segment_id="s002", tts_cache_key="k_b", raw_audio_path=str(wav_b), fitted_duration_ms=1800, status="ready")
    c3 = DubClip(segment_id="s003", tts_cache_key="k_a2", raw_audio_path=str(wav_a2), fitted_duration_ms=1800, status="ready")

    plan = DubbingPlan(
        mode="source_timed",
        speaker_mode="multi",
        source_duration_ms=15000,
        sample_rate=48000,
        segments=[s1, s2, s3],
        translations=[
            TranslatedSegment(segment_id="s001", translated_text="សួស្តី A1"),
            TranslatedSegment(segment_id="s002", translated_text="សួស្តី B"),
            TranslatedSegment(segment_id="s003", translated_text="សួស្តី A2"),
        ],
        clips=[c1, c2, c3],
        speaker_voice_map={
            "Speaker A": VoiceChoice(voice_id="km-KH-SreymomNeural", confirmed=True),
            "Speaker B": VoiceChoice(voice_id="km-KH-PisethNeural", confirmed=True),
        },
    )

    timeline_wav = tmp_path / "timeline.wav"
    placements, sync_rep = assemble_timeline_pcm(plan, timeline_wav)
    assert len(placements) == 3
    assert timeline_wav.exists()

    # 4. Test Dubbed excerpt preview (Criteria 9 & 10)
    dubbed_excerpt = tmp_path / "sample_dubbed_turn3.mp4"
    # Preview around late utterance s3 (11-13s)
    await render_timed_excerpt(
        source_path=source_video,
        assembled_audio_path=timeline_wav,
        output_preview_path=dubbed_excerpt,
        settings=settings,
        start_sec=10.5,
        duration_sec=3.0,
        variant="dubbed",
    )
    assert dubbed_excerpt.exists()
    assert dubbed_excerpt.stat().st_size > 1000

    # 5. Test Full timeline preview render
    full_preview = tmp_path / "full_preview.mp4"
    await render_full_preview_video(
        source_path=source_video,
        voice_audio_path=timeline_wav,
        output_path=full_preview,
        settings=settings,
        target_duration=15.0,
    )
    assert full_preview.exists()
    assert full_preview.stat().st_size > 5000

    # 6. Verify decoded audio from timeline has energy at slots 2-4s, 7-9s, 11-13s and silence in between
    with wave.open(str(timeline_wav), "rb") as wf:
        n_frames = wf.getnframes()
        sr = wf.getframerate()
        raw = wf.readframes(n_frames)

    samples = struct.unpack(f"<{n_frames * 2}h", raw)

    def get_rms(start_s: float, end_s: float) -> float:
        s_idx = int(start_s * sr * 2)
        e_idx = int(end_s * sr * 2)
        sub = samples[s_idx:e_idx]
        if not sub:
            return 0.0
        return math.sqrt(sum(x * x for x in sub) / len(sub))

    # Active bursts
    rms_a1 = get_rms(2.2, 3.5)
    rms_gap1 = get_rms(4.5, 6.5)  # Silence gap between 4s and 7s
    rms_b = get_rms(7.2, 8.5)
    rms_gap2 = get_rms(9.5, 10.5)  # Silence gap between 9s and 11s
    rms_a2 = get_rms(11.2, 12.5)

    assert rms_a1 > 1000, f"Speech burst A1 was muted: rms={rms_a1}"
    assert rms_gap1 < 50, f"Gap 1 was not silent: rms={rms_gap1}"
    assert rms_b > 1000, f"Speech burst B was muted: rms={rms_b}"
    assert rms_gap2 < 50, f"Gap 2 was not silent: rms={rms_gap2}"
    assert rms_a2 > 1000, f"Speech burst A2 was muted: rms={rms_a2}"
