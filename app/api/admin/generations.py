from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.admin.deps import CurrentAdmin, SessionDep
from app.models import Generation, TrendTemplate, User
from app.models.enums import GenerationStatus, Product, Resolution

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
        select(Generation, User.telegram_id, TrendTemplate.title_uz)
        .join(User, User.id == Generation.user_id)
        .outerjoin(TrendTemplate, TrendTemplate.id == Generation.template_id)
        .order_by(Generation.id.desc())
        .offset(offset)
        .limit(PAGE_SIZE)
    )
    if status is not None:
        query = query.where(Generation.status == status)
    if customer_id is not None:
        query = query.where(Generation.user_id == customer_id)
    rows = await session.execute(query)
    return [
        GenerationRow(
            id=generation.id,
            customer_id=generation.user_id,
            telegram_id=telegram_id,
            product=generation.product,
            resolution=generation.resolution,
            status=generation.status,
            trend_title=title,
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
        for generation, telegram_id, title in rows
    ]


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
