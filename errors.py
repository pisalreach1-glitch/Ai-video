"""
Error hierarchy and standardized processing results for Video Bot.
Provides distinct error classes for:
- QuotaExceededError (API rate limits / exhausted quota)
- NetworkError (Connectivity, DNS, timeouts)
- CorruptMediaError (Corrupt or unreadable media files)
- NoAudioStreamError (Video contains no audio stream)
- NoSpeechDetectedError (Audio contains no spoken words)
- ProcessTimeoutError (Subprocess exceeded real timeout)
- JobCancelledError (Job cancelled by user)
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any


class BotProcessingError(Exception):
    """Base exception for all Bot processing errors."""
    def __init__(
        self,
        message: str,
        user_friendly_message: Optional[str] = None,
        job_id: Optional[str] = None,
        error_code: Optional[str] = None
    ):
        super().__init__(message)
        self.message = message
        self.user_friendly_message = user_friendly_message or message
        self.job_id = job_id
        self.error_code = error_code or "PROCESSING_ERROR"

    def __str__(self):
        job_tag = f" [Job {self.job_id}]" if self.job_id else ""
        return f"{self.error_code}{job_tag}: {self.message}"


class QuotaExceededError(BotProcessingError):
    """Raised when API quota or rate limits are exceeded."""
    def __init__(self, message: str = "API quota exceeded", job_id: Optional[str] = None):
        super().__init__(
            message=message,
            user_friendly_message="⚠️ Cloud AI Quota ត្រូវបានប្រើប្រាស់អស់ជាបណ្តោះអាសន្ន។ ប្តូរទៅប្រើ Local Mode ដោយស្វ័យប្រវត្តិ។",
            job_id=job_id,
            error_code="QUOTA_EXCEEDED"
        )


class NetworkError(BotProcessingError):
    """Raised when network connectivity fails or timeouts occur."""
    def __init__(self, message: str = "Network connection failed or timed out", job_id: Optional[str] = None):
        super().__init__(
            message=message,
            user_friendly_message="📡 ជួបបញ្ហាការតភ្ជាប់បណ្តាញអ៊ីនធឺណិត។ សូមព្យាយាមម្តងទៀតនៅពេលបន្តិចទៀត។",
            job_id=job_id,
            error_code="NETWORK_ERROR"
        )


class CorruptMediaError(BotProcessingError):
    """Raised when media is corrupt, incomplete, or unreadable."""
    def __init__(self, message: str = "Media file is corrupt or unreadable", job_id: Optional[str] = None):
        super().__init__(
            message=message,
            user_friendly_message="❌ ឯកសារវីដេអូខូចខាត ឬមិនពេញលេញ (Corrupted Media)។ សូមផ្ញើវីដេអូឡើងវិញ។",
            job_id=job_id,
            error_code="CORRUPT_MEDIA"
        )


class NoAudioStreamError(BotProcessingError):
    """Raised when video file has no audio stream at all."""
    def __init__(self, message: str = "Video contains no audio stream", job_id: Optional[str] = None):
        super().__init__(
            message=message,
            user_friendly_message="🔇 វីដេអូនេះគ្មានសំឡេងឡើយ (No Audio Track Found)។ សូមផ្ញើវីដេអូដែលមានសំឡេងនិយាយ។",
            job_id=job_id,
            error_code="NO_AUDIO_STREAM"
        )


class NoSpeechDetectedError(BotProcessingError):
    """Raised when audio was analyzed but no speech/words were detected."""
    def __init__(self, message: str = "No spoken words detected in audio", job_id: Optional[str] = None):
        super().__init__(
            message=message,
            user_friendly_message="🎙️ មិនបានរកឃើញសំឡេងមនុស្សនិយាយនៅក្នុងវីដេអូនេះឡើយ (No Speech Detected)។",
            job_id=job_id,
            error_code="NO_SPEECH_DETECTED"
        )


class ProcessTimeoutError(BotProcessingError):
    """Raised when a subprocess exceeds its configured real timeout."""
    def __init__(self, message: str = "Subprocess exceeded configured timeout", job_id: Optional[str] = None):
        super().__init__(
            message=message,
            user_friendly_message="⏱️ ដំណើរការ Render លើសពីពេលវេលាកំណត់ (Subprocess Timed Out)។",
            job_id=job_id,
            error_code="PROCESS_TIMEOUT"
        )


class JobCancelledError(BotProcessingError):
    """Raised when a job is cancelled by user."""
    def __init__(self, message: str = "Job was cancelled by user", job_id: Optional[str] = None):
        super().__init__(
            message=message,
            user_friendly_message="🛑 ការងារត្រូវបានបោះបង់ដោយជោគជ័យ (Job Cancelled)។",
            job_id=job_id,
            error_code="JOB_CANCELLED"
        )


@dataclass
class ProcessingResult:
    """
    Standardized return object for video and subtitle processing.
    Never returns input path as output; explicitly conveys status and outputs.
    """
    success: bool
    output_path: Optional[str] = None
    job_id: Optional[str] = None
    error: Optional[BotProcessingError] = None
    error_code: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    @classmethod
    def ok(cls, output_path: str, job_id: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> "ProcessingResult":
        return cls(
            success=True,
            output_path=output_path,
            job_id=job_id,
            metadata=metadata or {}
        )

    @classmethod
    def fail(cls, error: BotProcessingError, job_id: Optional[str] = None) -> "ProcessingResult":
        return cls(
            success=False,
            output_path=None,
            job_id=job_id or error.job_id,
            error=error,
            error_code=error.error_code
        )
