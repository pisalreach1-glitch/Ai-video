"""Test AI auto-translation service and callbacks."""
import pytest
from app.domain.states import JobState, WizardStep
from app.domain.models import MediaInfo
import app.handlers.narration

@pytest.mark.asyncio
async def test_choose_manual_text_callback(temp_job_storage, monkeypatch):
    """Clicking manual text option sets state to awaiting_narration_text."""
    import app.handlers.common
    monkeypatch.setattr(app.handlers.narration, "job_storage", temp_job_storage)
    monkeypatch.setattr(app.handlers.common, "job_storage", temp_job_storage)

    job = temp_job_storage.create_job(user_id=123, chat_id=456)
    temp_job_storage.set_job_status(job.job_id, JobState.AWAITING_TEXT)

    edited_text = None
    answered = False

    class MockMsg:
        chat = type("Chat", (), {"id": 456})()
        video = None
        document = None
        photo = None

        async def edit_text(self, text, reply_markup=None):
            nonlocal edited_text
            edited_text = text

    class MockCall:
        data = f"act_text:{job.job_id}"
        from_user = type("User", (), {"id": 123})()
        message = MockMsg()

        async def answer(self, text="", show_alert=False):
            nonlocal answered
            answered = True

    class MockState:
        def __init__(self):
            self.data = {}
            self.state = None

        async def get_data(self):
            return dict(self.data)

        async def update_data(self, **kwargs):
            self.data.update(kwargs)

        async def set_state(self, s):
            self.state = s

    state = MockState()
    call = MockCall()

    await app.handlers.narration.cb_choose_manual_text(call, state)

    assert state.state == WizardStep.awaiting_narration_text
    assert state.data.get("job_id") == job.job_id
    assert "បញ្ចូលអត្ថបទអាន" in edited_text

@pytest.mark.asyncio
async def test_auto_translate_callback_success(temp_job_storage, monkeypatch, tmp_path):
    """Clicking auto-translate transcribes, translates to Khmer, and creates revision with translation review keyboard."""
    import app.handlers.common
    monkeypatch.setattr(app.handlers.narration, "job_storage", temp_job_storage)
    monkeypatch.setattr(app.handlers.common, "job_storage", temp_job_storage)

    # Mock video file
    dummy_vid = tmp_path / "dummy.mp4"
    dummy_vid.write_bytes(b"dummy video data")

    job = temp_job_storage.create_job(user_id=123, chat_id=456)
    temp_job_storage.set_job_source(
        job.job_id,
        str(dummy_vid),
        MediaInfo(width=1920, height=1080, duration=45.0, has_audio=True),
    )
    temp_job_storage.set_job_status(job.job_id, JobState.AWAITING_TEXT)

    # Mock translator function
    sample_khmer_translation = "សួស្តីបងប្អូនទាំងអស់គ្នា ថ្ងៃនេះយើងនឹងបង្ហាញពីរបៀបគូររូបភាពកោងដ៏ស្រស់ស្អាត។"
    async def mock_translate(*args, **kwargs):
        return sample_khmer_translation

    monkeypatch.setattr("app.services.translator.translate_video_to_khmer", mock_translate)

    edited_texts = []
    reply_markups = []

    class MockMsg:
        chat = type("Chat", (), {"id": 456})()
        video = None
        document = None
        photo = None

        async def edit_text(self, text, reply_markup=None):
            edited_texts.append(text)
            reply_markups.append(reply_markup)

    class MockCall:
        data = f"act_trans:{job.job_id}"
        from_user = type("User", (), {"id": 123})()
        message = MockMsg()

        async def answer(self, text="", show_alert=False):
            pass

    class MockState:
        def __init__(self):
            self.data = {}
            self.state = None

        async def get_data(self):
            return dict(self.data)

        async def update_data(self, **kwargs):
            self.data.update(kwargs)

        async def set_state(self, s):
            self.state = s

    state = MockState()
    call = MockCall()

    await app.handlers.narration.cb_start_auto_translation(call, state)

    # Revision was created with the translated Khmer text
    latest_rev = temp_job_storage.get_latest_revision(job.job_id)
    assert latest_rev is not None
    assert latest_rev.narration_text == sample_khmer_translation

    # Status updated to AWAITING_SETTINGS
    refreshed_job = temp_job_storage.get_job(job.job_id)
    assert refreshed_job.status == JobState.AWAITING_SETTINGS

    # UI displayed success message with translation review keyboard
    assert any("ការបកប្រែជាភាសាខ្មែរទទួលបានជោគជ័យ" in t for t in edited_texts)
    assert reply_markups[-1] is not None
    # Verify proceed to audio button exists
    assert any(btn.callback_data == f"set_proceed:{job.job_id}:{latest_rev.revision_id}" for row in reply_markups[-1].inline_keyboard for btn in row)

@pytest.mark.asyncio
async def test_auto_translate_no_speech_detected(temp_job_storage, monkeypatch, tmp_path):
    """When no speech is found in the video, prompt user to enter text manually."""
    import app.handlers.common
    monkeypatch.setattr(app.handlers.narration, "job_storage", temp_job_storage)
    monkeypatch.setattr(app.handlers.common, "job_storage", temp_job_storage)

    dummy_vid = tmp_path / "silent.mp4"
    dummy_vid.write_bytes(b"silent video data")

    job = temp_job_storage.create_job(user_id=123, chat_id=456)
    temp_job_storage.set_job_source(
        job.job_id,
        str(dummy_vid),
        MediaInfo(width=1920, height=1080, duration=20.0, has_audio=False),
    )
    temp_job_storage.set_job_status(job.job_id, JobState.AWAITING_TEXT)

    async def mock_translate(*args, **kwargs):
        return "NO_SPEECH_DETECTED"

    monkeypatch.setattr("app.services.translator.translate_video_to_khmer", mock_translate)

    edited_texts = []

    class MockMsg:
        chat = type("Chat", (), {"id": 456})()
        video = None
        document = None
        photo = None

        async def edit_text(self, text, reply_markup=None):
            edited_texts.append(text)

    class MockCall:
        data = f"act_trans:{job.job_id}"
        from_user = type("User", (), {"id": 123})()
        message = MockMsg()

        async def answer(self, text="", show_alert=False):
            pass

    class MockState:
        async def get_data(self):
            return {}
        async def update_data(self, **kwargs):
            pass
        async def set_state(self, s):
            pass

    call = MockCall()
    await app.handlers.narration.cb_start_auto_translation(call, MockState())

    # No revision created
    assert temp_job_storage.get_latest_revision(job.job_id) is None
    # Informative warning displayed
    assert any("មិនមានសំឡេងនិយាយនៅក្នុងវីដេអូដើមទេ" in t for t in edited_texts)
