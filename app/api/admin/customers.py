import logging
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from arq.connections import ArqRedis
from fastapi import APIRouter, HTTPException, Path, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import Select, func, or_, select

from app.api.admin.deps import CurrentAdmin, EditorAdmin, SessionDep
from app.domain.credits.errors import InsufficientCreditsError
from app.domain.credits.service import adjust_credits, get_balance, grant_bonus
from app.domain.users import display_name
from app.models import (
    CreditHold,
    CreditLedgerEntry,
    Generation,
    Pack,
    Payment,
    TrendTemplate,
    User,
)
from app.models.enums import (
    GenerationStatus,
    HoldStatus,
    Language,
    LedgerKind,
    PaymentProvider,
    PaymentStatus,
    Product,
)

router = APIRouter(prefix="/customers")
logger = logging.getLogger(__name__)

BONUS_NOTICE_JOB = "bonus_notice"

PAGE_SIZE = 50
CustomerId = Annotated[int, Path(gt=0)]


class CustomerRow(BaseModel):
    id: int
    telegram_id: int
    name: str
    first_name: str | None
    last_name: str | None
    username: str | None
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


class CustomerPayment(BaseModel):
    id: int
    provider: PaymentProvider
    pack_title: str
    amount: int
    currency: str
    credits: int
    status: PaymentStatus
    created_at: datetime
    paid_at: datetime | None


class CustomerDetail(CustomerRow):
    rules_accepted_at: datetime | None
    referrer_id: int | None
    ledger: list[LedgerRow]
    recent_generations: list[CustomerGeneration]
    payments: list[CustomerPayment]


class CreditsIn(BaseModel):
    amount: int = Field(ge=-10_000, le=10_000)
    note: str = Field(min_length=3, max_length=200)
    # "bonus": a gift (positive only); "adjustment": a correction either way.
    kind: Literal["adjustment", "bonus"] = "adjustment"
    # Tell the customer in the bot (positive amounts only).
    notify: bool = False


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
        name=display_name(user),
        first_name=user.first_name,
        last_name=user.last_name,
        username=user.username,
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
    q: Annotated[str | None, Query(max_length=64)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[CustomerRow]:
    """`q`: a Telegram id, a name or a @username."""
    query = _customer_query().order_by(User.id.desc()).offset(offset).limit(PAGE_SIZE)
    term = (q or "").strip().removeprefix("@")
    if term.isdigit():
        query = query.where(User.telegram_id == int(term))
    elif term:
        pattern = f"%{term}%"
        query = query.where(
            or_(
                User.first_name.ilike(pattern),
                User.last_name.ilike(pattern),
                User.username.ilike(pattern),
                (User.first_name + " " + User.last_name).ilike(pattern),
            )
        )
    rows = await session.execute(query)
    return [_row(user, settled, held, count) for user, settled, held, count in rows]


@router.get("/{customer_id}")
async def get_customer(
    customer_id: CustomerId, session: SessionDep, _: CurrentAdmin
) -> CustomerDetail:
    return await _detail(session, customer_id)


@router.post("/{customer_id}/credits")
async def change_credits(
    customer_id: CustomerId,
    body: CreditsIn,
    session: SessionDep,
    admin: EditorAdmin,
    request: Request,
) -> CustomerDetail:
    if body.amount == 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "amount must not be zero")
    if body.kind == "bonus" and body.amount < 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "a bonus must be positive")
    await _load(session, customer_id)
    note = f"{admin.email}: {body.note}"
    try:
        if body.kind == "bonus":
            await grant_bonus(session, customer_id, body.amount, note)
        else:
            await adjust_credits(session, customer_id, body.amount, note)
    except InsufficientCreditsError as exc:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"only {exc.available} ⚡ available to take back"
        ) from exc
    await session.commit()
    if body.notify and body.amount > 0:
        arq: ArqRedis = request.app.state.arq
        try:
            await arq.enqueue_job(BONUS_NOTICE_JOB, customer_id, body.amount)
        except Exception:
            # The ⚡ are already credited; a lost message must not undo that.
            logger.exception("could not queue the bonus notice for customer %s", customer_id)
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
    payments = await session.execute(
        select(Payment, Pack.title_uz)
        .join(Pack, Pack.id == Payment.pack_id)
        .where(Payment.user_id == user.id)
        .order_by(Payment.id.desc())
        .limit(20)
    )
    return CustomerDetail(
        **_row(user, balance.settled, balance.held, generation_count or 0).model_dump(),
        rules_accepted_at=user.rules_accepted_at,
        referrer_id=user.referrer_id,
        payments=[
            CustomerPayment(
                id=payment.id,
                provider=payment.provider,
                pack_title=title,
                amount=payment.amount,
                currency=payment.currency,
                credits=payment.credits,
                status=payment.status,
                created_at=payment.created_at,
                paid_at=payment.paid_at,
            )
            for payment, title in payments
        ],
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
