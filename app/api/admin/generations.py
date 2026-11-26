from datetime import datetime
from decimal import Decimal
from typing import Annotated

from arq.connections import ArqRedis
from fastapi import APIRouter, HTTPException, Path, Query, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.admin.deps import CurrentAdmin, EditorAdmin, SessionDep
from app.api.media import file_response
from app.domain.credits.errors import InsufficientCreditsError, NotRefundableError
from app.domain.credits.service import refund_generation
from app.domain.generations.jobs import job_for, job_id
from app.domain.generations.start import NotRerunnableError, UserBlockedError, rerun_generation
from app.domain.talking.script import Script
from app.models import CreditLedgerEntry, Generation, ScriptStyle, TrendTemplate, User
from app.models.enums import GenerationStatus, LedgerKind, Product, Resolution

router = APIRouter(prefix="/generations")

PAGE_SIZE = 50


class GenerationRow(BaseModel):
    id: int
    customer_id: int
    telegram_id: int
    product: Product
    resolution: Resolution
    status: GenerationStatus
    trend_title: str | None
    style_title: str | None
    credits_cost: int
    cost_usd: Decimal | None
    model: str | None
    error_code: str | None
    created_at: datetime
    finished_at: datetime | None
    seconds: float | None


class GenerationStats(BaseModel):
    total: int
    succeeded: int
    failed: int
    blocked: int
    in_progress: int
    cost_usd: Decimal


@router.get("")
async def list_generations(
    session: SessionDep,
    _: CurrentAdmin,
    status: Annotated[GenerationStatus | None, Query()] = None,
    customer_id: Annotated[int | None, Query(gt=0)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[GenerationRow]:
    query = (
        select(Generation, User.telegram_id, TrendTemplate.title_uz, ScriptStyle.title_uz)
        .join(User, User.id == Generation.user_id)
        .outerjoin(TrendTemplate, TrendTemplate.id == Generation.template_id)
        .outerjoin(ScriptStyle, ScriptStyle.id == Generation.style_id)
        .order_by(Generation.id.desc())
        .offset(offset)
        .limit(PAGE_SIZE)
    )
    if status is not None:
        query = query.where(Generation.status == status)
    if customer_id is not None:
        query = query.where(Generation.user_id == customer_id)
    rows = await session.execute(query)
    return [_row(*row) for row in rows]


def _row(
    generation: Generation, telegram_id: int, trend_title: str | None, style_title: str | None
) -> GenerationRow:
    return GenerationRow(
        id=generation.id,
        customer_id=generation.user_id,
        telegram_id=telegram_id,
        product=generation.product,
        resolution=generation.resolution,
        status=generation.status,
        trend_title=trend_title,
        style_title=style_title,
        credits_cost=generation.credits_cost,
        cost_usd=generation.cost_usd,
        model=generation.model,
        error_code=generation.error_code,
        created_at=generation.created_at,
        finished_at=generation.finished_at,
        seconds=(
            (generation.finished_at - generation.created_at).total_seconds()
            if generation.finished_at
            else None
        ),
    )


@router.get("/stats")
async def generation_stats(session: SessionDep, _: CurrentAdmin) -> GenerationStats:
    counts = dict(
        (status, count)
        for status, count in await session.execute(
            select(Generation.status, func.count(Generation.id)).group_by(Generation.status)
        )
    )
    cost = await session.scalar(select(func.coalesce(func.sum(Generation.cost_usd), 0)))
    return GenerationStats(
        total=sum(counts.values()),
        succeeded=counts.get(GenerationStatus.SUCCEEDED, 0),
        failed=counts.get(GenerationStatus.FAILED, 0),
        blocked=counts.get(GenerationStatus.BLOCKED, 0),
        in_progress=counts.get(GenerationStatus.PENDING, 0)
        + counts.get(GenerationStatus.PROCESSING, 0),
        cost_usd=Decimal(cost or 0),
    )


GenerationId = Annotated[int, Path(gt=0)]


class GenerationDetail(GenerationRow):
    idea: str | None
    script_lines: list[str]
    story_bible: str | None
    prompt: str | None
    subtitles: bool
    contact_text: str | None
    provider_job_id: str | None
    source_generation_id: int | None
    video_url: str | None
    has_photo: bool
    refunded: bool
    can_refund: bool
    can_rerun: bool


class Rerun(BaseModel):
    id: int


@router.get("/{generation_id}")
async def get_generation(
    generation_id: GenerationId, session: SessionDep, _: CurrentAdmin
) -> GenerationDetail:
    return await _detail(session, generation_id)


@router.get("/{generation_id}/video.mp4")
async def generation_video(
    generation_id: GenerationId, request: Request, session: SessionDep, _: CurrentAdmin
) -> FileResponse:
    generation = await session.get(Generation, generation_id)
    if generation is None or generation.output_media_key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no stored video")
    # Private: user faces. Never cached by shared caches.
    response = file_response(request, generation.output_media_key, "video/mp4", max_age=0)
    response.headers["Cache-Control"] = "private, no-store"
    return response


@router.post("/{generation_id}/refund")
async def refund(
    generation_id: GenerationId, session: SessionDep, admin: EditorAdmin
) -> GenerationDetail:
    await _detail(session, generation_id)
    try:
        await refund_generation(session, generation_id, f"{admin.email}: refund #{generation_id}")
    except NotRefundableError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, exc.reason) from exc
    await session.commit()
    return await _detail(session, generation_id)


@router.post("/{generation_id}/rerun", status_code=status.HTTP_201_CREATED)
async def rerun(
    generation_id: GenerationId, request: Request, session: SessionDep, _: EditorAdmin
) -> Rerun:
    await _detail(session, generation_id)
    try:
        generation = await rerun_generation(session, request.app.state.media_store, generation_id)
    except NotRerunnableError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, exc.code) from exc
    except InsufficientCreditsError as exc:
        await session.rollback()
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            f"customer has {exc.available} ⚡, needs {exc.required}",
        ) from exc
    except UserBlockedError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "customer_blocked") from exc
    await session.commit()
    arq: ArqRedis = request.app.state.arq
    await arq.enqueue_job(job_for(generation.product), generation.id, _job_id=job_id(generation.id))
    return Rerun(id=generation.id)


async def _detail(session: SessionDep, generation_id: int) -> GenerationDetail:
    row = (
        await session.execute(
            select(Generation, User.telegram_id, TrendTemplate.title_uz, ScriptStyle.title_uz)
            .join(User, User.id == Generation.user_id)
            .outerjoin(TrendTemplate, TrendTemplate.id == Generation.template_id)
            .outerjoin(ScriptStyle, ScriptStyle.id == Generation.style_id)
            .where(Generation.id == generation_id)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "generation not found")
    generation = row[0]
    kinds = set(
        await session.scalars(
            select(CreditLedgerEntry.kind).where(CreditLedgerEntry.generation_id == generation_id)
        )
    )
    script = Script.from_json(generation.script) if generation.script else None
    refunded = LedgerKind.REFUND in kinds
    return GenerationDetail(
        **_row(*row).model_dump(),
        idea=generation.user_input,
        script_lines=list(script.lines) if script else [],
        story_bible=script.story_bible if script else None,
        prompt=generation.prompt,
        subtitles=generation.subtitles,
        contact_text=generation.contact_text,
        provider_job_id=generation.provider_job_id,
        source_generation_id=generation.source_generation_id,
        video_url=(
            f"/admin/generations/{generation.id}/video.mp4" if generation.output_media_key else None
        ),
        has_photo=generation.input_media_key is not None,
        refunded=refunded,
        can_refund=LedgerKind.SPEND in kinds and not refunded,
        can_rerun=(
            generation.status in (GenerationStatus.FAILED, GenerationStatus.BLOCKED)
            and generation.input_media_key is not None
        ),
    )
