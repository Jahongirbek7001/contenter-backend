from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.alerts import daily_text, failures_text
from app.domain.credits.service import grant_bonus
from app.domain.payments.orders import complete_payment, create_site_order, record_stars_payment
from app.domain.settings import DAILY_COST_ALERT_USD, set_setting
from app.domain.stats import TASHKENT, failed_between, report, today
from app.models import Generation, Pack, User
from app.models.enums import GenerationStatus, PaymentProvider, Product, Resolution
from app.worker import monitor_costs, monitor_failures

SessionFactory = async_sessionmaker[AsyncSession]
# 23:30 in Tashkent on 27.11 is still 27.11 there but 18:30 UTC.
NOW = datetime(2026, 11, 27, 23, 30, tzinfo=TASHKENT).astimezone(UTC)


async def seed(factory: SessionFactory) -> None:
    async with factory() as session, session.begin():
        buyer, quiet = User(telegram_id=1), User(telegram_id=2)
        session.add_all([buyer, quiet])
        await session.flush()
        for status, cost in (
            (GenerationStatus.SUCCEEDED, "0.60"),
            (GenerationStatus.FAILED, "0.10"),
            (GenerationStatus.BLOCKED, "0.05"),
        ):
            session.add(
                Generation(
                    user_id=buyer.id,
                    product=Product.TREND,
                    resolution=Resolution.P1080,
                    credits_cost=2,
                    status=status,
                    cost_usd=Decimal(cost),
                    error_code="provider_error" if status is GenerationStatus.FAILED else None,
                    finished_at=NOW - timedelta(minutes=5),
                )
            )
        pack_id = await session.scalar(select(Pack.id).where(Pack.code == "start"))
        assert pack_id is not None
        await record_stars_payment(session, buyer, pack_id, "charge", 210, NOW)
        order = await create_site_order(session, quiet, "popular", PaymentProvider.CLICK)
        await complete_payment(session, order, NOW)
        await grant_bonus(session, quiet.id, 3, "gift")


async def test_report_counts_one_tashkent_day(session_factory: SessionFactory) -> None:
    await seed(session_factory)
    day = today(NOW)
    async with session_factory() as session:
        result = await report(session, day - timedelta(days=1), day)
    totals = result.totals

    assert [item.day for item in result.days] == [day - timedelta(days=1), day]
    assert result.days[0].totals.generations == 0
    assert (totals.new_users, totals.generations) == (2, 3)
    assert (totals.succeeded, totals.failed, totals.blocked) == (1, 1, 1)
    assert totals.cost_usd == Decimal("0.75")
    assert (totals.payments, totals.revenue_uzs, totals.revenue_stars) == (2, 99_999, 210)
    assert (totals.credits_sold, totals.credits_gifted) == (5 + 15, 1 + 3)
    # 99 999 / 12 000 + 210 * 0.013 = 8.33 + 2.73
    assert round(totals.revenue_usd, 2) == Decimal("11.06")
    assert "Yangi mijozlar: 2" in daily_text(day, totals)
    assert "99 999 so'm + 210 ⭐" in daily_text(day, totals)


@dataclass
class FakeRedis:
    values: dict[str, bytes] = field(default_factory=dict)

    async def get(self, key: str) -> bytes | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, nx: bool = False, ex: int | None = None) -> bool:
        if nx and key in self.values:
            return False
        self.values[key] = value.encode()
        return True


@dataclass
class FakeNotifier:
    sent: list[tuple[int, str]] = field(default_factory=list)

    async def send(self, chat_id: int, text: str) -> bool:
        self.sent.append((chat_id, text))
        return True


def worker_ctx(factory: SessionFactory, chat_id: int | None = 42) -> dict[str, Any]:
    return {
        "session_factory": factory,
        "redis": FakeRedis(),
        "notifier": FakeNotifier(),
        "alert_chat_id": chat_id,
        "site_url": "https://contentor.wtf",
    }


async def test_failures_are_alerted_once(session_factory: SessionFactory) -> None:
    await seed(session_factory)
    real_now = datetime.now(UTC)
    async with session_factory() as session, session.begin():
        failed = await session.scalar(
            select(Generation).where(Generation.status == GenerationStatus.FAILED)
        )
        assert failed is not None
        failed.finished_at = real_now - timedelta(minutes=1)
    ctx = worker_ctx(session_factory)
    since = (real_now - timedelta(minutes=10)).isoformat()
    ctx["redis"].values["monitor:failures:since"] = since.encode()

    first = await monitor_failures(ctx)
    second = await monitor_failures(ctx)

    assert (first, second) == (1, 0)
    [(chat, text)] = ctx["notifier"].sent
    assert chat == 42
    assert "1 ta generatsiya xato" in text and "provider_error" in text


async def test_cost_alert_fires_once_and_respects_the_limit(
    session_factory: SessionFactory,
) -> None:
    await seed(session_factory)
    async with session_factory() as session, session.begin():
        generation = await session.scalar(select(Generation).limit(1))
        assert generation is not None
        # Today in real time, so the worker's "today" sees it.
        generation.created_at = datetime.now(UTC)
        generation.cost_usd = Decimal("5")
        await set_setting(session, DAILY_COST_ALERT_USD, 1)
    ctx = worker_ctx(session_factory)

    assert await monitor_costs(ctx) is True
    assert await monitor_costs(ctx) is False
    assert "chegara $1" in ctx["notifier"].sent[0][1]

    off = worker_ctx(session_factory, chat_id=None)
    assert await monitor_costs(off) is False


async def test_failure_window_uses_finish_time(session_factory: SessionFactory) -> None:
    await seed(session_factory)
    async with session_factory() as session:
        inside = await failed_between(session, NOW - timedelta(minutes=10), NOW)
        outside = await failed_between(session, NOW, NOW + timedelta(minutes=10))
    assert len(inside) == 1 and outside == []
    assert "#" in failures_text(inside, "https://x")
