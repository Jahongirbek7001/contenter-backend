"""User photos are kept 24 h after a generation finishes (for "re-create"), then deleted.
The bot's rules screen promises this to users."""

from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.media.store import MediaStore
from app.models import Generation

PHOTO_RETENTION = timedelta(hours=24)

log = structlog.get_logger(__name__)


async def delete_expired_photos(
    session_factory: async_sessionmaker[AsyncSession],
    store: MediaStore,
    now: datetime | None = None,
) -> int:
    cutoff = (now or datetime.now(UTC)) - PHOTO_RETENTION
    async with session_factory() as session, session.begin():
        generations = await session.scalars(
            select(Generation)
            .where(Generation.input_media_key.is_not(None), Generation.finished_at < cutoff)
            .with_for_update(skip_locked=True)
        )
        deleted = 0
        for generation in generations:
            if generation.input_media_key is not None:
                await store.delete(generation.input_media_key)
            generation.input_media_key = None
            deleted += 1
    if deleted:
        log.info("deleted expired photos", count=deleted)
    return deleted
