"""Tests verifying the Voice Conversion upload order and promptless text-free flow.

Product requirement:
Photo -> Target Reference Voice (timbre) -> Full Source Voice (words & pauses) -> Review Inputs
No target text, reference transcript, or text entry required.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from pathlib import Path
from aiogram.types import Message, CallbackQuery, Voice, Audio, User, Chat

from app.features.voice_conversion.states import VoiceConversionSteps
from app.features.voice_conversion.handlers import (
    cb_choose_voice_conversion,
    handle_target_reference_upload,
    handle_full_source_upload,
    handle_target_reference_wrong_input,
    handle_full_source_wrong_input,
    cb_change_reference,
    cb_change_full_source,
)

class MockFSMContext:
    def __init__(self, initial_state=None, initial_data=None):
        self._state = initial_state
        self._data = initial_data or {}

    async def get_state(self):
        return self._state

    async def set_state(self, state):
        self._state = state

    async def get_data(self):
        return dict(self._data)

    async def update_data(self, **kwargs):
        self._data.update(kwargs)

    async def clear(self):
        self._data.clear()
        self._state = None

@pytest.mark.asyncio
async def test_vc_flow_requires_no_text_prompts():
    """Verify that starting VC sets waiting_target_reference and prompts for voice only."""
    state = MockFSMContext()
    message = AsyncMock()
    message.edit_text = AsyncMock()
    callback = AsyncMock()
    callback.answer = AsyncMock()
    callback.data = "tp_src_vc:job-vc-123"
    callback.message = message

    await cb_choose_voice_conversion(callback, state)

    # State must be waiting_target_reference
    assert await state.get_state() == VoiceConversionSteps.waiting_target_reference
    data = await state.get_data()
    assert data.get("job_id") == "job-vc-123"
    assert data.get("audio_source") == "converted_voice"

    # Verify prompt instructs voice/audio upload and does NOT ask for text or transcript
    prompt_text = message.edit_text.call_args[0][0]
    assert "Target Voice" in prompt_text or "សំឡេងគំរូ" in prompt_text
    assert "អត្ថបទ" not in prompt_text
    assert "transcript" not in prompt_text.lower()

@pytest.mark.asyncio
async def test_vc_wrong_input_text_guidance():
    """Verify that sending text at waiting_target_reference or waiting_full_source gives clear Khmer guidance."""
    state = MockFSMContext(initial_state=VoiceConversionSteps.waiting_target_reference, initial_data={"job_id": "job-vc-123"})
    msg = AsyncMock()
    msg.text = "Hello here is my text"
    msg.answer = AsyncMock()

    await handle_target_reference_wrong_input(msg, state)
    guidance = msg.answer.call_args[0][0]
    assert "Speech-to-Speech" in guidance or "មិនតម្រូវឱ្យវាយអក្សរឡើយ" in guidance

    # Full source step wrong input guidance
    await state.set_state(VoiceConversionSteps.waiting_full_source)
    msg.text = "Second text attempt"
    msg.answer = AsyncMock()
    await handle_full_source_wrong_input(msg, state)
    guidance_src = msg.answer.call_args[0][0]
    assert "មិនតម្រូវឱ្យវាយអក្សរឡើយ" in guidance_src
    assert "Full Source Speech" in guidance_src or "សំឡេងនិយាយពេញ" in guidance_src

@pytest.mark.asyncio
async def test_vc_change_inputs_updates_state():
    """Verify that changing reference or full source transitions to the respective waiting states."""
    state = MockFSMContext(
        initial_state=VoiceConversionSteps.reviewing_inputs,
        initial_data={
            "job_id": "job-vc-123",
            "target_reference_duration": 15.0,
            "full_source_duration": 120.0,
        }
    )
    cb = AsyncMock()
    cb.data = "vc_ch_ref:job-vc-123"
    cb.answer = AsyncMock()
    cb.message = AsyncMock()
    cb.message.answer = AsyncMock()

    await cb_change_reference(cb, state)
    assert await state.get_state() == VoiceConversionSteps.waiting_target_reference

    # Now change source
    cb.data = "vc_ch_src:job-vc-123"
    await cb_change_full_source(cb, state)
    assert await state.get_state() == VoiceConversionSteps.waiting_full_source
