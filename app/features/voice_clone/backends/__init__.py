"""Voice clone backends registry and selector."""
import os
from typing import Any

def get_voice_clone_backend() -> Any:
    """Return the active configured voice clone backend."""
    backend_id = os.getenv("VOICE_CLONE_BACKEND", "omnivoice").lower()
    if backend_id == "local":
        from app.features.voice_clone.backends.local import local_clone_backend
        return local_clone_backend
    from app.features.voice_clone.backends.omnivoice import omnivoice_backend
    return omnivoice_backend
