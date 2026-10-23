"""Handlers registration module."""
from aiogram import Dispatcher
from app.handlers import (
    start,
    navigation,
    uploads,
    links,
    modes,
    speakers,
    dubbing,
    narration,
    settings,
    previews,
    jobs,
    history,
)
from app.features.talking_photo.handlers import router as talking_photo_router
from app.features.voice_clone.handlers import router as voice_clone_router

def register_all_handlers(dp: Dispatcher) -> None:
    """Register all routers into the aiogram Dispatcher in priority order."""
    dp.include_router(start.router)
    dp.include_router(navigation.router)
    dp.include_router(talking_photo_router)
    dp.include_router(voice_clone_router)
    dp.include_router(uploads.router)
    dp.include_router(links.router)
    dp.include_router(modes.router)
    dp.include_router(speakers.router)
    dp.include_router(dubbing.router)
    dp.include_router(narration.router)
    dp.include_router(settings.router)
    dp.include_router(previews.router)
    dp.include_router(jobs.router)
    dp.include_router(history.router)
