from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.miniapp.deps import MiniAppUserDep, SessionDep
from app.domain.credits.errors import InsufficientCreditsError
from app.domain.credits.service import get_balance
from app.domain.generations.start import (
    MAX_PHOTO_BYTES,
    InvalidPhotoError,
    PriceUnavailableError,
    TemplateUnavailableError,
    start_trend_generation,
    trend_price,
)
from app.models import Generation, TrendTemplate, User
from app.models.enums import GenerationStatus, Language, TrendAudience, TrendBadge

router = APIRouter(prefix="/miniapp", tags=["miniapp"])

TREND_JOB = "trend_generation"
HISTORY_LIMIT = 20


class MeOut(BaseModel):
    language: Language
    available: int
    held: int
    rules_accepted: bool
    trend_price: int


class MeUpdate(BaseModel):
    language: Language


class TrendCard(BaseModel):
    id: int
    slug: str
    title_uz: str
    title_ru: str
    category: str
    audience: TrendAudience
    badge: TrendBadge


class GenerationOut(BaseModel):
    id: int
    status: GenerationStatus
    trend_title_uz: str | None
    trend_title_ru: str | None
    created_at: datetime
    finished_at: datetime | None


class GenerationCreated(BaseModel):
    id: int


class ErrorDetail(BaseModel):
    code: str
    required: int | None = None
    available: int | None = None


async def _me(session: SessionDep, user: User) -> MeOut:
    balance = await get_balance(session, user.id)
    try:
        price = await trend_price(session)
    except PriceUnavailableError:
        price = 0
    return MeOut(
        language=user.language,
        available=balance.available,
        held=balance.held,
        rules_accepted=user.rules_accepted_at is not None,
        trend_price=price,
    )


@router.get("/me")
async def me(session: SessionDep, user: MiniAppUserDep) -> MeOut:
    return await _me(session, user)


@router.patch("/me")
async def update_me(body: MeUpdate, session: SessionDep, user: MiniAppUserDep) -> MeOut:
    user.language = body.language
    await session.commit()
    return await _me(session, user)


@router.post("/rules/accept")
async def accept_rules(session: SessionDep, user: MiniAppUserDep) -> MeOut:
    if user.rules_accepted_at is None:
        user.rules_accepted_at = datetime.now(UTC)
        await session.commit()
    return await _me(session, user)


@router.get("/trends")
async def list_trends(session: SessionDep, _: MiniAppUserDep) -> list[TrendCard]:
    trends = await session.scalars(
        select(TrendTemplate)
        .where(TrendTemplate.is_active)
        .order_by(TrendTemplate.sort_order, TrendTemplate.id)
    )
    return [
        TrendCard(
            id=trend.id,
            slug=trend.slug,
            title_uz=trend.title_uz,
            title_ru=trend.title_ru,
            category=trend.category,
            audience=trend.audience,
            badge=trend.badge,
        )
        for trend in trends
    ]


@router.get("/generations")
async def list_generations(session: SessionDep, user: MiniAppUserDep) -> list[GenerationOut]:
    rows = await session.execute(
        select(Generation, TrendTemplate.title_uz, TrendTemplate.title_ru)
        .outerjoin(TrendTemplate, TrendTemplate.id == Generation.template_id)
        .where(Generation.user_id == user.id)
        .order_by(Generation.id.desc())
        .limit(HISTORY_LIMIT)
    )
    return [
        GenerationOut(
            id=generation.id,
            status=generation.status,
            trend_title_uz=title_uz,
            trend_title_ru=title_ru,
            created_at=generation.created_at,
            finished_at=generation.finished_at,
        )
        for generation, title_uz, title_ru in rows
    ]


def _error(status_code: int, code: str, **values: int) -> HTTPException:
    return HTTPException(status_code, ErrorDetail(code=code, **values).model_dump())


@router.post("/generations", status_code=status.HTTP_201_CREATED)
async def create_generation(
    request: Request,
    session: SessionDep,
    user: MiniAppUserDep,
    template_id: Annotated[int, Form(gt=0)],
    photo: Annotated[UploadFile, File()],
) -> GenerationCreated:
    if user.rules_accepted_at is None:
        raise _error(status.HTTP_409_CONFLICT, "rules_required")
    data = await photo.read(MAX_PHOTO_BYTES + 1)
    if len(data) > MAX_PHOTO_BYTES:
        raise _error(status.HTTP_413_CONTENT_TOO_LARGE, "photo_too_big")
    try:
        generation = await start_trend_generation(
            session,
            request.app.state.media_store,
            user,
            template_id,
            data,
            photo.content_type or "",
        )
        await session.commit()
    except InsufficientCreditsError as exc:
        await session.rollback()
        raise _error(
            status.HTTP_402_PAYMENT_REQUIRED,
            "insufficient",
            required=exc.required,
            available=exc.available,
        ) from exc
    except TemplateUnavailableError as exc:
        await session.rollback()
        raise _error(status.HTTP_404_NOT_FOUND, "trend_unavailable") from exc
    except InvalidPhotoError as exc:
        await session.rollback()
        raise _error(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_photo") from exc
    await request.app.state.arq.enqueue_job(
        TREND_JOB, generation.id, _job_id=f"generation:{generation.id}"
    )
    return GenerationCreated(id=generation.id)
