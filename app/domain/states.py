"""State machine definitions for jobs and wizard."""
from enum import Enum
from aiogram.fsm.state import State, StatesGroup

class JobState(str, Enum):
    AWAITING_SOURCE = "awaiting_source"
    AWAITING_URL = "awaiting_url"
    DOWNLOADING = "downloading"
    AWAITING_MODE = "awaiting_mode"
    AWAITING_TEXT = "awaiting_text"
    AWAITING_SETTINGS = "awaiting_settings"
    ANALYZING_SOURCE = "analyzing_source"
    TRANSLATING_SEGMENTS = "translating_segments"
    AWAITING_SEGMENT_REVIEW = "awaiting_segment_review"
    GENERATING_SEGMENTS = "generating_segments"
    CHECKING_FIT = "checking_fit"
    AWAITING_FIT_RESOLUTION = "awaiting_fit_resolution"
    ASSEMBLING_TIMELINE = "assembling_timeline"
    AUDIO_QUEUED = "audio_queued"
    GENERATING_AUDIO = "generating_audio"
    AWAITING_AUDIO_REVIEW = "awaiting_audio_review"
    AWAITING_DURATION_CHOICE = "awaiting_duration_choice"
    PREVIEW_QUEUED = "preview_queued"
    PREVIEW_RENDERING = "preview_rendering"
    AWAITING_APPROVAL = "awaiting_approval"
    FINAL_QUEUED = "final_queued"
    RENDERING = "rendering"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DELIVERY_FAILED = "delivery_failed"
    INTERRUPTED = "interrupted"

# FSM States for aiogram wizard conversation
class WizardStep(StatesGroup):
    idle = State()
    awaiting_video_source = State()
    awaiting_url_input = State()
    mode_choice = State()
    awaiting_narration_text = State()
    editing_narration_text = State()
    customizing_settings = State()
    audio_review = State()
    duration_choice = State()
    preview_review = State()
    rendering_in_progress = State()
    dubbing_review = State()
    editing_segment_text = State()
    resolving_fit = State()
