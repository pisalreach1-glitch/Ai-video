"""Database access layer for Voice Conversion records."""
import time
import uuid
from typing import Any
from app.features.voice_conversion.domain import VoiceConversionRecord
from app.storage.database import get_db

class VoiceConversionStorage:
    def __init__(self, db=None):
        self.db = db or get_db()

    def create_conversion(
        self,
        job_id: str,
        owner_user_id: int,
        target_reference_path: str,
        target_reference_sha256: str,
        target_reference_duration: float,
        full_source_path: str,
        full_source_sha256: str,
        full_source_duration: float,
        request_digest: str,
        backend_id: str = "seed_vc",
        conversion_id: str | None = None,
    ) -> VoiceConversionRecord:
        conn = self.db.get_connection()
        now = time.time()
        conv_id = conversion_id or f"vc_{uuid.uuid4().hex[:12]}"

        conn.execute(
            """
            INSERT INTO voice_conversions (
                conversion_id, job_id, owner_user_id,
                target_reference_path, target_reference_sha256, target_reference_duration,
                full_source_path, full_source_sha256, full_source_duration,
                converted_wav_path, converted_wav_sha256, converted_duration,
                state, backend_id, request_digest, manifest_path, error_code, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, 0.0, 'pending', ?, ?, NULL, NULL, ?)
            """,
            (
                conv_id,
                job_id,
                owner_user_id,
                str(target_reference_path),
                target_reference_sha256,
                target_reference_duration,
                str(full_source_path),
                full_source_sha256,
                full_source_duration,
                backend_id,
                request_digest,
                now,
            )
        )
        return VoiceConversionRecord(
            conversion_id=conv_id,
            job_id=job_id,
            owner_user_id=owner_user_id,
            target_reference_path=str(target_reference_path),
            target_reference_sha256=target_reference_sha256,
            target_reference_duration=target_reference_duration,
            full_source_path=str(full_source_path),
            full_source_sha256=full_source_sha256,
            full_source_duration=full_source_duration,
            state="pending",
            backend_id=backend_id,
            request_digest=request_digest,
            created_at=now,
        )

    def get_conversion(self, conversion_id: str) -> VoiceConversionRecord | None:
        conn = self.db.get_connection()
        row = conn.execute("SELECT * FROM voice_conversions WHERE conversion_id = ?", (conversion_id,)).fetchone()
        if not row:
            return None
        return VoiceConversionRecord.from_dict(dict(row))

    def get_latest_conversion_for_job(self, job_id: str) -> VoiceConversionRecord | None:
        conn = self.db.get_connection()
        row = conn.execute(
            "SELECT * FROM voice_conversions WHERE job_id = ? ORDER BY created_at DESC LIMIT 1",
            (job_id,)
        ).fetchone()
        if not row:
            return None
        return VoiceConversionRecord.from_dict(dict(row))

    def update_conversion_completed(
        self,
        conversion_id: str,
        converted_wav_path: str,
        converted_wav_sha256: str,
        converted_duration: float,
        manifest_path: str | None = None,
    ) -> None:
        conn = self.db.get_connection()
        conn.execute(
            """
            UPDATE voice_conversions
            SET state = 'ready', converted_wav_path = ?, converted_wav_sha256 = ?,
                converted_duration = ?, manifest_path = ?
            WHERE conversion_id = ?
            """,
            (str(converted_wav_path), converted_wav_sha256, converted_duration, str(manifest_path) if manifest_path else None, conversion_id)
        )

    def update_conversion_failed(self, conversion_id: str, error_code: str) -> None:
        conn = self.db.get_connection()
        conn.execute(
            "UPDATE voice_conversions SET state = 'failed', error_code = ? WHERE conversion_id = ?",
            (error_code, conversion_id)
        )

voice_conversion_storage = VoiceConversionStorage()
