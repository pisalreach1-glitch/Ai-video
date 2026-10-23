"""Voice Conversion backend protocol."""
from typing import Protocol, Callable
from app.features.voice_conversion.domain import ConversionRequest, ConvertedAudio

class VoiceConversionBackend(Protocol):
    @property
    def backend_id(self) -> str:
        ...

    async def is_available(self) -> bool:
        ...

    async def convert(
        self,
        request: ConversionRequest,
        *,
        cancel_check: Callable[[], bool] | None = None,
        on_pid: Callable[[int], None] | None = None,
    ) -> ConvertedAudio:
        ...
