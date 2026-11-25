from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import Select, func, select

from app.api.admin.deps import CurrentAdmin, EditorAdmin, SessionDep
from app.domain.credits.errors import InsufficientCreditsError
from app.domain.credits.service import adjust_credits, get_balance
from app.models import CreditHold, CreditLedgerEntry, Generation, TrendTemplate, User
from app.models.enums import GenerationStatus, HoldStatus, Language, LedgerKind, Product

router = APIRouter(prefix="/customers")

PAGE_SIZE = 50
CustomerId = Annotated[int, Path(gt=0)]


class CustomerRow(BaseModel):
    id: int
    telegram_id: int
    language: Language
    is_blocked: bool
    created_at: datetime
    available: int
    held: int
    generations: int


class LedgerRow(BaseModel):
    id: int
    kind: LedgerKind
    amount: int
    note: str | None
    generation_id: int | None
    created_at: datetime


class CustomerGeneration(BaseModel):
    id: int
    product: Product
    status: GenerationStatus
    trend_title: str | None
    credits_cost: int
    cost_usd: Decimal | None
    error_code: str | None
    created_at: datetime


class CustomerDetail(CustomerRow):
    rules_accepted_at: datetime | None
    ledger: list[LedgerRow]
    recent_generations: list[CustomerGeneration]


class CreditsIn(BaseModel):
    amount: int = Field(ge=-10_000, le=10_000)
    note: str = Field(min_length=3, max_length=200)


class CustomerUpdate(BaseModel):
    is_blocked: bool


def _customer_query() -> Select[User, int, int, int]:
    settled = (
        select(func.coalesce(func.sum(CreditLedgerEntry.amount), 0))
        .where(CreditLedgerEntry.user_id == User.id)
        .scalar_subquery()
    )
    held = (
        select(func.coalesce(func.sum(CreditHold.amount), 0))
        .where(CreditHold.user_id == User.id, CreditHold.status == HoldStatus.ACTIVE)
        .scalar_subquery()
    )
    generations = (
        select(func.count(Generation.id)).where(Generation.user_id == User.id).scalar_subquery()
    )
    return select(User, settled, held, generations)


def _row(user: User, settled: int, held: int, generations: int) -> CustomerRow:
    return CustomerRow(
        id=user.id,
        telegram_id=user.telegram_id,
        language=user.language,
        is_blocked=user.is_blocked,
        created_at=user.created_at,
        available=int(settled) - int(held),
        held=int(held),
        generations=int(generations),
    )


@router.get("")
async def list_customers(
    session: SessionDep,
    _: CurrentAdmin,
    telegram_id: Annotated[int | None, Query(gt=0)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[CustomerRow]:
    query = _customer_query().order_by(User.id.desc()).offset(offset).limit(PAGE_SIZE)
    if telegram_id is not None:
        query = query.where(User.telegram_id == telegram_id)
    rows = await session.execute(query)
    return [_row(user, settled, held, count) for user, settled, held, count in rows]


@router.get("/{customer_id}")
async def get_customer(
    customer_id: CustomerId, session: SessionDep, _: CurrentAdmin
) -> CustomerDetail:
    return await _detail(session, customer_id)


@router.post("/{customer_id}/credits")
async def change_credits(
    customer_id: CustomerId, body: CreditsIn, session: SessionDep, admin: EditorAdmin
) -> CustomerDetail:
    if body.amount == 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "amount must not be zero")
    await _load(session, customer_id)
    try:
        await adjust_credits(session, customer_id, body.amount, f"{admin.email}: {body.note}")
    except InsufficientCreditsError as exc:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"only {exc.available} ⚡ available to take back"
        ) from exc
    await session.commit()
    return await _detail(session, customer_id)


@router.patch("/{customer_id}")
async def update_customer(
    customer_id: CustomerId, body: CustomerUpdate, session: SessionDep, _: EditorAdmin
) -> CustomerDetail:
    user = await _load(session, customer_id)
    user.is_blocked = body.is_blocked
    await session.commit()
    return await _detail(session, customer_id)


async def _load(session: SessionDep, customer_id: int) -> User:
    user = await session.get(User, customer_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "customer not found")
    return user


async def _detail(session: SessionDep, customer_id: int) -> CustomerDetail:
    user = await _load(session, customer_id)
    balance = await get_balance(session, user.id)
    generation_count = await session.scalar(
        select(func.count(Generation.id)).where(Generation.user_id == user.id)
    )
    ledger = await session.scalars(
        select(CreditLedgerEntry)
        .where(CreditLedgerEntry.user_id == user.id)
        .order_by(CreditLedgerEntry.id.desc())
        .limit(PAGE_SIZE)
    )
    generations = await session.execute(
        select(Generation, TrendTemplate.title_uz)
        .outerjoin(TrendTemplate, TrendTemplate.id == Generation.template_id)
        .where(Generation.user_id == user.id)
        .order_by(Generation.id.desc())
        .limit(20)
    )
    return CustomerDetail(
        **_row(user, balance.settled, balance.held, generation_count or 0).model_dump(),
        rules_accepted_at=user.rules_accepted_at,
        ledger=[
            LedgerRow(
                id=entry.id,
                kind=entry.kind,
                amount=entry.amount,
                note=entry.note,
                generation_id=entry.generation_id,
                created_at=entry.created_at,
            )
            for entry in ledger
        ],
        recent_generations=[
            CustomerGeneration(
                id=generation.id,
                product=generation.product,
                status=generation.status,
                trend_title=title,
                credits_cost=generation.credits_cost,
                cost_usd=generation.cost_usd,
                error_code=generation.error_code,
                created_at=generation.created_at,
            )
            for generation, title in generations
        ],
    )
