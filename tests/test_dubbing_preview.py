"""Tests for timed excerpt preview and subtitle rebasing."""
import pytest
from pathlib import Path
from app.services.previews import _rebase_ass_file
from timecode_utils import format_ass_timestamp

def test_preview_rebase_subtitles_offsets_and_clips(tmp_path):
    """Requirement 10: Preview around later utterance (e.g. 8s to 13s) rebases subtitle cues."""
    src_ass = tmp_path / "original.ass"
    header = (
        "[Script Info]\nTitle: Test\nScriptType: v4.00+\n\n"
        "[V4+ Styles]\nFormat: Name\nStyle: Default\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    # Cue 1 at 2.0s - 4.0s (outside preview window 8s - 13s)
    # Cue 2 at 8.5s - 10.5s (inside preview window: should become 0.5s - 2.5s)
    # Cue 3 at 12.0s - 14.0s (overlaps end: should clip to 4.0s - 5.0s)
    dialogues = [
        f"Dialogue: 0,{format_ass_timestamp(2.0)},{format_ass_timestamp(4.0)},Default,,0,0,0,,Early Cue",
        f"Dialogue: 0,{format_ass_timestamp(8.5)},{format_ass_timestamp(10.5)},Default,,0,0,0,,Middle Cue",
        f"Dialogue: 0,{format_ass_timestamp(12.0)},{format_ass_timestamp(14.0)},Default,,0,0,0,,Late Overlapping Cue",
    ]
    src_ass.write_text(header + "\n".join(dialogues) + "\n", encoding="utf-8")

    dest_ass = tmp_path / "rebased.ass"
    _rebase_ass_file(src_ass, dest_ass, start_sec=8.0, dur_sec=5.0)

    content = dest_ass.read_text(encoding="utf-8")
    assert "Early Cue" not in content # Excluded
    assert "Middle Cue" in content
    assert "Late Overlapping Cue" in content

    # Verify Middle Cue timing rebased from 8.5s -> 0.5s
    lines = [l for l in content.splitlines() if "Middle Cue" in l]
    assert len(lines) == 1
    parts = lines[0].split(",")
    assert parts[1].strip() == format_ass_timestamp(0.5)
    assert parts[2].strip() == format_ass_timestamp(2.5)

    # Verify Late Overlapping Cue clipped to duration 5.0s
    late_lines = [l for l in content.splitlines() if "Late Overlapping Cue" in l]
    assert len(late_lines) == 1
    late_parts = late_lines[0].split(",")
    assert late_parts[1].strip() == format_ass_timestamp(4.0)
    assert late_parts[2].strip() == format_ass_timestamp(5.0)
