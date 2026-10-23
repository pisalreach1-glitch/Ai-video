"""FSM states for Voice Cloning flow."""
from aiogram.fsm.state import State, StatesGroup

class VoiceCloneSteps(StatesGroup):
    choosing_audio_source = State()
    waiting_reference = State()
    waiting_text = State()
    synthesizing = State()
    reviewing_audio = State()
