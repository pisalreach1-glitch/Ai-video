"""Workspace filesystem layout manager."""
from pathlib import Path
from app.config import config

class WorkspaceManager:
    def __init__(self, runtime_dir: Path | str | None = None):
        self.runtime_dir = Path(runtime_dir) if runtime_dir else config.runtime_dir
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_dir = self.runtime_dir / "jobs"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.voice_samples_dir = self.runtime_dir / "voice_samples"
        self.voice_samples_dir.mkdir(parents=True, exist_ok=True)

    def get_job_dir(self, job_id: str) -> Path:
        job_dir = self.jobs_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        return job_dir

    def get_input_dir(self, job_id: str) -> Path:
        input_dir = self.get_job_dir(job_id) / "input"
        input_dir.mkdir(parents=True, exist_ok=True)
        return input_dir

    def get_source_video_path(self, job_id: str, ext: str = "mp4") -> Path:
        return self.get_input_dir(job_id) / f"source.{ext.lstrip('.')}"

    def get_revision_dir(self, job_id: str, revision_id: int) -> Path:
        rev_dir = self.get_job_dir(job_id) / "revisions" / str(revision_id)
        rev_dir.mkdir(parents=True, exist_ok=True)
        return rev_dir

    def get_narration_path(self, job_id: str, revision_id: int) -> Path:
        return self.get_revision_dir(job_id, revision_id) / "narration.txt"

    def get_settings_path(self, job_id: str, revision_id: int) -> Path:
        return self.get_revision_dir(job_id, revision_id) / "settings.json"

    def get_voice_audio_path(self, job_id: str, revision_id: int) -> Path:
        return self.get_revision_dir(job_id, revision_id) / "voice.mp3"

    def get_subtitles_srt_path(self, job_id: str, revision_id: int) -> Path:
        return self.get_revision_dir(job_id, revision_id) / "subtitles.srt"

    def get_subtitles_ass_path(self, job_id: str, revision_id: int) -> Path:
        return self.get_revision_dir(job_id, revision_id) / "subtitles.ass"

    def get_audio_preview_path(self, job_id: str, revision_id: int) -> Path:
        return self.get_revision_dir(job_id, revision_id) / "audio_preview.mp3"

    def get_preview_video_path(self, job_id: str, revision_id: int) -> Path:
        return self.get_revision_dir(job_id, revision_id) / "preview.mp4"

    def get_final_video_path(self, job_id: str, revision_id: int) -> Path:
        return self.get_revision_dir(job_id, revision_id) / "final.mp4"

    def get_voice_sample_path(self, voice_name: str) -> Path:
        safe_name = "".join(c for c in voice_name if c.isalnum() or c in "-_")
        return self.voice_samples_dir / f"{safe_name}.mp3"

workspace = WorkspaceManager()
