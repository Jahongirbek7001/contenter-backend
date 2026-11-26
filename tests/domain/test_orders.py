from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.credits.service import get_balance
from app.domain.payments.orders import (
    REFERRAL_BONUS,
    OrderError,
    check_payable,
    complete_payment,
    create_site_order,
    record_stars_payment,
)
from app.domain.promo import PromoError, redeem_promo
from app.models import Pack, PromoCode, User
from app.models.enums import PaymentProvider

SessionFactory = async_sessionmaker[AsyncSession]
NOW = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)


async def new_user(
    factory: SessionFactory, telegram_id: int, referrer_id: int | None = None
) -> int:
    async with factory() as session, session.begin():
        user = User(telegram_id=telegram_id, referrer_id=referrer_id)
        session.add(user)
        await session.flush()
        return user.id


async def available(factory: SessionFactory, user_id: int) -> int:
    async with factory() as session:
        return (await get_balance(session, user_id)).available


async def pack_id(factory: SessionFactory, code: str) -> int:
    async with factory() as session:
        found = await session.scalar(select(Pack.id).where(Pack.code == code))
        assert found is not None
        return found


async def stars(factory: SessionFactory, user_id: int, code: str, charge: str) -> bool:
    async with factory() as session, session.begin():
        user = await session.get(User, user_id)
        assert user is not None
        result = await record_stars_payment(
            session, user, await pack_id(factory, code), charge, 210, NOW
        )
        return result.credited


async def test_stars_payment_is_credited_once_per_charge(session_factory: SessionFactory) -> None:
    user_id = await new_user(session_factory, 1)

    assert await stars(session_factory, user_id, "popular", "charge-1") is True
    assert await stars(session_factory, user_id, "popular", "charge-1") is False

    assert await available(session_factory, user_id) == 16


async def test_referral_bonus_comes_with_the_first_purchase_only(
    session_factory: SessionFactory,
) -> None:
    inviter = await new_user(session_factory, 1)
    friend = await new_user(session_factory, 2, referrer_id=inviter)

    await stars(session_factory, friend, "start", "charge-1")
    await stars(session_factory, friend, "start", "charge-2")

    assert await available(session_factory, inviter) == REFERRAL_BONUS
    assert await available(session_factory, friend) == 5 + 5 + REFERRAL_BONUS


async def test_trial_is_not_sold_twice_but_a_paid_race_is_still_credited(
    session_factory: SessionFactory,
) -> None:
    user_id = await new_user(session_factory, 1)
    async with session_factory() as session, session.begin():
        user = await session.get(User, user_id)
        assert user is not None
        first = await create_site_order(session, user, "trial", PaymentProvider.PAYME)
        second = await create_site_order(session, user, "trial", PaymentProvider.CLICK)
        # Payme accepted the first order: the second can no longer be paid.
        first.provider_tx_id = "payme-1"
        await session.flush()
        with pytest.raises(OrderError) as error:
            await check_payable(session, second)
        assert error.value.reason == "trial_used"
        # Money for the first order arrived after all: it is credited.
        await complete_payment(session, first, NOW)
        with pytest.raises(OrderError):
            await create_site_order(session, user, "trial", PaymentProvider.PAYME)

    assert await available(session_factory, user_id) == 2


async def test_blocked_customer_cannot_order(session_factory: SessionFactory) -> None:
    user_id = await new_user(session_factory, 1)
    async with session_factory() as session, session.begin():
        user = await session.get(User, user_id)
        assert user is not None
        user.is_blocked = True
        with pytest.raises(OrderError) as error:
            await create_site_order(session, user, "start", PaymentProvider.CLICK)
    assert error.value.reason == "blocked"


async def promo(factory: SessionFactory, **fields: object) -> None:
    async with factory() as session, session.begin():
        session.add(PromoCode(**fields))


async def redeem(factory: SessionFactory, user_id: int, code: str) -> int | str:
    async with factory() as session, session.begin():
        try:
            return await redeem_promo(session, user_id, code, NOW)
        except PromoError as exc:
            return exc.reason


async def test_promo_code_rules(session_factory: SessionFactory) -> None:
    first, second = await new_user(session_factory, 1), await new_user(session_factory, 2)
    await promo(session_factory, code="NAVRUZ", credits=3, max_uses=1)
    await promo(session_factory, code="OLD", credits=1, expires_at=NOW - timedelta(days=1))
    await promo(session_factory, code="OFF", credits=1, is_active=False)

    assert await redeem(session_factory, first, " navruz ") == 3
    assert await redeem(session_factory, first, "NAVRUZ") == "already_used"
    assert await redeem(session_factory, second, "NAVRUZ") == "used_up"
    assert await redeem(session_factory, second, "OLD") == "expired"
    assert await redeem(session_factory, second, "OFF") == "not_found"
    assert await redeem(session_factory, second, "NOPE") == "not_found"
    assert await available(session_factory, first) == 3
