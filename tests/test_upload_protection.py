"""Test upload blocking during active render and completed job edit handling."""
import pytest
from app.domain.states import JobState, WizardStep
from app.domain.models import VoiceSettings
from app.handlers.uploads import handle_video_upload
from app.handlers.jobs import cb_edit_completed_job

@pytest.mark.asyncio
async def test_upload_blocked_during_active_render(temp_job_storage, monkeypatch):
    """Ensure handle_video_upload rejects media when a job is currently rendering and uses job_in_progress_keyboard."""
    job = temp_job_storage.create_job(user_id=100, chat_id=200)
    temp_job_storage.set_job_status(job.job_id, JobState.RENDERING)

    import app.handlers.uploads
    monkeypatch.setattr(app.handlers.uploads, "job_storage", temp_job_storage)

    replied = False
    reply_markup_used = None

    class MockMessage:
        from_user = type("User", (), {"id": 100})()
        chat = type("Chat", (), {"id": 200})()
        video = type("Video", (), {"file_id": "vid123", "file_size": 1000})()
        document = None

        async def reply(self, text, reply_markup=None):
            nonlocal replied, reply_markup_used
            replied = True
            reply_markup_used = reply_markup

    class MockState:
        async def get_data(self):
            return {}
        async def set_state(self, s):
            pass

    msg = MockMessage()
    await handle_video_upload(msg, MockState(), None)

    assert replied is True
    assert reply_markup_used is not None
    # Verify button points to active job cancellation
    buttons = reply_markup_used.inline_keyboard
    assert any(btn.callback_data == f"job_cancel:{job.job_id}" for row in buttons for btn in row)

@pytest.mark.asyncio
async def test_job_edit_completed_screen_safety(temp_job_storage, monkeypatch):
    """Ensure job_edit verifies ownership, strips video buttons safely, and sends a new message."""
    job = temp_job_storage.create_job(user_id=555, chat_id=777)
    r1 = temp_job_storage.create_revision(
        job.job_id, "Voice text", VoiceSettings(),
        audio_path="/tmp/aud.mp3",
        audio_duration=4.5,
        subtitles_srt="/tmp/sub.srt",
    )
    temp_job_storage.set_job_status(job.job_id, JobState.COMPLETED)

    import app.handlers.jobs
    monkeypatch.setattr(app.handlers.jobs, "job_storage", temp_job_storage)

    stripped_markup = False
    answered_msg = False
    alert_text = None

    class MockMsg:
        chat = type("Chat", (), {"id": 777})()
        video = type("Video", (), {})()
        document = None
        photo = None

        async def edit_reply_markup(self, reply_markup=None):
            nonlocal stripped_markup
            stripped_markup = True

        async def answer(self, text, reply_markup=None):
            nonlocal answered_msg
            answered_msg = True

    class MockCall:
        from_user = type("User", (), {"id": 555})()
        message = MockMsg()
        data = f"job_edit:{job.job_id}"

        async def answer(self, text="", show_alert=False):
            nonlocal alert_text
            alert_text = text

    class MockState:
        async def update_data(self, **kwargs):
            pass
        async def set_state(self, s):
            pass

    call = MockCall()
    await cb_edit_completed_job(call, MockState())

    assert stripped_markup is True
    assert answered_msg is True
    assert alert_text == "🔁 ចាប់ផ្ដើមកែសម្រួល"

    # Confirm new revision was created and carries over audio
    latest = temp_job_storage.get_latest_revision(job.job_id)
    assert latest.revision_id == 2
    assert latest.audio_path == "/tmp/aud.mp3"
    assert latest.audio_duration == 4.5

@pytest.mark.asyncio
async def test_concurrent_uploads_prevent_overwriting_same_destination(temp_job_storage, monkeypatch, tmp_path):
    """Ensure two rapid concurrent uploads cannot overwrite each other or share the same destination."""
    import asyncio
    import app.handlers.uploads
    from app.domain.models import MediaInfo
    monkeypatch.setattr(app.handlers.uploads, "job_storage", temp_job_storage)
    monkeypatch.setattr("app.handlers.uploads.probe_media", lambda p: MediaInfo(width=1920, height=1080, duration=10.0, has_audio=True))

    user_id = 999
    chat_id = 888

    # Start with an awaiting_source job in state
    init_job = temp_job_storage.create_job(user_id=user_id, chat_id=chat_id, source_type="upload")
    temp_job_storage.set_job_status(init_job.job_id, JobState.AWAITING_SOURCE)

    downloaded_dests = []
    replies = []

    class MockStatusMsg:
        async def edit_text(self, text, reply_markup=None):
            pass

    class MockMsg:
        def __init__(self, tag):
            self.tag = tag
            self.from_user = type("User", (), {"id": user_id})()
            self.chat = type("Chat", (), {"id": chat_id})()
            self.video = type("Video", (), {"file_id": f"vid_{tag}", "file_size": 5000, "file_name": f"{tag}.mp4"})()
            self.document = None
            self.caption = None

        async def reply(self, text, reply_markup=None):
            replies.append((self.tag, text))
            return MockStatusMsg()

    class MockBot:
        async def get_file(self, file_id):
            return type("FileObj", (), {"file_path": f"/remote/{file_id}"})()

        async def download_file(self, file_path, destination):
            from pathlib import Path
            p_dest = Path(destination)
            downloaded_dests.append((file_path, str(p_dest)))
            p_dest.parent.mkdir(parents=True, exist_ok=True)
            p_dest.write_text(f"content from {file_path}")
            await asyncio.sleep(0.05)

    class MockState:
        def __init__(self):
            self.data = {"job_id": init_job.job_id}
        async def get_data(self):
            return dict(self.data)
        async def update_data(self, **kwargs):
            self.data.update(kwargs)
        async def set_state(self, s):
            pass

    msg1 = MockMsg("upload1")
    msg2 = MockMsg("upload2")
    bot = MockBot()
    state1 = MockState()
    state2 = MockState()

    await asyncio.gather(
        app.handlers.uploads.handle_video_upload(msg1, state1, bot),
        app.handlers.uploads.handle_video_upload(msg2, state2, bot),
    )

    # One download succeeded
    assert len(downloaded_dests) == 1
    # The other message was rejected with active job warning
    assert any("មានការងារវីដេអូមួយកំពុងដំណើរការ" in r[1] for r in replies)

    # Job ended up in awaiting text
    job_after = temp_job_storage.get_job(init_job.job_id)
    assert job_after.status == JobState.AWAITING_TEXT
