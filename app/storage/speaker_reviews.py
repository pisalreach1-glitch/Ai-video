"""Revision-scoped review decisions, audit log, and compact callback token registry."""
from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

from app.storage.workspaces import workspace

logger = logging.getLogger(__name__)


class SpeakerReviewStore:
    def __init__(self) -> None:
        # In-memory mapping of short token -> payload with TTL
        self._tokens: dict[str, dict[str, Any]] = {}

    def create_token(
        self,
        job_id: str,
        revision_id: int,
        user_id: int,
        target_id: str = "",
        ttl_seconds: float = 86400.0,
    ) -> str:
        """
        Creates a short 8-character token reference to keep Telegram callback data <= 64 bytes.
        """
        token = uuid.uuid4().hex[:8]
        now = time.time()
        self._tokens[token] = {
            "token": token,
            "job_id": job_id,
            "revision_id": revision_id,
            "user_id": user_id,
            "target_id": target_id,
            "created_at": now,
            "expires_at": now + ttl_seconds,
        }
        return token

    def get_token(self, token: str) -> dict[str, Any] | None:
        """Resolves token data if not expired."""
        data = self._tokens.get(token)
        if not data:
            return None
        if time.time() > data["expires_at"]:
            self._tokens.pop(token, None)
            return None
        return data

    def record_decision(
        self,
        job_id: str,
        revision_id: int,
        user_id: int,
        action: str,
        target_id: str,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Appends an immutable audit decision to review_decisions.json under the revision directory.
        """
        path = workspace.get_review_decisions_path(job_id, revision_id)
        decisions: list[dict[str, Any]] = []
        if path.exists():
            try:
                decisions = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                decisions = []

        entry = {
            "decision_id": str(uuid.uuid4()),
            "user_id": user_id,
            "timestamp": time.time(),
            "action": action,
            "target_id": target_id,
            "details": details or {},
        }
        decisions.append(entry)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(decisions, ensure_ascii=False, indent=2), encoding="utf-8")
        return entry

    def load_decisions(self, job_id: str, revision_id: int) -> list[dict[str, Any]]:
        """Loads decisions recorded for a revision."""
        path = workspace.get_review_decisions_path(job_id, revision_id)
        if not path.exists():
            return []
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error(f"Failed to load review decisions from {path}: {e}")
            return []


speaker_review_store = SpeakerReviewStore()
