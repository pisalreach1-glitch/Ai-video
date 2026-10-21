"""User preferences storage."""
import time
from app.domain.models import VoiceSettings
from app.storage.database import get_db

class PreferencesStorage:
    def __init__(self, db=None):
        self.db = db or get_db()

    def get_preferences(self, user_id: int) -> VoiceSettings:
        conn = self.db.get_connection()
        row = conn.execute(
            """
            SELECT voice, speed, subtitles_enabled, subtitle_color, subtitle_position,
                   source_audio_mode, aspect_ratio, framing_mode, duration_policy
            FROM preferences
            WHERE user_id = ?
            """,
            (user_id,)
        ).fetchone()

        if not row:
            return VoiceSettings()

        return VoiceSettings(
            voice=row["voice"],
            speed=row["speed"],
            subtitles_enabled=bool(row["subtitles_enabled"]),
            subtitle_color=row["subtitle_color"],
            subtitle_position=row["subtitle_position"],
            source_audio_mode=row["source_audio_mode"],
            aspect_ratio=row["aspect_ratio"],
            framing_mode=row["framing_mode"],
            duration_policy=row["duration_policy"],
        )

    def save_preferences(self, user_id: int, settings: VoiceSettings) -> None:
        conn = self.db.get_connection()
        now = time.time()
        conn.execute(
            """
            INSERT INTO preferences (
                user_id, voice, speed, subtitles_enabled, subtitle_color, subtitle_position,
                source_audio_mode, aspect_ratio, framing_mode, duration_policy, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                voice = excluded.voice,
                speed = excluded.speed,
                subtitles_enabled = excluded.subtitles_enabled,
                subtitle_color = excluded.subtitle_color,
                subtitle_position = excluded.subtitle_position,
                source_audio_mode = excluded.source_audio_mode,
                aspect_ratio = excluded.aspect_ratio,
                framing_mode = excluded.framing_mode,
                duration_policy = excluded.duration_policy,
                updated_at = excluded.updated_at
            """,
            (
                user_id,
                settings.voice,
                settings.speed,
                1 if settings.subtitles_enabled else 0,
                settings.subtitle_color,
                settings.subtitle_position,
                settings.source_audio_mode,
                settings.aspect_ratio,
                settings.framing_mode,
                settings.duration_policy,
                now,
            )
        )

    def restore_preferences(self, user_id: int) -> VoiceSettings:
        conn = self.db.get_connection()
        conn.execute("DELETE FROM preferences WHERE user_id = ?", (user_id,))
        return VoiceSettings()

preferences_storage = PreferencesStorage()
