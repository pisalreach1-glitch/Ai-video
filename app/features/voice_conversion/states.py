"""FSM states for Voice Conversion flow."""
from aiogram.fsm.state import State, StatesGroup

class VoiceConversionSteps(StatesGroup):
    waiting_target_reference = State()
    waiting_full_source = State()
    reviewing_inputs = State()
    converting = State()
    reviewing_conversion = State()
