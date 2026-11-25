from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Path, Request, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.admin.deps import CurrentAdmin, EditorAdmin, SessionDep
from app.api.media import file_response, preview_url
from app.domain.trends.media import (
    MAX_PREVIEW_UPLOAD_BYTES,
    MissingMoodError,
    create_track,
    set_preview,
)
from app.gateway.base import ProviderError
from app.media.ffmpeg import FfmpegError
from app.models import MusicTrack, TrendTemplate
from app.models.enums import TrendAudience, TrendBadge

router = APIRouter(prefix="/trends")

SLUG_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"
CATEGORIES = ("national", "seasonal", "cinematic", "lifestyle")
CATEGORY_PATTERN = "^(" + "|".join(CATEGORIES) + ")$"

TrendId = Annotated[int, Path(gt=0)]


class TrendFields(BaseModel):
    title_uz: str = Field(min_length=1, max_length=128)
    title_ru: str = Field(min_length=1, max_length=128)
    category: str = Field(pattern=CATEGORY_PATTERN)
    audience: TrendAudience
    badge: TrendBadge
    prompt_skeleton: str = Field(min_length=20, max_length=4000)
    first_frame_instructions: str = Field(min_length=20, max_length=4000)
    music_prompt: str | None = Field(default=None, max_length=1000)
    sort_order: int = Field(ge=0, le=100_000)
    is_active: bool


class TrendCreate(TrendFields):
    slug: str = Field(pattern=SLUG_PATTERN, max_length=64)


class TrendUpdate(BaseModel):
    """Partial update: only the fields that are sent change."""

    title_uz: str | None = Field(default=None, min_length=1, max_length=128)
    title_ru: str | None = Field(default=None, min_length=1, max_length=128)
    category: str | None = Field(default=None, pattern=CATEGORY_PATTERN)
    audience: TrendAudience | None = None
    badge: TrendBadge | None = None
    prompt_skeleton: str | None = Field(default=None, min_length=20, max_length=4000)
    first_frame_instructions: str | None = Field(default=None, min_length=20, max_length=4000)
    music_prompt: str | None = Field(default=None, max_length=1000)
    sort_order: int | None = Field(default=None, ge=0, le=100_000)
    is_active: bool | None = None


class TrendOut(TrendCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    has_preview: bool
    preview_url: str | None


class TrackOut(BaseModel):
    id: int
    mood: str
    is_active: bool
    created_at: datetime
    audio_url: str


def _out(trend: TrendTemplate) -> TrendOut:
    return TrendOut.model_validate(
        {
            **{f: getattr(trend, f) for f in TrendCreate.model_fields},
            "id": trend.id,
            "has_preview": trend.preview_storage_key is not None,
            "preview_url": preview_url(trend.id, trend.preview_storage_key),
        }
    )


@router.get("")
async def list_trends(session: SessionDep, _: CurrentAdmin) -> list[TrendOut]:
    trends = await session.scalars(
        select(TrendTemplate).order_by(TrendTemplate.sort_order, TrendTemplate.id)
    )
    return [_out(trend) for trend in trends]


@router.get("/{trend_id}")
async def get_trend(trend_id: TrendId, session: SessionDep, _: CurrentAdmin) -> TrendOut:
    return _out(await _load(session, trend_id))


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_trend(body: TrendCreate, session: SessionDep, _: EditorAdmin) -> TrendOut:
    trend = TrendTemplate(**body.model_dump())
    session.add(trend)
    try:
        await session.commit()
    except IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "slug already exists") from exc
    return _out(trend)


@router.patch("/{trend_id}")
async def update_trend(
    trend_id: TrendId, body: TrendUpdate, session: SessionDep, _: EditorAdmin
) -> TrendOut:
    trend = await _load(session, trend_id)
    changes = body.model_dump(exclude_unset=True)
    for field, value in changes.items():
        if value is None and field != "music_prompt":
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{field} cannot be null")
        setattr(trend, field, value)
    await session.commit()
    return _out(trend)


async def _load(session: SessionDep, trend_id: int) -> TrendTemplate:
    trend = await session.get(TrendTemplate, trend_id)
    if trend is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "trend not found")
    return trend


@router.post("/{trend_id}/preview")
async def upload_preview(
    trend_id: TrendId,
    request: Request,
    session: SessionDep,
    _: EditorAdmin,
    video: Annotated[UploadFile, File()],
) -> TrendOut:
    trend = await _load(session, trend_id)
    if not (video.content_type or "").startswith("video/"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "upload a video file")
    data = await video.read(MAX_PREVIEW_UPLOAD_BYTES + 1)
    if len(data) > MAX_PREVIEW_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "video is larger than 60 MB")
    try:
        await set_preview(
            session, request.app.state.media_store, trend, data, request.app.state.transcode
        )
    except FfmpegError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "could not read this video"
        ) from exc
    await session.commit()
    return _out(trend)


def _track_out(track: MusicTrack) -> TrackOut:
    return TrackOut(
        id=track.id,
        mood=track.mood,
        is_active=track.is_active,
        created_at=track.created_at,
        audio_url=f"/admin/trends/{track.template_id}/music/{track.id}.mp3",
    )


@router.get("/{trend_id}/music")
async def list_tracks(trend_id: TrendId, session: SessionDep, _: CurrentAdmin) -> list[TrackOut]:
    tracks = await session.scalars(
        select(MusicTrack)
        .where(MusicTrack.template_id == trend_id)
        .order_by(MusicTrack.id.desc())
        .limit(10)
    )
    return [_track_out(track) for track in tracks]


@router.post("/{trend_id}/music", status_code=status.HTTP_201_CREATED)
async def generate_track(
    trend_id: TrendId, request: Request, session: SessionDep, _: EditorAdmin
) -> TrackOut:
    """Calls Lyria (about $0.04 and 15 s); the new track replaces the active one."""
    trend = await _load(session, trend_id)
    try:
        track = await create_track(
            session, request.app.state.music_provider, request.app.state.media_store, trend
        )
    except MissingMoodError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "set the music mood first"
        ) from exc
    except ProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Lyria failed: {exc}") from exc
    await session.commit()
    await session.refresh(track)
    return _track_out(track)


@router.get("/{trend_id}/music/{track_id}.mp3", response_class=FileResponse)
async def track_audio(
    trend_id: TrendId,
    track_id: Annotated[int, Path(gt=0)],
    request: Request,
    session: SessionDep,
    _: CurrentAdmin,
) -> FileResponse:
    track = await session.get(MusicTrack, track_id)
    if track is None or track.template_id != trend_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "track not found")
    return file_response(request, track.storage_key, "audio/mpeg", max_age=3600)
