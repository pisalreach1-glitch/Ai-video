"""Verify isolated background mixing, excerpt sync, and honest failure handling."""
import asyncio
import subprocess
from unittest.mock import AsyncMock
import numpy as np
import pytest
from app.config import config
from app.domain.models import VoiceSettings
from app.services.media import probe_media
from app.services.render import render_video
from app.services.previews import render_timed_excerpt

def amplitude(samples, frequency, rate=48000):
    start = samples[int(0.2 * rate):int(0.8 * rate)]
    times = np.arange(len(start)) / rate
    return abs(np.sum(start * np.exp(-2j * np.pi * frequency * times))) / len(start)

def decode(path):
    result = subprocess.run([config.ffmpeg_path, '-v', 'error', '-i', str(path),
        '-vn', '-ac', '1', '-ar', '48000', '-f', 'f32le', '-'], capture_output=True, check=True)
    return np.frombuffer(result.stdout, dtype=np.float32)

@pytest.mark.asyncio
async def test_background_and_narration_survive_without_original_speech(session_media_dir, tmp_path, monkeypatch):
    background = tmp_path / 'separated.wav'
    subprocess.run([config.ffmpeg_path, '-y', '-f', 'lavfi', '-i',
        'sine=frequency=880:duration=3', str(background)], capture_output=True, check=True)
    prepare = AsyncMock(return_value=background)
    monkeypatch.setattr('app.services.background_audio.prepare_background', prepare)
    settings = VoiceSettings(source_audio_mode='background')
    full = tmp_path / 'full.mp4'
    await render_video(session_media_dir['video_with_audio'], session_media_dir['audio_sample'],
        full, settings, target_duration=3.0)
    samples = decode(full)
    assert amplitude(samples, 440) > 0.02  # new narration
    assert amplitude(samples, 880) > 0.02  # retained background
    assert amplitude(samples, 1000) < 0.002  # source speech track is never remixed
    assert abs(probe_media(full).duration - 3.0) < 0.15
    assert np.max(np.abs(samples[-12000:])) > 0.02  # no lost final background/narration
    preview = tmp_path / 'excerpt.mp4'
    await render_timed_excerpt(session_media_dir['video_with_audio'], session_media_dir['audio_sample'],
        preview, settings, start_sec=0.5, duration_sec=1.0)
    samples = decode(preview)
    assert amplitude(samples, 880) > 0.02
    assert amplitude(samples, 1000) < 0.002
    assert abs(probe_media(preview).duration - 1.0) < 0.15

@pytest.mark.asyncio
async def test_separator_failure_never_silently_remixes_original_speech(session_media_dir, tmp_path, monkeypatch):
    monkeypatch.setattr('app.services.background_audio.prepare_background',
        AsyncMock(side_effect=RuntimeError('separation failed')))
    with pytest.raises(RuntimeError, match='separation failed'):
        await render_video(session_media_dir['video_with_audio'], session_media_dir['audio_sample'],
            tmp_path/'failed.mp4', VoiceSettings(source_audio_mode='background'), 2.0)

@pytest.mark.asyncio
async def test_no_source_audio_needs_no_separator(session_media_dir, tmp_path, monkeypatch):
    prepare = AsyncMock(side_effect=AssertionError('should not separate silence'))
    monkeypatch.setattr('app.services.background_audio.prepare_background', prepare)
    await render_video(session_media_dir['video_no_audio'], session_media_dir['audio_sample'],
        tmp_path/'no-source-audio.mp4', VoiceSettings(source_audio_mode='background'), 2.0)
    prepare.assert_not_awaited()

def test_new_default_preserves_background_and_explicit_mute_is_respected():
    assert VoiceSettings().source_audio_mode == 'background'
    assert VoiceSettings.from_dict({'source_audio_mode':'mute'}).source_audio_mode == 'mute'
