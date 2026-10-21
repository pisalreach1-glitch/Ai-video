import sys
import subprocess
import pytest
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import config
from app.storage.database import Database
from app.storage.jobs import JobStorage
from app.storage.preferences import PreferencesStorage
from app.storage.sessions import SessionStorage
from app.storage.workspaces import WorkspaceManager

@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_state.sqlite3"
    db = Database(db_file)
    return db

@pytest.fixture
def temp_job_storage(temp_db):
    return JobStorage(temp_db)

@pytest.fixture
def temp_preferences(temp_db):
    return PreferencesStorage(temp_db)

@pytest.fixture
def temp_sessions(temp_db):
    return SessionStorage(temp_db)

@pytest.fixture
def temp_workspace(tmp_path):
    return WorkspaceManager(tmp_path / "runtime")

@pytest.fixture(scope="session")
def session_media_dir(tmp_path_factory):
    media_dir = tmp_path_factory.mktemp("media")

    # 1. Video with audio (2 seconds, 640x360)
    video_with_audio = media_dir / "sample_with_audio.mp4"
    cmd1 = [
        config.ffmpeg_path, "-y",
        "-f", "lavfi", "-i", "testsrc=size=640x360:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=1000:sample_rate=44100",
        "-t", "2.0",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-movflags", "+faststart",
        str(video_with_audio),
    ]
    subprocess.run(cmd1, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    # 2. Video without audio (2 seconds, 640x360)
    video_no_audio = media_dir / "sample_no_audio.mp4"
    cmd2 = [
        config.ffmpeg_path, "-y",
        "-f", "lavfi", "-i", "testsrc=size=640x360:rate=30",
        "-t", "2.0",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(video_no_audio),
    ]
    subprocess.run(cmd2, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    # 3. Audio narration (3 seconds, mp3)
    audio_sample = media_dir / "sample_narration.mp3"
    cmd3 = [
        config.ffmpeg_path, "-y",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
        "-t", "3.0",
        "-c:a", "libmp3lame",
        str(audio_sample),
    ]
    subprocess.run(cmd3, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    return {
        "video_with_audio": video_with_audio,
        "video_no_audio": video_no_audio,
        "audio_sample": audio_sample,
    }
