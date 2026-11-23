import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.credits import service
from app.domain.credits.errors import (
    HoldNotActiveError,
    InsufficientCreditsError,
    TrialAlreadyUsedError,
)
from app.models import Generation, Pack, Payment, User
from app.models.enums import PaymentProvider, PaymentStatus, Product, Resolution

SessionFactory = async_sessionmaker[AsyncSession]


async def create_user(factory: SessionFactory, telegram_id: int = 1001) -> int:
    async with factory() as session, session.begin():
        user = User(telegram_id=telegram_id)
        session.add(user)
        await session.flush()
        return user.id


async def create_generation(factory: SessionFactory, user_id: int, credits: int) -> int:
    async with factory() as session, session.begin():
        generation = Generation(
            user_id=user_id,
            product=Product.TALKING,
            resolution=Resolution.P720,
            credits_cost=credits,
        )
        session.add(generation)
        await session.flush()
        return generation.id


async def get_pack(session: AsyncSession, code: str) -> Pack:
    pack = await session.scalar(select(Pack).where(Pack.code == code))
    assert pack is not None
    return pack


async def pay(factory: SessionFactory, user_id: int, pack_code: str, tx_id: str) -> bool:
    async with factory() as session, session.begin():
        pack = await get_pack(session, pack_code)
        payment = await session.scalar(
            select(Payment).where(
                Payment.provider == PaymentProvider.PAYME, Payment.provider_tx_id == tx_id
            )
        )
        if payment is None:
            payment = Payment(
                user_id=user_id,
                pack_id=pack.id,
                provider=PaymentProvider.PAYME,
                provider_tx_id=tx_id,
                amount=pack.price_uzs,
                currency="UZS",
                credits=pack.credits,
                status=PaymentStatus.PAID,
            )
            session.add(payment)
            await session.flush()
        return await service.credit_payment(session, payment, pack)


async def balance(factory: SessionFactory, user_id: int) -> service.Balance:
    async with factory() as session:
        return await service.get_balance(session, user_id)


async def test_new_user_has_zero_balance(session_factory: SessionFactory) -> None:
    user_id = await create_user(session_factory)

    assert (await balance(session_factory, user_id)).available == 0


async def test_payment_credits_pack_and_bonus(session_factory: SessionFactory) -> None:
    user_id = await create_user(session_factory)

    assert await pay(session_factory, user_id, "popular", "tx-1") is True

    assert (await balance(session_factory, user_id)).available == 16


async def test_same_payment_is_credited_once(session_factory: SessionFactory) -> None:
    user_id = await create_user(session_factory)

    await pay(session_factory, user_id, "start", "tx-1")
    assert await pay(session_factory, user_id, "start", "tx-1") is False

    assert (await balance(session_factory, user_id)).available == 5


async def test_trial_pack_can_be_bought_once(session_factory: SessionFactory) -> None:
    user_id = await create_user(session_factory)
    await pay(session_factory, user_id, "trial", "tx-1")

    with pytest.raises(TrialAlreadyUsedError):
        await pay(session_factory, user_id, "trial", "tx-2")

    assert (await balance(session_factory, user_id)).available == 2


async def test_hold_reserves_credits(session_factory: SessionFactory) -> None:
    user_id = await create_user(session_factory)
    await pay(session_factory, user_id, "start", "tx-1")
    generation_id = await create_generation(session_factory, user_id, credits=3)

    async with session_factory() as session, session.begin():
        await service.hold_credits(session, user_id, generation_id, 3)

    result = await balance(session_factory, user_id)
    assert (result.settled, result.held, result.available) == (5, 3, 2)


async def test_hold_fails_without_enough_credits(session_factory: SessionFactory) -> None:
    user_id = await create_user(session_factory)
    await pay(session_factory, user_id, "trial", "tx-1")
    generation_id = await create_generation(session_factory, user_id, credits=3)

    with pytest.raises(InsufficientCreditsError) as error:
        async with session_factory() as session, session.begin():
            await service.hold_credits(session, user_id, generation_id, 3)

    assert (error.value.available, error.value.required) == (2, 3)


async def test_settle_spends_held_credits(session_factory: SessionFactory) -> None:
    user_id = await create_user(session_factory)
    await pay(session_factory, user_id, "start", "tx-1")
    generation_id = await create_generation(session_factory, user_id, credits=3)
    async with session_factory() as session, session.begin():
        await service.hold_credits(session, user_id, generation_id, 3)

    async with session_factory() as session, session.begin():
        await service.settle_hold(session, generation_id)

    result = await balance(session_factory, user_id)
    assert (result.settled, result.held, result.available) == (2, 0, 2)


async def test_release_returns_credits_after_failure(session_factory: SessionFactory) -> None:
    user_id = await create_user(session_factory)
    await pay(session_factory, user_id, "start", "tx-1")
    generation_id = await create_generation(session_factory, user_id, credits=3)
    async with session_factory() as session, session.begin():
        await service.hold_credits(session, user_id, generation_id, 3)

    async with session_factory() as session, session.begin():
        await service.release_hold(session, generation_id)

    assert (await balance(session_factory, user_id)).available == 5


async def test_hold_cannot_be_resolved_twice(session_factory: SessionFactory) -> None:
    user_id = await create_user(session_factory)
    await pay(session_factory, user_id, "start", "tx-1")
    generation_id = await create_generation(session_factory, user_id, credits=3)
    async with session_factory() as session, session.begin():
        await service.hold_credits(session, user_id, generation_id, 3)
    async with session_factory() as session, session.begin():
        await service.settle_hold(session, generation_id)

    with pytest.raises(HoldNotActiveError):
        async with session_factory() as session, session.begin():
            await service.release_hold(session, generation_id)

    assert (await balance(session_factory, user_id)).available == 2


async def test_concurrent_holds_never_overspend(session_factory: SessionFactory) -> None:
    user_id = await create_user(session_factory)
    await pay(session_factory, user_id, "start", "tx-1")  # 5 credits
    generation_ids = [await create_generation(session_factory, user_id, 3) for _ in range(2)]

    async def try_hold(generation_id: int) -> bool:
        try:
            async with session_factory() as session, session.begin():
                await service.hold_credits(session, user_id, generation_id, 3)
        except InsufficientCreditsError:
            return False
        return True

    results = await asyncio.gather(*(try_hold(gid) for gid in generation_ids))

    assert sorted(results) == [False, True]
    assert (await balance(session_factory, user_id)).available == 2
