"""Safe retention cleanup for expired job files."""
import shutil
import time
import logging
from app.config import config
from app.storage.database import get_db
from app.storage.workspaces import workspace

logger = logging.getLogger(__name__)

def cleanup_expired_jobs(retention_hours: float | None = None) -> int:
    """
    Remove disk artifacts for completed/failed/cancelled jobs older than retention_hours.
    Never removes active jobs or jobs currently queued/rendering.
    """
    db = get_db()
    hours = retention_hours if retention_hours is not None else config.job_retention_hours
    cutoff = time.time() - (hours * 3600.0)

    conn = db.get_connection()
    # Find jobs past retention that are not actively queued or processing
    rows = conn.execute(
        """
        SELECT j.job_id, j.status, j.created_at
        FROM jobs j
        LEFT JOIN render_queue q ON j.job_id = q.job_id
        WHERE j.created_at < ?
          AND j.status IN ('completed', 'failed', 'cancelled')
          AND (q.status IS NULL OR q.status NOT IN ('queued', 'processing'))
        """,
        (cutoff,)
    ).fetchall()

    cleaned_count = 0
    for row in rows:
        job_id = row["job_id"]
        job_dir = workspace.get_job_dir(job_id)
        if job_dir.exists():
            try:
                shutil.rmtree(job_dir, ignore_errors=True)
                cleaned_count += 1
                logger.info(f"Cleaned up expired job directory: {job_id}")
            except Exception as e:
                logger.warning(f"Error cleaning job {job_id}: {e}")

    return cleaned_count
