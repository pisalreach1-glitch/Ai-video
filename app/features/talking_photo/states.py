"""FSM states for Talking Photo feature."""
from aiogram.fsm.state import State, StatesGroup

class TalkingPhotoSteps(StatesGroup):
    waiting_photo = State()
    waiting_voice = State()
    reviewing_inputs = State()
    rendering = State()
    reviewing_video = State()
