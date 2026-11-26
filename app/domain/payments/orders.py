"""Orders and confirmed payments, shared by Telegram Stars, Payme and Click.

Functions run inside the caller's transaction and never commit.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.credits.service import credit_payment, grant_bonus
from app.models import Pack, Payment, User
from app.models.enums import PaymentProvider, PaymentStatus

UZS = "UZS"
STARS = "XTR"
# Both sides get it when the invited user pays for the first time (docs/s4-plan.md).
REFERRAL_BONUS = 2
SITE_PROVIDERS = frozenset({PaymentProvider.PAYME, PaymentProvider.CLICK})


class OrderError(Exception):
    """`reason`: pack_unavailable | trial_used | blocked."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Completed:
    payment_id: int
    credited: bool
    # Set when this payment also paid the referral bonus; the inviter gets a message.
    referrer_id: int | None = None


async def sellable_pack(
    session: AsyncSession, user: User, pack: Pack | None, *, exclude_payment_id: int | None = None
) -> Pack:
    """The pack can be sold to this user right now, or OrderError says why not."""
    if user.is_blocked:
        raise OrderError("blocked")
    if pack is None or not pack.is_active:
        raise OrderError("pack_unavailable")
    if pack.is_one_time and (
        user.trial_used or await _trial_in_progress(session, user.id, exclude_payment_id)
    ):
        raise OrderError("trial_used")
    return pack


async def _trial_in_progress(
    session: AsyncSession, user_id: int, exclude_payment_id: int | None
) -> bool:
    """Another one-time order is paid or already accepted by a provider."""
    query = (
        select(Payment.id)
        .join(Pack, Pack.id == Payment.pack_id)
        .where(
            Payment.user_id == user_id,
            Pack.is_one_time,
            (Payment.status == PaymentStatus.PAID)
            | ((Payment.status == PaymentStatus.PENDING) & Payment.provider_tx_id.is_not(None)),
        )
    )
    if exclude_payment_id is not None:
        query = query.where(Payment.id != exclude_payment_id)
    return bool(await session.scalar(select(exists(query))))


async def create_site_order(
    session: AsyncSession, user: User, pack_code: str, provider: PaymentProvider
) -> Payment:
    if provider not in SITE_PROVIDERS:
        raise ValueError(f"{provider} is not a site provider")
    pack = await session.scalar(select(Pack).where(Pack.code == pack_code))
    pack = await sellable_pack(session, user, pack)
    payment = Payment(
        user_id=user.id,
        pack_id=pack.id,
        provider=provider,
        amount=pack.price_uzs,
        currency=UZS,
        credits=pack.credits + pack.bonus_credits,
    )
    session.add(payment)
    await session.flush()
    return payment


async def check_payable(session: AsyncSession, payment: Payment) -> None:
    """Re-checked when a provider is about to take the money (OrderError if not)."""
    user = await session.get(User, payment.user_id)
    if user is None:
        raise OrderError("pack_unavailable")
    pack = await session.get(Pack, payment.pack_id)
    # The price the customer saw is fixed in the order, so only availability matters here.
    await sellable_pack(session, user, pack, exclude_payment_id=payment.id)


async def complete_payment(session: AsyncSession, payment: Payment, now: datetime) -> Completed:
    """The provider has the money: mark paid and credit ⚡ (once)."""
    pack = await session.get(Pack, payment.pack_id)
    if pack is None:
        raise LookupError(f"pack {payment.pack_id} not found")
    payment.status = PaymentStatus.PAID
    payment.paid_at = now
    credited = await credit_payment(session, payment, pack, enforce_one_time=False)
    if not credited:
        return Completed(payment.id, credited=False)
    return Completed(
        payment.id, credited=True, referrer_id=await _reward_referral(session, payment.user_id, now)
    )


def cancel_payment(payment: Payment, reason: int | None, now: datetime) -> None:
    payment.status = PaymentStatus.CANCELLED
    payment.cancelled_at = now
    payment.cancel_reason = reason


async def _reward_referral(session: AsyncSession, user_id: int, now: datetime) -> int | None:
    user = await session.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None or user.referrer_id is None or user.referral_rewarded_at is not None:
        return None
    user.referral_rewarded_at = now
    note = f"referral:{user.id}"
    await grant_bonus(session, user.id, REFERRAL_BONUS, note)
    await grant_bonus(session, user.referrer_id, REFERRAL_BONUS, note)
    return user.referrer_id


async def record_stars_payment(
    session: AsyncSession,
    user: User,
    pack_id: int,
    charge_id: str,
    stars: int,
    now: datetime,
) -> Completed:
    """Telegram already took the Stars; the charge id makes a redelivered update a no-op."""
    already = await session.scalar(
        select(Payment.id).where(
            Payment.provider == PaymentProvider.STARS, Payment.provider_tx_id == charge_id
        )
    )
    if already is not None:
        return Completed(already, credited=False)
    pack = await session.get(Pack, pack_id)
    if pack is None:
        raise LookupError(f"pack {pack_id} not found")
    payment = Payment(
        user_id=user.id,
        pack_id=pack.id,
        provider=PaymentProvider.STARS,
        provider_tx_id=charge_id,
        amount=stars,
        currency=STARS,
        credits=pack.credits + pack.bonus_credits,
        provider_created_at=now,
    )
    session.add(payment)
    await session.flush()
    return await complete_payment(session, payment, now)
