"""Test SRT and styled ASS subtitle generation."""
import pytest
from pathlib import Path
from app.services.subtitles import (
    group_events_into_phrases,
    generate_srt,
    generate_ass,
)

def test_phrase_grouping_readable():
    """Verify that long phrases are chunked while keeping times monotonic."""
    sample_events = [
        {
            "start": 0.0,
            "end": 6.0,
            "text": "នេះជាឃ្លាវែងមួយដែលមានអក្សរខ្មែរច្រើនដែលត្រូវបែងចែកជាឃ្លាខ្លីៗដើម្បីងាយស្រួលមើលនៅលើអេក្រង់ទូរស័ព្ទ។",
        }
    ]
    phrases = group_events_into_phrases(sample_events, max_chars_per_phrase=35)
    assert len(phrases) >= 2

    # Check continuity and monotonicity
    for i in range(len(phrases) - 1):
        assert phrases[i]["end"] <= phrases[i + 1]["start"] + 0.001
        assert phrases[i]["start"] < phrases[i]["end"]

def test_srt_generation(tmp_path):
    """Ensure standard valid SRT timecodes are output."""
    events = [
        {"start": 1.250, "end": 3.750, "text": "ជំរាបសួរ"},
        {"start": 4.000, "end": 5.500, "text": "អ្នកទាំងអស់គ្នា"},
    ]
    srt_file = tmp_path / "test.srt"
    out = generate_srt(events, srt_file)

    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "1\n00:00:01,250 --> 00:00:03,750\nជំរាបសួរ" in content
    assert "2\n00:00:04,000 --> 00:00:05,500\nអ្នកទាំងអស់គ្នា" in content

def test_ass_styling_options(tmp_path):
    """Check color and position configurations in ASS headers and events."""
    events = [{"start": 0.5, "end": 2.5, "text": "អក្សររត់"}]

    # Yellow color, middle position
    ass_file = tmp_path / "styled.ass"
    generate_ass(
        events=events,
        output_path=ass_file,
        color="yellow",
        position="middle",
        res_x=1080,
        res_y=1920,
    )

    content = ass_file.read_text(encoding="utf-8")
    assert "PlayResX: 1080" in content
    assert "PlayResY: 1920" in content
    # Middle alignment is 5
    assert ",5," in content
    # Yellow primary color
    assert "&H002BF7FF" in content
    # Event text present
    assert "Dialogue: 0,0:00:00.50,0:00:02.50,Default,,0,0,0,,អក្សររត់" in content
