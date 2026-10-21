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

    def get_analysis_dir(self, job_id: str, key: str = "default") -> Path:
        analysis_dir = self.get_job_dir(job_id) / "analysis" / key
        analysis_dir.mkdir(parents=True, exist_ok=True)
        return analysis_dir

    def get_source_audio_path(self, job_id: str, key: str = "default") -> Path:
        return self.get_analysis_dir(job_id, key) / "source_audio.wav"

    def get_source_segments_path(self, job_id: str, key: str = "default") -> Path:
        return self.get_analysis_dir(job_id, key) / "source_segments.json"

    def get_dubbing_plan_path(self, job_id: str, revision_id: int) -> Path:
        return self.get_revision_dir(job_id, revision_id) / "dubbing.json"

    def get_segment_dir(self, job_id: str, revision_id: int, segment_id: str) -> Path:
        seg_dir = self.get_revision_dir(job_id, revision_id) / "segments" / segment_id
        seg_dir.mkdir(parents=True, exist_ok=True)
        return seg_dir

    def get_segment_voice_mp3(self, job_id: str, revision_id: int, segment_id: str) -> Path:
        return self.get_segment_dir(job_id, revision_id, segment_id) / "voice.mp3"

    def get_segment_voice_wav(self, job_id: str, revision_id: int, segment_id: str) -> Path:
        return self.get_segment_dir(job_id, revision_id, segment_id) / "voice.wav"

    def get_segment_fitted_wav(self, job_id: str, revision_id: int, segment_id: str) -> Path:
        return self.get_segment_dir(job_id, revision_id, segment_id) / "fitted.wav"

    def get_segment_tts_events_path(self, job_id: str, revision_id: int, segment_id: str) -> Path:
        return self.get_segment_dir(job_id, revision_id, segment_id) / "tts_events.json"

    def get_placements_path(self, job_id: str, revision_id: int) -> Path:
        return self.get_revision_dir(job_id, revision_id) / "placements.json"

    def get_timeline_audio_path(self, job_id: str, revision_id: int) -> Path:
        return self.get_revision_dir(job_id, revision_id) / "narration_timeline.wav"

    def get_sync_report_path(self, job_id: str, revision_id: int) -> Path:
        return self.get_revision_dir(job_id, revision_id) / "sync_report.json"

    def get_voice_sample_path(self, voice_name: str) -> Path:
        safe_name = "".join(c for c in voice_name if c.isalnum() or c in "-_")
        return self.voice_samples_dir / f"{safe_name}.mp3"

workspace = WorkspaceManager()
