"""Database access layer for Voice Cloning entities."""
import json
import time
import uuid
from typing import Any
from app.features.voice_clone.domain import VoiceReference, VoiceCloneArtifact, AudioApproval
from app.storage.database import get_db

class VoiceCloneStorage:
    def __init__(self, db=None):
        self.db = db or get_db()

    # -------------------------------------------------------------
    # Voice References
    # -------------------------------------------------------------
    def save_reference(
        self,
        owner_user_id: int,
        job_id: str,
        wav_path: str,
        sha256: str,
        duration_seconds: float,
        sample_rate: int = 24000,
        channels: int = 1,
        reference_id: str | None = None,
    ) -> VoiceReference:
        conn = self.db.get_connection()
        now = time.time()
        ref_id = reference_id or f"ref_{uuid.uuid4().hex[:12]}"

        # Check existing version count for this job
        row = conn.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 AS next_ver FROM voice_references WHERE job_id = ?",
            (job_id,)
        ).fetchone()
        version = row["next_ver"] if row else 1

        conn.execute(
            """
            INSERT INTO voice_references (
                reference_id, owner_user_id, job_id, version,
                wav_path, sha256, duration_seconds, sample_rate, channels, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ref_id,
                owner_user_id,
                job_id,
                version,
                str(wav_path),
                sha256,
                duration_seconds,
                sample_rate,
                channels,
                now,
            )
        )
        return VoiceReference(
            reference_id=ref_id,
            owner_user_id=owner_user_id,
            job_id=job_id,
            version=version,
            wav_path=str(wav_path),
            sha256=sha256,
            duration_seconds=duration_seconds,
            sample_rate=sample_rate,
            channels=channels,
            created_at=now,
        )

    def get_reference(self, reference_id: str) -> VoiceReference | None:
        conn = self.db.get_connection()
        row = conn.execute("SELECT * FROM voice_references WHERE reference_id = ?", (reference_id,)).fetchone()
        if not row:
            return None
        return VoiceReference.from_dict(dict(row))

    def get_latest_reference_for_job(self, job_id: str) -> VoiceReference | None:
        conn = self.db.get_connection()
        row = conn.execute(
            "SELECT * FROM voice_references WHERE job_id = ? ORDER BY version DESC LIMIT 1",
            (job_id,)
        ).fetchone()
        if not row:
            return None
        return VoiceReference.from_dict(dict(row))

    # -------------------------------------------------------------
    # Voice Clone Artifacts
    # -------------------------------------------------------------
    def create_artifact(
        self,
        job_id: str,
        owner_user_id: int,
        reference_id: str,
        reference_sha256: str,
        text: str,
        text_sha256: str,
        request_digest: str,
        language: str = "km",
        backend_id: str = "local",
        model_version: str = "1.0",
        settings: dict[str, Any] | None = None,
        artifact_id: str | None = None,
    ) -> VoiceCloneArtifact:
        conn = self.db.get_connection()
        now = time.time()
        art_id = artifact_id or f"art_{uuid.uuid4().hex[:12]}"
        settings_json = json.dumps(settings or {})

        conn.execute(
            """
            INSERT INTO voice_clone_artifacts (
                artifact_id, job_id, owner_user_id, reference_id, reference_sha256,
                text, text_sha256, language, backend_id, model_version, settings_json,
                request_digest, state, wav_path, wav_sha256, duration_seconds,
                manifest_path, error_code, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', NULL, NULL, 0.0, NULL, NULL, ?)
            """,
            (
                art_id,
                job_id,
                owner_user_id,
                reference_id,
                reference_sha256,
                text,
                text_sha256,
                language,
                backend_id,
                model_version,
                settings_json,
                request_digest,
                now,
            )
        )
        return VoiceCloneArtifact(
            artifact_id=art_id,
            job_id=job_id,
            owner_user_id=owner_user_id,
            reference_id=reference_id,
            reference_sha256=reference_sha256,
            text=text,
            text_sha256=text_sha256,
            language=language,
            backend_id=backend_id,
            model_version=model_version,
            settings_json=settings_json,
            request_digest=request_digest,
            state="pending",
            created_at=now,
        )

    def get_artifact(self, artifact_id: str) -> VoiceCloneArtifact | None:
        conn = self.db.get_connection()
        row = conn.execute("SELECT * FROM voice_clone_artifacts WHERE artifact_id = ?", (artifact_id,)).fetchone()
        if not row:
            return None
        return VoiceCloneArtifact.from_dict(dict(row))

    def get_latest_artifact_for_job(self, job_id: str) -> VoiceCloneArtifact | None:
        conn = self.db.get_connection()
        row = conn.execute(
            "SELECT * FROM voice_clone_artifacts WHERE job_id = ? ORDER BY created_at DESC LIMIT 1",
            (job_id,)
        ).fetchone()
        if not row:
            return None
        return VoiceCloneArtifact.from_dict(dict(row))

    def update_artifact_completed(
        self,
        artifact_id: str,
        wav_path: str,
        wav_sha256: str,
        duration_seconds: float,
        manifest_path: str | None = None,
    ) -> None:
        conn = self.db.get_connection()
        conn.execute(
            """
            UPDATE voice_clone_artifacts
            SET state = 'ready', wav_path = ?, wav_sha256 = ?, duration_seconds = ?, manifest_path = ?
            WHERE artifact_id = ?
            """,
            (str(wav_path), wav_sha256, duration_seconds, str(manifest_path) if manifest_path else None, artifact_id)
        )

    def update_artifact_failed(self, artifact_id: str, error_code: str) -> None:
        conn = self.db.get_connection()
        conn.execute(
            "UPDATE voice_clone_artifacts SET state = 'failed', error_code = ? WHERE artifact_id = ?",
            (error_code, artifact_id)
        )

    # -------------------------------------------------------------
    # Audio Approvals
    # -------------------------------------------------------------
    def approve_audio(
        self,
        job_id: str,
        artifact_id: str,
        request_digest: str,
        wav_sha256: str,
        owner_user_id: int,
    ) -> AudioApproval:
        now = time.time()
        approval_id = f"appr_{uuid.uuid4().hex[:12]}"

        with self.db.transaction() as conn:
            # Invalidate any earlier active approvals for this job
            conn.execute(
                "UPDATE audio_approvals SET invalidated_at = ? WHERE job_id = ? AND invalidated_at IS NULL",
                (now, job_id)
            )
            conn.execute(
                """
                INSERT INTO audio_approvals (
                    approval_id, job_id, artifact_id, request_digest, wav_sha256,
                    owner_user_id, approved_at, invalidated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (approval_id, job_id, artifact_id, request_digest, wav_sha256, owner_user_id, now)
            )

        return AudioApproval(
            approval_id=approval_id,
            job_id=job_id,
            artifact_id=artifact_id,
            request_digest=request_digest,
            wav_sha256=wav_sha256,
            owner_user_id=owner_user_id,
            approved_at=now,
        )

    def get_active_approval(self, job_id: str) -> AudioApproval | None:
        conn = self.db.get_connection()
        row = conn.execute(
            "SELECT * FROM audio_approvals WHERE job_id = ? AND invalidated_at IS NULL ORDER BY approved_at DESC LIMIT 1",
            (job_id,)
        ).fetchone()
        if not row:
            return None
        return AudioApproval.from_dict(dict(row))

    def invalidate_approvals(self, job_id: str) -> None:
        conn = self.db.get_connection()
        now = time.time()
        conn.execute(
            "UPDATE audio_approvals SET invalidated_at = ? WHERE job_id = ? AND invalidated_at IS NULL",
            (now, job_id)
        )

voice_clone_storage = VoiceCloneStorage()
