"""Storage persistence for DubbingPlan, SourceSegments, and SyncReports."""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any
from app.domain.dubbing import DubbingPlan, SourceSegment
from app.storage.workspaces import workspace

logger = logging.getLogger(__name__)

def save_dubbing_plan(job_id: str, revision_id: int, plan: DubbingPlan) -> Path:
    """Save dubbing plan JSON snapshot for a specific revision."""
    plan_path = workspace.get_dubbing_plan_path(job_id, revision_id)
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(plan.to_json(indent=2), encoding="utf-8")
    return plan_path

def load_dubbing_plan(job_id: str, revision_id: int) -> DubbingPlan | None:
    """Load dubbing plan snapshot for a specific revision."""
    plan_path = workspace.get_dubbing_plan_path(job_id, revision_id)
    if not plan_path.exists():
        return None
    try:
        content = plan_path.read_text(encoding="utf-8")
        return DubbingPlan.from_json(content)
    except Exception as e:
        logger.error(f"Failed to load dubbing plan at {plan_path}: {e}")
        return None

def save_source_segments(job_id: str, segments: list[SourceSegment], key: str = "default") -> Path:
    """Save extracted source segments in analysis directory."""
    path = workspace.get_source_segments_path(job_id, key=key)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [s.to_dict() for s in segments]
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path

def load_source_segments(job_id: str, key: str = "default") -> list[SourceSegment] | None:
    """Load extracted source segments from analysis directory."""
    path = workspace.get_source_segments_path(job_id, key=key)
    if not path.exists():
        return None
    try:
        content = path.read_text(encoding="utf-8")
        data = json.loads(content)
        return [SourceSegment.from_dict(item) for item in data]
    except Exception as e:
        logger.error(f"Failed to load source segments at {path}: {e}")
        return None

def save_sync_report(job_id: str, revision_id: int, report: dict[str, Any]) -> Path:
    """Save sync_report.json containing timeline measurements."""
    path = workspace.get_sync_report_path(job_id, revision_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path

def load_sync_report(job_id: str, revision_id: int) -> dict[str, Any] | None:
    """Load sync_report.json."""
    path = workspace.get_sync_report_path(job_id, revision_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"Failed to load sync report at {path}: {e}")
        return None
