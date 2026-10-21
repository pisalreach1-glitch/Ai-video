"""Session storage isolated per user and chat."""
import json
import time
from typing import Any
from app.storage.database import get_db

class SessionStorage:
    def __init__(self, db=None):
        self.db = db or get_db()

    def get_session(self, user_id: int, chat_id: int) -> dict[str, Any] | None:
        conn = self.db.get_connection()
        cursor = conn.execute(
            "SELECT active_job_id, wizard_state, state_data, updated_at FROM sessions WHERE user_id = ? AND chat_id = ?",
            (user_id, chat_id)
        )
        row = cursor.fetchone()
        if not row:
            return None
        
        state_data = {}
        if row["state_data"]:
            try:
                state_data = json.loads(row["state_data"])
            except Exception:
                state_data = {}

        return {
            "user_id": user_id,
            "chat_id": chat_id,
            "active_job_id": row["active_job_id"],
            "wizard_state": row["wizard_state"],
            "state_data": state_data,
            "updated_at": row["updated_at"],
        }

    def set_session(
        self,
        user_id: int,
        chat_id: int,
        active_job_id: str | None = None,
        wizard_state: str | None = None,
        state_data: dict[str, Any] | None = None
    ) -> None:
        conn = self.db.get_connection()
        now = time.time()
        json_data = json.dumps(state_data or {}, ensure_ascii=False)
        conn.execute(
            """
            INSERT INTO sessions (user_id, chat_id, active_job_id, wizard_state, state_data, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, chat_id) DO UPDATE SET
                active_job_id = excluded.active_job_id,
                wizard_state = excluded.wizard_state,
                state_data = excluded.state_data,
                updated_at = excluded.updated_at
            """,
            (user_id, chat_id, active_job_id, wizard_state, json_data, now)
        )

    def update_state_data(self, user_id: int, chat_id: int, updates: dict[str, Any]) -> dict[str, Any]:
        curr = self.get_session(user_id, chat_id) or {
            "user_id": user_id,
            "chat_id": chat_id,
            "active_job_id": None,
            "wizard_state": None,
            "state_data": {},
        }
        data = curr.get("state_data", {})
        data.update(updates)
        self.set_session(
            user_id=user_id,
            chat_id=chat_id,
            active_job_id=curr.get("active_job_id"),
            wizard_state=curr.get("wizard_state"),
            state_data=data
        )
        return data

    def clear_session(self, user_id: int, chat_id: int) -> None:
        conn = self.db.get_connection()
        conn.execute(
            "DELETE FROM sessions WHERE user_id = ? AND chat_id = ?",
            (user_id, chat_id)
        )

session_storage = SessionStorage()
