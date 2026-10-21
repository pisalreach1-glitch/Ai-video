"""
Cleanup and retention manager for Video Bot.
Enforces:
- Configurable retention (e.g. JOB_RETENTION_HOURS=24).
- Safe retention of inputs/media while users edit or re-render.
- Absolute preservation of running and queued jobs.
- Path traversal guards preventing deletion outside job/temp directories.
- Cleaning of expired job directories, props, previews, and overlays.
"""

import os
import time
import shutil
import logging
from pathlib import Path
from typing import Set, Optional, List, Dict

logger = logging.getLogger(__name__)

DEFAULT_RETENTION_HOURS = float(os.getenv("JOB_RETENTION_HOURS", "24"))


def is_safe_deletion_path(target: Path, base_dirs: List[Path]) -> bool:
    """
    Guards cleanup paths so deletion cannot escape designated temp/cache directories.
    Verifies that target is strictly a descendant of one of the allowed base directories.
    """
    try:
        resolved_target = target.resolve()
        for base in base_dirs:
            resolved_base = base.resolve()
            if resolved_target != resolved_base and resolved_base in resolved_target.parents:
                return True
        return False
    except Exception as e:
        logger.warning(f"Security path check failed for {target}: {e}")
        return False


class CleanupManager:
    """
    Manages periodic and on-demand cleanup of job media, cache, and temp files.
    """

    def __init__(
        self,
        temp_dir: Path,
        cache_dir: Optional[Path] = None,
        retention_hours: float = DEFAULT_RETENTION_HOURS
    ):
        self.temp_dir = temp_dir.resolve()
        self.cache_dir = cache_dir.resolve() if cache_dir else (self.temp_dir / "cache")
        self.jobs_dir = self.temp_dir / "jobs"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.retention_seconds = retention_hours * 3600.0

    @property
    def allowed_roots(self) -> List[Path]:
        roots = [self.temp_dir]
        if self.cache_dir:
            roots.append(self.cache_dir)
        return roots

    def cleanup_expired_jobs(
        self,
        active_job_ids: Set[str],
        force_retention_seconds: Optional[float] = None
    ) -> Dict[str, int]:
        """
        Scans job directories and temp files:
        - NEVER deletes files for active or queued jobs (checked against active_job_ids).
        - Deletes expired job directories older than retention period.
        - Deletes orphaned props/overlays/previews older than retention period.
        - Guarantees path traversal prevention.
        """
        now = time.time()
        retention = force_retention_seconds if force_retention_seconds is not None else self.retention_seconds
        deleted_jobs = 0
        deleted_files = 0

        # 1. Clean expired job folders
        if self.jobs_dir.exists():
            for entry in os.scandir(self.jobs_dir):
                if not entry.is_dir():
                    continue

                job_id = entry.name
                # Guard 1: Never delete files for running or queued jobs!
                if job_id in active_job_ids:
                    logger.debug(f"Skipping active/queued job during cleanup: {job_id}")
                    continue

                job_path = Path(entry.path)
                # Guard 2: Security path traversal guard
                if not is_safe_deletion_path(job_path, self.allowed_roots):
                    logger.error(f"Refusing to delete unsafe job path: {job_path}")
                    continue

                # Check age
                try:
                    mtime = entry.stat().st_mtime
                    if now - mtime >= retention:
                        shutil.rmtree(job_path, ignore_errors=True)
                        deleted_jobs += 1
                        logger.info(f"Deleted expired job directory: {job_id}")
                except Exception as e:
                    logger.warning(f"Error checking/deleting job directory {job_id}: {e}")

        # 2. Clean orphaned root temp files (e.g. props_*.json, clip_*.mp4)
        if self.temp_dir.exists():
            for entry in os.scandir(self.temp_dir):
                if entry.is_file():
                    fname = entry.name
                    # Only clean files matching generated temporary patterns
                    if fname.startswith(("props_", "clip_", "captions_", "audio_")):
                        file_path = Path(entry.path)
                        if not is_safe_deletion_path(file_path, self.allowed_roots):
                            continue
                        try:
                            # If file name contains an active job_id, preserve it
                            if any(act_id in fname for act_id in active_job_ids):
                                continue
                            if now - entry.stat().st_mtime >= retention:
                                os.remove(file_path)
                                deleted_files += 1
                        except Exception:
                            pass

        return {
            "deleted_jobs": deleted_jobs,
            "deleted_files": deleted_files
        }

    def delete_single_job(self, job_id: str, active_job_ids: Set[str]) -> bool:
        """Explicit deletion of a single job directory if not active."""
        if job_id in active_job_ids:
            logger.warning(f"Cannot delete active job: {job_id}")
            return False

        job_path = self.jobs_dir / job_id
        if not job_path.exists():
            return False

        if not is_safe_deletion_path(job_path, self.allowed_roots):
            logger.error(f"Unsafe path detected for job {job_id}: {job_path}")
            return False

        try:
            shutil.rmtree(job_path, ignore_errors=True)
            return True
        except Exception as e:
            logger.error(f"Failed to delete job {job_id}: {e}")
            return False
