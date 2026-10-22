"""Tests for speaker turn coverage, assignment, and word-boundary splitting."""
import pytest
from app.domain.dubbing import SourceSegment
from app.domain.speakers import SpeakerTurn
from app.services.speaker_assignment import (
    compute_speaker_coverages,
    compute_turn_overlap,
    assign_speakers_to_segments,
)


def test_turn_overlap_calculation():
    assert compute_turn_overlap(1000, 3000, 2000, 4000) == 1000
    assert compute_turn_overlap(1000, 2000, 3000, 4000) == 0
    assert compute_turn_overlap(1000, 5000, 2000, 3000) == 1000
    assert compute_turn_overlap(2000, 3000, 1000, 5000) == 1000


def test_speaker_coverage_unions_overlapping_turns():
    """Duplicate/overlapping turns of the same speaker must not be double counted."""
    turns = [
        SpeakerTurn(speaker_id="Speaker A", start_ms=1000, end_ms=3000),
        SpeakerTurn(speaker_id="Speaker A", start_ms=2000, end_ms=4000),  # overlaps with first turn
    ]
    coverages = compute_speaker_coverages(0, 5000, turns)
    # Total interval for Speaker A is 1000 to 4000 = 3000ms
    assert coverages["Speaker A"] == 3000


def test_ab_a_maintains_consistent_speaker_assignment():
    """Criteria 1: A/B/A at separate times maintains same identity for A."""
    turns = [
        SpeakerTurn(speaker_id="Speaker A", start_ms=1000, end_ms=3000),
        SpeakerTurn(speaker_id="Speaker B", start_ms=4000, end_ms=6000),
        SpeakerTurn(speaker_id="Speaker A", start_ms=7000, end_ms=9000),
    ]
    segments = [
        SourceSegment(segment_id="s001", start_ms=1050, end_ms=2900, source_text="Hello from A 1"),
        SourceSegment(segment_id="s002", start_ms=4100, end_ms=5900, source_text="Hello from B"),
        SourceSegment(segment_id="s003", start_ms=7050, end_ms=8950, source_text="Hello from A 2"),
    ]

    out_segs, assignments, issues = assign_speakers_to_segments(segments, turns)
    assert len(out_segs) == 3
    assert out_segs[0].speaker_id == "Speaker A"
    assert out_segs[1].speaker_id == "Speaker B"
    assert out_segs[2].speaker_id == "Speaker A"

    asgn_map = {a.segment_id: a for a in assignments}
    assert asgn_map["s001"].speaker_id == "Speaker A"
    assert asgn_map["s002"].speaker_id == "Speaker B"
    assert asgn_map["s003"].speaker_id == "Speaker A"


def test_multi_speaker_word_boundary_split():
    """Criteria 11: Multi-speaker utterance splits with valid word times without duplicating text."""
    turns = [
        SpeakerTurn(speaker_id="Speaker A", start_ms=1000, end_ms=3000),
        SpeakerTurn(speaker_id="Speaker B", start_ms=3000, end_ms=5000),
    ]
    words = [
        {"word": "Hi", "start": 1.1, "end": 1.8},
        {"word": "there", "start": 1.9, "end": 2.7},
        {"word": "I", "start": 3.1, "end": 3.5},
        {"word": "agree", "start": 3.6, "end": 4.8},
    ]
    seg = SourceSegment(
        segment_id="s001",
        start_ms=1000,
        end_ms=5000,
        source_text="Hi there I agree",
        words=words,
    )

    out_segs, assignments, issues = assign_speakers_to_segments([seg], turns)
    # Must have split into two child segments
    assert len(out_segs) == 2
    assert out_segs[0].segment_id == "s001_a"
    assert out_segs[0].speaker_id == "Speaker A"
    assert out_segs[0].source_text == "Hi there"
    assert out_segs[0].parent_segment_id == "s001"

    assert out_segs[1].segment_id == "s001_b"
    assert out_segs[1].speaker_id == "Speaker B"
    assert out_segs[1].source_text == "I agree"
    assert out_segs[1].parent_segment_id == "s001"


def test_unscored_assignment_confidence_representation():
    """Criteria 5: Unscored confidence is stored as None / unavailable, never 100%."""
    turns = [SpeakerTurn(speaker_id="Speaker A", start_ms=1000, end_ms=3000)]
    seg = SourceSegment(segment_id="s001", start_ms=1000, end_ms=3000, source_text="Hello")

    out_segs, assignments, issues = assign_speakers_to_segments([seg], turns)
    asgn = assignments[0]
    assert asgn.confidence is None
    assert asgn.confidence_kind == "unavailable"
