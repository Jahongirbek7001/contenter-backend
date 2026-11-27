"""Business numbers for the dashboard, the daily report and the cost alert.

Days are counted in Tashkent time (UTC+5, no daylight saving).
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, case, cast, func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CreditLedgerEntry, Generation, Payment, User
from app.models.enums import GenerationStatus, LedgerKind, PaymentProvider, PaymentStatus

TASHKENT = timezone(timedelta(hours=5))
SQL_TZ = "Asia/Tashkent"
# Estimates for the margin (docs/plan.md): 1 USD = 12 000 so'm; a Star pays out about $0.013.
UZS_PER_USD = Decimal(12_000)
USD_PER_STAR = Decimal("0.013")


@dataclass(frozen=True)
class Totals:
    new_users: int = 0
    generations: int = 0
    succeeded: int = 0
    failed: int = 0
    blocked: int = 0
    cost_usd: Decimal = Decimal(0)
    payments: int = 0
    revenue_uzs: int = 0
    revenue_stars: int = 0
    credits_sold: int = 0
    credits_gifted: int = 0
    credits_spent: int = 0

    @property
    def revenue_usd(self) -> Decimal:
        return Decimal(self.revenue_uzs) / UZS_PER_USD + self.revenue_stars * USD_PER_STAR

    @property
    def margin_usd(self) -> Decimal:
        return self.revenue_usd - self.cost_usd


@dataclass(frozen=True)
class Day:
    day: date
    totals: Totals


@dataclass(frozen=True)
class Report:
    start: datetime
    end: datetime
    totals: Totals
    days: list[Day] = field(default_factory=list)


def day_start(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=TASHKENT).astimezone(UTC)


def today(now: datetime) -> date:
    return now.astimezone(TASHKENT).date()


def _local_day(column: Any) -> Any:
    return cast(func.timezone(SQL_TZ, column), Date)


async def report(session: AsyncSession, first_day: date, last_day: date) -> Report:
    """Totals and a per-day breakdown for [first_day, last_day] (Tashkent dates)."""
    start, end = day_start(first_day), day_start(last_day + timedelta(days=1))
    per_day: dict[date, dict[str, Any]] = {}

    def bucket(day: date) -> dict[str, Any]:
        return per_day.setdefault(day, {})

    users = await session.execute(
        select(_local_day(User.created_at), func.count())
        .where(User.created_at >= start, User.created_at < end)
        .group_by(literal_column("1"))
    )
    for day, count in users:
        bucket(day)["new_users"] = int(count)

    generations = await session.execute(
        select(
            _local_day(Generation.created_at),
            func.count(),
            func.count().filter(Generation.status == GenerationStatus.SUCCEEDED),
            func.count().filter(Generation.status == GenerationStatus.FAILED),
            func.count().filter(Generation.status == GenerationStatus.BLOCKED),
            func.coalesce(func.sum(Generation.cost_usd), 0),
        )
        .where(Generation.created_at >= start, Generation.created_at < end)
        .group_by(literal_column("1"))
    )
    for day, total, ok, failed, blocked, cost in generations:
        bucket(day).update(
            generations=int(total),
            succeeded=int(ok),
            failed=int(failed),
            blocked=int(blocked),
            cost_usd=Decimal(cost),
        )

    is_stars = Payment.provider == PaymentProvider.STARS
    payments = await session.execute(
        select(
            _local_day(Payment.paid_at),
            func.count(),
            func.coalesce(func.sum(case((is_stars, 0), else_=Payment.amount)), 0),
            func.coalesce(func.sum(case((is_stars, Payment.amount), else_=0)), 0),
        )
        .where(
            Payment.status == PaymentStatus.PAID, Payment.paid_at >= start, Payment.paid_at < end
        )
        .group_by(literal_column("1"))
    )
    for day, count, uzs, stars in payments:
        bucket(day).update(payments=int(count), revenue_uzs=int(uzs), revenue_stars=int(stars))

    ledger = await session.execute(
        select(
            _local_day(CreditLedgerEntry.created_at),
            func.coalesce(
                func.sum(CreditLedgerEntry.amount).filter(
                    CreditLedgerEntry.kind == LedgerKind.PURCHASE
                ),
                0,
            ),
            func.coalesce(
                func.sum(CreditLedgerEntry.amount).filter(
                    CreditLedgerEntry.kind == LedgerKind.BONUS
                ),
                0,
            ),
            # Spend is negative; a support refund gives part of it back.
            func.coalesce(
                -func.sum(CreditLedgerEntry.amount).filter(
                    CreditLedgerEntry.kind.in_((LedgerKind.SPEND, LedgerKind.REFUND))
                ),
                0,
            ),
        )
        .where(CreditLedgerEntry.created_at >= start, CreditLedgerEntry.created_at < end)
        .group_by(literal_column("1"))
    )
    for day, sold, gifted, spent in ledger:
        bucket(day).update(
            credits_sold=int(sold), credits_gifted=int(gifted), credits_spent=int(spent)
        )

    days = []
    cursor = first_day
    while cursor <= last_day:
        days.append(Day(cursor, Totals(**per_day.get(cursor, {}))))
        cursor += timedelta(days=1)
    return Report(start=start, end=end, totals=_sum(day.totals for day in days), days=days)


def _sum(items: Iterable[Totals]) -> Totals:
    totals = Totals()
    for item in items:
        totals = Totals(
            new_users=totals.new_users + item.new_users,
            generations=totals.generations + item.generations,
            succeeded=totals.succeeded + item.succeeded,
            failed=totals.failed + item.failed,
            blocked=totals.blocked + item.blocked,
            cost_usd=totals.cost_usd + item.cost_usd,
            payments=totals.payments + item.payments,
            revenue_uzs=totals.revenue_uzs + item.revenue_uzs,
            revenue_stars=totals.revenue_stars + item.revenue_stars,
            credits_sold=totals.credits_sold + item.credits_sold,
            credits_gifted=totals.credits_gifted + item.credits_gifted,
            credits_spent=totals.credits_spent + item.credits_spent,
        )
    return totals


async def failed_between(
    session: AsyncSession, since: datetime, until: datetime, limit: int = 20
) -> list[Generation]:
    """Technical failures that finished in [since, until); blocks are normal, not alerted."""
    rows = await session.scalars(
        select(Generation)
        .where(
            Generation.status == GenerationStatus.FAILED,
            Generation.finished_at >= since,
            Generation.finished_at < until,
        )
        .order_by(Generation.finished_at)
        .limit(limit)
    )
    return list(rows)
