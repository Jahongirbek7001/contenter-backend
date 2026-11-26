"""Retention of user media. Photos are kept 24 h after a generation finishes (for
"re-create"); the bot's rules screen promises this to users. Finished videos are kept 30 days
for the admin cabinet (support, refunds); the user keeps their copy in Telegram."""

from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import InstrumentedAttribute

from app.media.store import MediaStore
from app.models import Generation

PHOTO_RETENTION = timedelta(hours=24)
VIDEO_RETENTION = timedelta(days=30)

log = structlog.get_logger(__name__)


async def delete_expired_photos(
    session_factory: async_sessionmaker[AsyncSession],
    store: MediaStore,
    now: datetime | None = None,
) -> int:
    cutoff = (now or datetime.now(UTC)) - PHOTO_RETENTION
    deleted = await _delete_expired(session_factory, store, Generation.input_media_key, cutoff)
    if deleted:
        log.info("deleted expired photos", count=deleted)
    return deleted


async def delete_expired_videos(
    session_factory: async_sessionmaker[AsyncSession],
    store: MediaStore,
    now: datetime | None = None,
) -> int:
    cutoff = (now or datetime.now(UTC)) - VIDEO_RETENTION
    deleted = await _delete_expired(session_factory, store, Generation.output_media_key, cutoff)
    if deleted:
        log.info("deleted expired videos", count=deleted)
    return deleted


async def _delete_expired(
    session_factory: async_sessionmaker[AsyncSession],
    store: MediaStore,
    column: InstrumentedAttribute[str | None],
    cutoff: datetime,
) -> int:
    async with session_factory() as session, session.begin():
        generations = await session.scalars(
            select(Generation)
            .where(column.is_not(None), Generation.finished_at < cutoff)
            .with_for_update(skip_locked=True)
        )
        deleted = 0
        for generation in generations:
            key = getattr(generation, column.key)
            if key is not None:
                await store.delete(key)
            setattr(generation, column.key, None)
            deleted += 1
    return deleted
