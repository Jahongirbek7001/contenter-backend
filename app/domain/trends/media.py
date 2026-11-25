"""Trend assets managed from the admin cabinet: the catalog preview and the music track."""

import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.gateway.base import MusicProvider
from app.media.store import MediaStore
from app.models import MusicTrack, TrendTemplate

MUSIC_PROMPT_TEMPLATE = (
    "Original 30 second instrumental background music for a short vertical video, "
    "no vocals, no recognisable melodies. Mood: {mood}"
)
MAX_PREVIEW_UPLOAD_BYTES = 60 * 1024 * 1024

Transcoder = Callable[[bytes], Awaitable[bytes]]


class MissingMoodError(ValueError):
    pass


def music_prompt(mood: str) -> str:
    return MUSIC_PROMPT_TEMPLATE.format(mood=mood)


async def set_preview(
    session: AsyncSession,
    store: MediaStore,
    template: TrendTemplate,
    video: bytes,
    transcode: Transcoder,
) -> str:
    """Stores a transcoded preview; the bot re-uploads it to Telegram on first use."""
    preview = await transcode(video)
    key = f"previews/{template.id}/{uuid.uuid4().hex}.mp4"
    await store.save(key, preview)
    old_key = template.preview_storage_key
    template.preview_storage_key = key
    template.preview_file_id = None
    await session.flush()
    if old_key is not None:
        await store.delete(old_key)
    return key


async def save_track(
    session: AsyncSession, store: MediaStore, template_id: int, audio: bytes, mood: str
) -> MusicTrack:
    """The newest track becomes the only active one for the trend."""
    key = f"music/{template_id}/{uuid.uuid4().hex}.mp3"
    await store.save(key, audio)
    await session.execute(
        update(MusicTrack)
        .where(MusicTrack.template_id == template_id, MusicTrack.is_active)
        .values(is_active=False)
    )
    track = MusicTrack(template_id=template_id, storage_key=key, mood=mood[:64])
    session.add(track)
    await session.flush()
    return track


async def create_track(
    session: AsyncSession, music: MusicProvider, store: MediaStore, template: TrendTemplate
) -> MusicTrack:
    if not template.music_prompt:
        raise MissingMoodError(f"trend {template.id} has no music mood")
    result = await music.compose(music_prompt(template.music_prompt))
    return await save_track(session, store, template.id, result.data, template.music_prompt)
