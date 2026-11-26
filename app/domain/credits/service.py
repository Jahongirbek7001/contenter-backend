"""⚡ credit ledger.

All functions run inside the caller's transaction and never commit. Operations that
change what a user can spend lock the user row first, so concurrent requests for the
same user are serialized and the balance can never go negative.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.credits.errors import (
    HoldNotActiveError,
    InsufficientCreditsError,
    NotRefundableError,
    TrialAlreadyUsedError,
)
from app.models import CreditHold, CreditLedgerEntry, Pack, Payment, User
from app.models.enums import HoldStatus, LedgerKind


@dataclass(frozen=True)
class Balance:
    settled: int
    held: int

    @property
    def available(self) -> int:
        return self.settled - self.held


async def get_balance(session: AsyncSession, user_id: int) -> Balance:
    settled = await session.scalar(
        select(func.coalesce(func.sum(CreditLedgerEntry.amount), 0)).where(
            CreditLedgerEntry.user_id == user_id
        )
    )
    held = await session.scalar(
        select(func.coalesce(func.sum(CreditHold.amount), 0)).where(
            CreditHold.user_id == user_id, CreditHold.status == HoldStatus.ACTIVE
        )
    )
    return Balance(settled=int(settled or 0), held=int(held or 0))


async def hold_credits(
    session: AsyncSession, user_id: int, generation_id: int, amount: int
) -> CreditHold:
    await _lock_user(session, user_id)
    balance = await get_balance(session, user_id)
    if balance.available < amount:
        raise InsufficientCreditsError(available=balance.available, required=amount)
    hold = CreditHold(user_id=user_id, generation_id=generation_id, amount=amount)
    session.add(hold)
    await session.flush()
    return hold


async def settle_hold(session: AsyncSession, generation_id: int) -> None:
    """Generation succeeded: the reserved credits are spent."""
    hold = await _lock_active_hold(session, generation_id)
    hold.status = HoldStatus.SETTLED
    hold.resolved_at = datetime.now(UTC)
    session.add(
        CreditLedgerEntry(
            user_id=hold.user_id,
            kind=LedgerKind.SPEND,
            amount=-hold.amount,
            generation_id=generation_id,
        )
    )
    await session.flush()


async def release_hold(session: AsyncSession, generation_id: int) -> None:
    """Generation failed or was blocked: the reserved credits return to the user."""
    hold = await _lock_active_hold(session, generation_id)
    hold.status = HoldStatus.RELEASED
    hold.resolved_at = datetime.now(UTC)
    await session.flush()


async def credit_payment(session: AsyncSession, payment: Payment, pack: Pack) -> bool:
    """Credit a confirmed payment once. Returns False if it was already credited."""
    user = await _lock_user(session, payment.user_id)
    already_credited = await session.scalar(
        select(CreditLedgerEntry.id).where(
            CreditLedgerEntry.payment_id == payment.id,
            CreditLedgerEntry.kind == LedgerKind.PURCHASE,
        )
    )
    if already_credited is not None:
        return False
    if pack.is_one_time:
        if user.trial_used:
            raise TrialAlreadyUsedError(user.id)
        user.trial_used = True
    session.add(
        CreditLedgerEntry(
            user_id=user.id,
            kind=LedgerKind.PURCHASE,
            amount=pack.credits,
            payment_id=payment.id,
        )
    )
    if pack.bonus_credits > 0:
        session.add(
            CreditLedgerEntry(
                user_id=user.id,
                kind=LedgerKind.BONUS,
                amount=pack.bonus_credits,
                payment_id=payment.id,
                note=f"pack:{pack.code}",
            )
        )
    await session.flush()
    return True


async def grant_bonus(session: AsyncSession, user_id: int, amount: int, note: str) -> None:
    await _lock_user(session, user_id)
    session.add(CreditLedgerEntry(user_id=user_id, kind=LedgerKind.BONUS, amount=amount, note=note))
    await session.flush()


async def _lock_user(session: AsyncSession, user_id: int) -> User:
    user = await session.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None:
        raise LookupError(f"user {user_id} not found")
    return user


async def _lock_active_hold(session: AsyncSession, generation_id: int) -> CreditHold:
    hold = await session.scalar(
        select(CreditHold).where(CreditHold.generation_id == generation_id).with_for_update()
    )
    if hold is None or hold.status != HoldStatus.ACTIVE:
        raise HoldNotActiveError(generation_id)
    return hold


async def adjust_credits(session: AsyncSession, user_id: int, amount: int, note: str) -> None:
    """Manual correction from the admin cabinet: positive adds ⚡, negative takes back
    only what the user can spare (never below zero)."""
    if amount == 0:
        raise ValueError("adjustment amount must not be zero")
    await _lock_user(session, user_id)
    if amount < 0:
        balance = await get_balance(session, user_id)
        if balance.available < -amount:
            raise InsufficientCreditsError(available=balance.available, required=-amount)
    session.add(
        CreditLedgerEntry(user_id=user_id, kind=LedgerKind.ADJUSTMENT, amount=amount, note=note)
    )
    await session.flush()


async def refund_generation(session: AsyncSession, generation_id: int, note: str) -> int:
    """Support refund of a delivered video the user complained about. Returns the ⚡ given
    back. Failed and blocked generations never need this: their hold was released."""
    spend = await session.scalar(
        select(CreditLedgerEntry).where(
            CreditLedgerEntry.generation_id == generation_id,
            CreditLedgerEntry.kind == LedgerKind.SPEND,
        )
    )
    if spend is None:
        raise NotRefundableError(generation_id, "not_spent")
    await _lock_user(session, spend.user_id)
    already = await session.scalar(
        select(CreditLedgerEntry.id).where(
            CreditLedgerEntry.generation_id == generation_id,
            CreditLedgerEntry.kind == LedgerKind.REFUND,
        )
    )
    if already is not None:
        raise NotRefundableError(generation_id, "already_refunded")
    session.add(
        CreditLedgerEntry(
            user_id=spend.user_id,
            kind=LedgerKind.REFUND,
            amount=-spend.amount,
            generation_id=generation_id,
            note=note,
        )
    )
    await session.flush()
    return -spend.amount
