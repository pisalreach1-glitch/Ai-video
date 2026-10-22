"""Assign and split ASR utterances by speaker turns with uncertainty tracking."""
from __future__ import annotations

import hashlib
import json
from typing import Any
from app.domain.dubbing import SourceSegment
from app.domain.speakers import SpeakerTurn, SpeakerAssignment, ReviewIssue


def compute_turn_overlap(start1: int, end1: int, start2: int, end2: int) -> int:
    """Calculates millisecond overlap between two intervals."""
    s = max(start1, start2)
    e = min(end1, end2)
    return max(0, e - s)


def compute_speaker_coverages(
    seg_start_ms: int,
    seg_end_ms: int,
    turns: list[SpeakerTurn],
) -> dict[str, int]:
    """
    Computes total non-overlapping coverage (ms) by each speaker for a time window.
    Merges duplicate or overlapping turns per speaker to avoid double counting.
    """
    by_speaker: dict[str, list[tuple[int, int]]] = {}
    for t in turns:
        ov = compute_turn_overlap(seg_start_ms, seg_end_ms, t.start_ms, t.end_ms)
        if ov > 0:
            s = max(seg_start_ms, t.start_ms)
            e = min(seg_end_ms, t.end_ms)
            by_speaker.setdefault(t.speaker_id, []).append((s, e))

    coverages: dict[str, int] = {}
    for spk_id, intervals in by_speaker.items():
        # Merge overlapping intervals for this speaker
        intervals.sort(key=lambda x: x[0])
        merged: list[tuple[int, int]] = []
        for s, e in intervals:
            if not merged:
                merged.append((s, e))
            else:
                prev_s, prev_e = merged[-1]
                if s <= prev_e:
                    merged[-1] = (prev_s, max(prev_e, e))
                else:
                    merged.append((s, e))
        coverages[spk_id] = sum(e - s for s, e in merged)

    return coverages


def assign_speakers_to_segments(
    segments: list[SourceSegment],
    turns: list[SpeakerTurn],
    analysis_key: str = "default",
) -> tuple[list[SourceSegment], list[SpeakerAssignment], list[ReviewIssue]]:
    """
    Assigns speakers to ASR segments based on diarization turns.
    If trustworthy word timings exist and an utterance spans distinct speaker turns,
    splits the utterance at the speaker boundary, preserving provenance.
    Produces honest uncertainty records and review issues where ambiguous.
    """
    out_segments: list[SourceSegment] = []
    out_assignments: list[SpeakerAssignment] = []
    out_issues: list[ReviewIssue] = []

    for seg in segments:
        seg_dur = max(1, seg.duration_ms)
        coverages = compute_speaker_coverages(seg.start_ms, seg.end_ms, turns)

        evidence_payload = {
            "seg_id": seg.segment_id,
            "seg_start": seg.start_ms,
            "seg_end": seg.end_ms,
            "coverages": coverages,
            "analysis_key": analysis_key,
        }
        evidence_key = hashlib.sha256(
            json.dumps(evidence_payload, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]

        if not coverages:
            # No speaker turn overlaps with this segment
            seg_copy = SourceSegment(
                segment_id=seg.segment_id,
                start_ms=seg.start_ms,
                end_ms=seg.end_ms,
                source_text=seg.source_text,
                source_language=seg.source_language,
                words=seg.words,
                timing_origin=seg.timing_origin,
                needs_review=True,
                speaker_id=None,
                speaker_assignment_origin="auto",
                speaker_evidence_key=evidence_key,
                parent_segment_id=seg.parent_segment_id,
            )
            out_segments.append(seg_copy)
            out_assignments.append(
                SpeakerAssignment(
                    segment_id=seg.segment_id,
                    speaker_id=None,
                    evidence_key=evidence_key,
                    origin="auto",
                    confidence=None,
                    confidence_kind="unavailable",
                )
            )
            out_issues.append(
                ReviewIssue(
                    issue_id=f"no_turn_{seg.segment_id}",
                    segment_id=seg.segment_id,
                    reason="unknown_speaker",
                    subject_key=evidence_key,
                    producer="speaker_assignment",
                    blocking=True,
                    allow_confirmation=False,
                )
            )
            continue

        sorted_spks = sorted(coverages.items(), key=lambda x: x[1], reverse=True)
        top_spk, top_cov = sorted_spks[0]
        top_fraction = top_cov / seg_dur

        # Check if multiple speakers compete (e.g. runner-up has > 25% coverage)
        competing = [spk for spk, cov in sorted_spks if cov / seg_dur >= 0.25]

        # Try word-boundary split if segment has word timings and competing speakers
        if len(competing) > 1 and seg.words and len(seg.words) >= 2:
            # Check if words clearly partition between speakers
            word_spks: list[str | None] = []
            for w in seg.words:
                w_start = int(round(float(w.get("start", 0.0)) * 1000))
                w_end = int(round(float(w.get("end", 0.0)) * 1000))
                w_cov = compute_speaker_coverages(w_start, w_end, turns)
                if w_cov:
                    word_spks.append(max(w_cov.items(), key=lambda x: x[1])[0])
                else:
                    word_spks.append(None)

            # Look for a clean single transition point
            split_idx = -1
            first_spk = next((s for s in word_spks if s is not None), None)
            if first_spk:
                for idx, s in enumerate(word_spks[1:], start=1):
                    if s is not None and s != first_spk:
                        # Transition found
                        split_idx = idx
                        break

            if split_idx > 0:
                words_a = seg.words[:split_idx]
                words_b = seg.words[split_idx:]
                text_a = " ".join(str(w.get("word", w.get("text", ""))).strip() for w in words_a).strip()
                text_b = " ".join(str(w.get("word", w.get("text", ""))).strip() for w in words_b).strip()

                start_a = seg.start_ms
                end_a = int(round(float(words_a[-1].get("end", 0.0)) * 1000))
                start_b = int(round(float(words_b[0].get("start", 0.0)) * 1000))
                end_b = seg.end_ms

                if end_a > start_a and end_b > start_b and text_a and text_b:
                    seg_a_id = f"{seg.segment_id}_a"
                    seg_b_id = f"{seg.segment_id}_b"

                    seg_a = SourceSegment(
                        segment_id=seg_a_id,
                        start_ms=start_a,
                        end_ms=end_a,
                        source_text=text_a,
                        source_language=seg.source_language,
                        words=words_a,
                        timing_origin="local_asr",
                        speaker_id=first_spk,
                        speaker_assignment_origin="auto",
                        speaker_evidence_key=evidence_key,
                        parent_segment_id=seg.segment_id,
                    )
                    second_spk = next((s for s in word_spks[split_idx:] if s is not None), top_spk)
                    seg_b = SourceSegment(
                        segment_id=seg_b_id,
                        start_ms=start_b,
                        end_ms=end_b,
                        source_text=text_b,
                        source_language=seg.source_language,
                        words=words_b,
                        timing_origin="local_asr",
                        speaker_id=second_spk,
                        speaker_assignment_origin="auto",
                        speaker_evidence_key=evidence_key,
                        parent_segment_id=seg.segment_id,
                    )

                    out_segments.extend([seg_a, seg_b])
                    out_assignments.append(
                        SpeakerAssignment(
                            segment_id=seg_a_id,
                            speaker_id=first_spk,
                            evidence_key=evidence_key,
                            origin="auto",
                            confidence=None,
                            confidence_kind="unavailable",
                        )
                    )
                    out_assignments.append(
                        SpeakerAssignment(
                            segment_id=seg_b_id,
                            speaker_id=second_spk,
                            evidence_key=evidence_key,
                            origin="auto",
                            confidence=None,
                            confidence_kind="unavailable",
                        )
                    )
                    continue

        # Standard assignment to top speaker
        seg_copy = SourceSegment(
            segment_id=seg.segment_id,
            start_ms=seg.start_ms,
            end_ms=seg.end_ms,
            source_text=seg.source_text,
            source_language=seg.source_language,
            words=seg.words,
            timing_origin=seg.timing_origin,
            needs_review=(len(competing) > 1 or top_fraction < 0.65),
            speaker_id=top_spk,
            speaker_assignment_origin="auto",
            speaker_evidence_key=evidence_key,
            parent_segment_id=seg.parent_segment_id,
        )
        out_segments.append(seg_copy)

        asgn = SpeakerAssignment(
            segment_id=seg.segment_id,
            speaker_id=top_spk,
            evidence_key=evidence_key,
            origin="auto",
            confidence=None,  # Community-1 raw outputs are uncalibrated
            confidence_kind="unavailable",
        )
        out_assignments.append(asgn)

        if len(competing) > 1:
            out_issues.append(
                ReviewIssue(
                    issue_id=f"competing_{seg.segment_id}",
                    segment_id=seg.segment_id,
                    reason="competing_speakers",
                    subject_key=evidence_key,
                    producer="speaker_assignment",
                    blocking=True,
                    allow_confirmation=True,
                )
            )
        elif top_fraction < 0.60:
            out_issues.append(
                ReviewIssue(
                    issue_id=f"low_cov_{seg.segment_id}",
                    segment_id=seg.segment_id,
                    reason="low_speaker_confidence",
                    subject_key=evidence_key,
                    producer="speaker_assignment",
                    blocking=True,
                    allow_confirmation=True,
                )
            )

    return out_segments, out_assignments, out_issues
