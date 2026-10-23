"""Abstract base and registry for Voice Cloning backends."""
from abc import ABC, abstractmethod
from typing import Callable
from app.features.voice_clone.domain import CloneCapabilities, CloneRequest, CloneOutput

class BaseVoiceCloneBackend(ABC):
    @abstractmethod
    async def capabilities(self) -> CloneCapabilities:
        """Return declared hardware, language and reference audio constraints."""
        pass

    @abstractmethod
    async def synthesize(
        self,
        request: CloneRequest,
        *,
        cancel_check: Callable[[], bool],
        on_pid: Callable[[int], None],
    ) -> CloneOutput:
        """Synthesize cloned speech from reference audio and text."""
        pass
