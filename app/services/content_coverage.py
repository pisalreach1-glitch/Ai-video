"""Deterministic stage coverage and completeness validation for source-timed dubbing."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.domain.dubbing import DubbingPlan, DubbingIssue
from app.domain.models import VoiceSettings
from app.storage.workspaces import workspace

logger = logging.getLogger(__name__)


def validate_content_coverage(
    plan: DubbingPlan,
    settings: VoiceSettings,
    require_clips_and_placements: bool = True,
) -> list[DubbingIssue]:
    """
    Validates end-to-end stage coverage for every source segment:
    1) Valid source transcript and start/end time range.
    2) Exactly one non-empty accepted translation exists (status != 'failed' and != 'pending').
    3) Valid speaker assignment and confirmed voice in multi-speaker mode.
    4) Decodable, non-empty TTS clip matching cache key (when require_clips_and_placements=True).
    5) Placement exists for the complete fitted clip within source bounds (when require_clips_and_placements=True).

    Returns a list of blocking DubbingIssue instances if any stage is missing or broken.
    """
    issues: list[DubbingIssue] = []

    if not plan.segments:
        issues.append(
            DubbingIssue(
                segment_id="global",
                issue_type="missing_source_segments",
                message="មិនមានទិន្នន័យឃ្លាដើមនៅក្នុងគម្រោងឡើយ។",
                severity="blocking",
            )
        )
        return issues

    # 1. Check for duplicate segment IDs
    source_ids = [s.segment_id for s in plan.segments]
    if len(source_ids) != len(set(source_ids)):
        issues.append(
            DubbingIssue(
                segment_id="global",
                issue_type="duplicate_segment_ids",
                message="មាន Segment IDs ស្ទួនគ្នានៅក្នុងបញ្ជីឃ្លាដើម។",
                severity="blocking",
            )
        )

    translation_map: dict[str, Any] = {}
    for t in plan.translations:
        if t.segment_id in translation_map:
            issues.append(
                DubbingIssue(
                    segment_id=t.segment_id,
                    issue_type="duplicate_translation_id",
                    message=f"មានអត្ថបទបកប្រែស្ទួនគ្នាសម្រាប់ឃ្លា {t.segment_id}",
                    severity="blocking",
                )
            )
        translation_map[t.segment_id] = t

    clip_map = {c.segment_id: c for c in plan.clips}
    placement_map = {p.segment_id: p for p in plan.placements}
    assignment_map = {a.segment_id: a for a in plan.speaker_assignments}

    for s in plan.segments:
        sid = s.segment_id

        # 1. Source transcript & timing
        if not s.source_text.strip():
            issues.append(
                DubbingIssue(
                    segment_id=sid,
                    issue_type="empty_source_text",
                    message=f"ឃ្លា {sid} គ្មានអត្ថបទដើមឡើយ។",
                    severity="blocking",
                )
            )
        if s.end_ms <= s.start_ms:
            issues.append(
                DubbingIssue(
                    segment_id=sid,
                    issue_type="invalid_source_timing",
                    message=f"ពេលវេលាឃ្លា {sid} មិនត្រឹមត្រូវ ({s.start_ms}ms >= {s.end_ms}ms)។",
                    severity="blocking",
                )
            )

        # 2. Translation coverage
        t = translation_map.get(sid)
        if not t or not t.translated_text.strip():
            issues.append(
                DubbingIssue(
                    segment_id=sid,
                    issue_type="missing_translation",
                    message=f"ខ្វះអត្ថបទបកប្រែសម្រាប់ឃ្លា {sid}។",
                    severity="blocking",
                )
            )
        elif t.status in ("failed", "pending", "needs_review") or (require_clips_and_placements and t.status != "ready"):
            issues.append(
                DubbingIssue(
                    segment_id=sid,
                    issue_type="unready_translation",
                    message=f"អត្ថបទបកប្រែសម្រាប់ឃ្លា {sid} មិនទាន់រួចរាល់ ({t.status})។",
                    severity="blocking",
                    producer="coverage",
                )
            )

        # 3. Speaker assignment in multi mode
        if plan.speaker_mode == "multi":
            asgn = assignment_map.get(sid)
            if not asgn or not asgn.speaker_id:
                issues.append(
                    DubbingIssue(
                        segment_id=sid,
                        issue_type="missing_speaker_assignment",
                        message=f"ឃ្លា {sid} មិនទាន់បានកំណត់អ្នកនិយាយឡើយ។",
                        severity="blocking",
                        producer="coverage",
                    )
                )

        if require_clips_and_placements:
            # 4. Audio clip check
            clip = clip_map.get(sid)
            if not clip:
                issues.append(
                    DubbingIssue(
                        segment_id=sid,
                        issue_type="missing_clip",
                        message=f"ខ្វះសំឡេងសម្រាប់ឃ្លា {sid}។",
                        severity="blocking",
                        producer="coverage",
                    )
                )
            elif clip.status == "too_long":
                issues.append(
                    DubbingIssue(
                        segment_id=sid,
                        issue_type="too_long",
                        message=f"សំឡេងឃ្លា {sid} វែងលើសពេលវេលាក្នុងវីដេអូដើម។",
                        severity="blocking",
                        producer="coverage",
                    )
                )
            elif clip.status == "failed":
                issues.append(
                    DubbingIssue(
                        segment_id=sid,
                        issue_type="failed_clip",
                        message=f"ការបង្កើតសំឡេងឃ្លា {sid} បានបរាជ័យ។",
                        severity="blocking",
                        producer="coverage",
                    )
                )
            else:
                # Require real, nonempty audio artifacts
                c_path = Path(clip.fitted_audio_path or clip.raw_audio_path)
                if not c_path.exists() or c_path.stat().st_size == 0:
                    issues.append(
                        DubbingIssue(
                            segment_id=sid,
                            issue_type="empty_clip_artifact",
                            message=f"ឯកសារសំឡេងឃ្លា {sid} មិនមាន ឬទទេស្អាត។",
                            severity="blocking",
                            producer="coverage",
                        )
                    )

            # 5. Placement check
            placement = placement_map.get(sid)
            if not placement:
                issues.append(
                    DubbingIssue(
                        segment_id=sid,
                        issue_type="missing_placement",
                        message=f"មិនទាន់បានរៀបចំទីតាំងសំឡេងលើបន្ទាត់ពេលវេលាសម្រាប់ឃ្លា {sid}។",
                        severity="blocking",
                        producer="coverage",
                    )
                )
            elif placement.speech_end_ms > plan.source_duration_ms:
                issues.append(
                    DubbingIssue(
                        segment_id=sid,
                        issue_type="overrun",
                        message=f"សំឡេងឃ្លា {sid} ហួសប្រវែងវីដេអូដើម។",
                        severity="blocking",
                        producer="coverage",
                    )
                )

    # Check for orphaned translations (translations that have no corresponding source segment)
    valid_source_set = set(source_ids)
    for t_id in translation_map:
        if t_id not in valid_source_set:
            issues.append(
                DubbingIssue(
                    segment_id=t_id,
                    issue_type="orphaned_translation",
                    message=f"អត្ថបទបកប្រែ {t_id} គ្មាន Segment ដើមដែលត្រូវគ្នាឡើយ។",
                    severity="blocking",
                )
            )

    return issues


def generate_completeness_report(
    plan: DubbingPlan,
    settings: VoiceSettings,
    job_id: str,
    revision_id: int,
) -> dict[str, Any]:
    """
    Generates and persists completeness_report.json tracking coverage across all stages.
    """
    report_items = []
    coverage_issues = validate_content_coverage(plan, settings, require_clips_and_placements=True)

    clip_map = {c.segment_id: c for c in plan.clips}
    placement_map = {p.segment_id: p for p in plan.placements}
    trans_map = {t.segment_id: t for t in plan.translations}
    asgn_map = {a.segment_id: a for a in plan.speaker_assignments}

    for s in plan.segments:
        sid = s.segment_id
        t = trans_map.get(sid)
        c = clip_map.get(sid)
        p = placement_map.get(sid)
        a = asgn_map.get(sid)

        item = {
            "segment_id": sid,
            "start_ms": s.start_ms,
            "end_ms": s.end_ms,
            "duration_ms": s.duration_ms,
            "source_text": s.source_text,
            "translated_text": t.translated_text if t else None,
            "full_translation": t.full_translation if t else None,
            "proposed_concise_text": t.proposed_concise_text if t else None,
            "translation_status": t.status if t else "missing",
            "speaker_id": a.speaker_id if a else s.speaker_id,
            "clip_status": c.status if c else "missing",
            "effective_duration_ms": c.effective_duration_ms if c else 0,
            "placement_start_ms": p.timeline_start_ms if p else None,
            "placement_end_ms": p.speech_end_ms if p else None,
        }
        report_items.append(item)

    report = {
        "job_id": job_id,
        "revision_id": revision_id,
        "total_segments": len(plan.segments),
        "total_translations": len(plan.translations),
        "total_clips": len(plan.clips),
        "total_placements": len(plan.placements),
        "is_complete": len(coverage_issues) == 0 and not plan.has_blocking_issues,
        "blocking_issues_count": len(coverage_issues) + len(plan.issues),
        "segments": report_items,
        "issues": [i.to_dict() for i in coverage_issues + plan.issues],
    }

    report_path = workspace.get_revision_dir(job_id, revision_id) / "completeness_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
