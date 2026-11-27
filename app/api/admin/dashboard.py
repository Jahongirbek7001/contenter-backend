from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.api.admin.deps import CurrentAdmin, SessionDep
from app.domain.stats import USD_PER_STAR, UZS_PER_USD, Totals, report, today

router = APIRouter(prefix="/dashboard")


class TotalsOut(BaseModel):
    new_users: int
    generations: int
    succeeded: int
    failed: int
    blocked: int
    cost_usd: Decimal
    payments: int
    revenue_uzs: int
    revenue_stars: int
    revenue_usd: Decimal
    margin_usd: Decimal
    credits_sold: int
    credits_gifted: int
    credits_spent: int

    @classmethod
    def of(cls, totals: Totals) -> "TotalsOut":
        return cls(
            new_users=totals.new_users,
            generations=totals.generations,
            succeeded=totals.succeeded,
            failed=totals.failed,
            blocked=totals.blocked,
            cost_usd=round(totals.cost_usd, 2),
            payments=totals.payments,
            revenue_uzs=totals.revenue_uzs,
            revenue_stars=totals.revenue_stars,
            revenue_usd=round(totals.revenue_usd, 2),
            margin_usd=round(totals.margin_usd, 2),
            credits_sold=totals.credits_sold,
            credits_gifted=totals.credits_gifted,
            credits_spent=totals.credits_spent,
        )


class DayOut(TotalsOut):
    day: date


class DashboardOut(BaseModel):
    first_day: date
    last_day: date
    totals: TotalsOut
    days: list[DayOut]
    # How the margin is estimated, so the cabinet can say so.
    uzs_per_usd: Decimal
    usd_per_star: Decimal


@router.get("")
async def dashboard(
    session: SessionDep,
    _: CurrentAdmin,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> DashboardOut:
    last_day = today(datetime.now(UTC))
    first_day = last_day - timedelta(days=days - 1)
    result = await report(session, first_day, last_day)
    return DashboardOut(
        first_day=first_day,
        last_day=last_day,
        totals=TotalsOut.of(result.totals),
        days=[
            DayOut(day=item.day, **TotalsOut.of(item.totals).model_dump()) for item in result.days
        ],
        uzs_per_usd=UZS_PER_USD,
        usd_per_star=USD_PER_STAR,
    )
