from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.admin.deps import CurrentAdmin, EditorAdmin, SessionDep
from app.models import TrendTemplate
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


def _out(trend: TrendTemplate) -> TrendOut:
    return TrendOut.model_validate(
        {
            **{f: getattr(trend, f) for f in TrendCreate.model_fields},
            "id": trend.id,
            "has_preview": trend.preview_file_id is not None,
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
