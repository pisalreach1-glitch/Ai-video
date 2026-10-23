"""Tests for long render duration, timeline integrity, and quality evaluation."""
import pytest
from app.features.talking_photo.quality import evaluate_render_quality

def test_long_render_speech_preserved_through_final_phrase():
    audio_dur = 125.4
    video_dur = 125.4

    report = evaluate_render_quality(video_dur, audio_dur)
    assert report.duration_valid is True
    assert report.final_phrase_preserved is True
    assert report.duration_difference == 0.0

def test_long_render_small_rounding_pad_accepted():
    audio_dur = 120.0
    # Video slightly longer by 0.04s due to rational frame rate (e.g. 25fps)
    video_dur = 120.04

    report = evaluate_render_quality(video_dur, audio_dur)
    assert report.duration_valid is True
    assert report.final_phrase_preserved is True
    assert report.duration_difference == 0.04

def test_long_render_incomplete_video_rejected():
    audio_dur = 120.0
    # Video truncated at 115s (missing 5s of speech)
    video_dur = 115.0

    report = evaluate_render_quality(video_dur, audio_dur)
    assert report.duration_valid is False
    assert report.final_phrase_preserved is False
    assert "Video truncated" in report.notes
