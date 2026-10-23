"""Storage and revision management for Talking Photo feature."""
import json
import time
import hashlib
from pathlib import Path
from typing import Any
from app.features.talking_photo.domain import TalkingPhotoRevision, TalkingPhotoSettings
from app.storage.database import get_db

def compute_input_digest(image_path: str | Path, voice_path: str | Path) -> str:
    """Compute deterministic SHA256 digest of input image and voice files."""
    hasher = hashlib.sha256()
    for p in (image_path, voice_path):
        path_obj = Path(p)
        if path_obj.exists():
            with open(path_obj, "rb") as f:
                while chunk := f.read(65536):
                    hasher.update(chunk)
    return hasher.hexdigest()

class TalkingPhotoStorage:
    def __init__(self, db=None):
        self.db = db or get_db()

    def create_revision(
        self,
        job_id: str,
        image_path: str,
        original_voice_path: str,
        settings: TalkingPhotoSettings | None = None,
        input_digest: str | None = None,
        input_version: int = 1,
        engine_version: str = "sadtalker-1.0",
        audio_source: str = "recorded_voice",
        approved_audio_artifact_id: str | None = None,
        audio_approval_id: str | None = None,
        image_sha256: str = "",
        settings_digest: str = "",
        video_snapshot_digest: str = "",
    ) -> TalkingPhotoRevision:
        conn = self.db.get_connection()
        now = time.time()
        st = settings or TalkingPhotoSettings()

        # Find next revision_id for this job
        row = conn.execute(
            "SELECT COALESCE(MAX(revision_id), 0) + 1 AS next_rev FROM talking_photo_revisions WHERE job_id = ?",
            (job_id,)
        ).fetchone()
        next_rev = row["next_rev"] if row else 1

        if not input_digest:
            input_digest = compute_input_digest(image_path, original_voice_path)

        settings_json = json.dumps(st.to_dict())

        conn.execute(
            """
            INSERT INTO talking_photo_revisions (
                job_id, revision_id, input_version, image_path, original_voice_path,
                inference_wav_path, master_audio_path, settings_json, manifest_path,
                preview_path, approved_preview_id, final_path, input_digest,
                engine_version, audio_source, approved_audio_artifact_id, audio_approval_id,
                image_sha256, settings_digest, video_snapshot_digest, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                next_rev,
                input_version,
                str(image_path),
                str(original_voice_path),
                None,
                None,
                settings_json,
                None,
                None,
                None,
                None,
                input_digest,
                engine_version,
                audio_source,
                approved_audio_artifact_id,
                audio_approval_id,
                image_sha256,
                settings_digest,
                video_snapshot_digest,
                now,
            )
        )

        # Update job's current_revision_id
        conn.execute(
            "UPDATE jobs SET current_revision_id = ?, updated_at = ? WHERE job_id = ?",
            (next_rev, now, job_id)
        )

        return TalkingPhotoRevision(
            job_id=job_id,
            revision_id=next_rev,
            input_version=input_version,
            image_path=str(image_path),
            original_voice_path=str(original_voice_path),
            settings=st,
            input_digest=input_digest,
            engine_version=engine_version,
            audio_source=audio_source,
            approved_audio_artifact_id=approved_audio_artifact_id,
            audio_approval_id=audio_approval_id,
            image_sha256=image_sha256,
            settings_digest=settings_digest,
            video_snapshot_digest=video_snapshot_digest,
            created_at=now,
        )

    def get_revision(self, job_id: str, revision_id: int) -> TalkingPhotoRevision | None:
        conn = self.db.get_connection()
        row = conn.execute(
            "SELECT * FROM talking_photo_revisions WHERE job_id = ? AND revision_id = ?",
            (job_id, revision_id)
        ).fetchone()
        if not row:
            return None
        return TalkingPhotoRevision.from_dict(dict(row))

    def get_latest_revision(self, job_id: str) -> TalkingPhotoRevision | None:
        conn = self.db.get_connection()
        row = conn.execute(
            """
            SELECT * FROM talking_photo_revisions
            WHERE job_id = ?
            ORDER BY revision_id DESC
            LIMIT 1
            """,
            (job_id,)
        ).fetchone()
        if not row:
            return None
        return TalkingPhotoRevision.from_dict(dict(row))

    def update_revision_paths(
        self,
        job_id: str,
        revision_id: int,
        inference_wav_path: str | None = None,
        master_audio_path: str | None = None,
        preview_path: str | None = None,
        approved_preview_id: str | None = None,
        final_path: str | None = None,
        manifest_path: str | None = None,
        audio_source: str | None = None,
        approved_audio_artifact_id: str | None = None,
        audio_approval_id: str | None = None,
    ) -> None:
        conn = self.db.get_connection()
        updates = []
        params = []
        if inference_wav_path is not None:
            updates.append("inference_wav_path = ?")
            params.append(str(inference_wav_path))
        if master_audio_path is not None:
            updates.append("master_audio_path = ?")
            params.append(str(master_audio_path))
        if preview_path is not None:
            updates.append("preview_path = ?")
            params.append(str(preview_path))
        if approved_preview_id is not None:
            updates.append("approved_preview_id = ?")
            params.append(str(approved_preview_id))
        if final_path is not None:
            updates.append("final_path = ?")
            params.append(str(final_path))
        if manifest_path is not None:
            updates.append("manifest_path = ?")
            params.append(str(manifest_path))
        if audio_source is not None:
            updates.append("audio_source = ?")
            params.append(str(audio_source))
        if approved_audio_artifact_id is not None:
            updates.append("approved_audio_artifact_id = ?")
            params.append(str(approved_audio_artifact_id))
        if audio_approval_id is not None:
            updates.append("audio_approval_id = ?")
            params.append(str(audio_approval_id))

        if not updates:
            return

        params.extend([job_id, revision_id])
        sql = f"UPDATE talking_photo_revisions SET {', '.join(updates)} WHERE job_id = ? AND revision_id = ?"
        conn.execute(sql, tuple(params))

talking_photo_storage = TalkingPhotoStorage()
