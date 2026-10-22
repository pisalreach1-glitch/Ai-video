"""Tests for cancellation, old plan JSON migration, and offline fallback."""
import json
import pytest
from app.domain.dubbing import DubbingPlan, SourceSegment
from app.jobs.worker import worker_pool


def test_old_plan_json_deserializes_to_single_mode_without_error():
    """Criteria 17: Old plan JSON without speaker fields loads seamlessly as single mode."""
    old_json = {
        "mode": "source_timed",
        "source_duration_ms": 15000,
        "sample_rate": 48000,
        "segments": [
            {
                "segment_id": "s001",
                "start_ms": 1000,
                "end_ms": 3000,
                "source_text": "Old segment text",
            }
        ],
        "translations": [
            {
                "segment_id": "s001",
                "translated_text": "អត្ថបទបកប្រែចាស់",
            }
        ],
        "clips": [],
        "placements": [],
        "issues": [],
    }

    plan = DubbingPlan.from_json(json.dumps(old_json))
    assert plan.schema_version == 1
    assert plan.speaker_mode == "single"
    assert len(plan.speakers) == 0
    assert len(plan.speaker_turns) == 0
    assert len(plan.speaker_assignments) == 0
    assert plan.segments[0].speaker_id is None
    assert plan.segments[0].speaker_assignment_origin == "auto"


def test_job_cancellation_flags():
    """Criteria 16: Cancel marks job as cancelled immediately."""
    test_job_id = "test_cancel_uuid_123"
    worker_pool.cancel_job(test_job_id)
    assert worker_pool.is_cancelled(test_job_id)
