"""Avatar backend protocol and capability definitions."""
from typing import Protocol, Callable
from app.features.talking_photo.domain import AvatarRequest, AvatarResult

class AvatarBackend(Protocol):
    @property
    def backend_id(self) -> str:
        ...

    async def is_available(self) -> bool:
        ...

    async def render(
        self,
        request: AvatarRequest,
        *,
        cancel_check: Callable[[], bool] | None = None,
        on_pid: Callable[[int], None] | None = None,
    ) -> AvatarResult:
        ...
