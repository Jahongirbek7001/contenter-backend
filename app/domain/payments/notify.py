"""What to tell the customer (and the inviter) after a payment credited ⚡."""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.credits.service import get_balance
from app.domain.payments.orders import REFERRAL_BONUS
from app.models import Payment, User
from app.models.enums import Language


@dataclass(frozen=True)
class Notice:
    chat_id: int
    language: Language
    credits: int
    available: int
    # ⚡ from the referral programme that came with this payment (0 if none).
    referral_bonus: int = 0


@dataclass(frozen=True)
class PaymentNotices:
    payer: Notice
    referrer: Notice | None


async def payment_notices(
    session: AsyncSession, payment_id: int, referrer_id: int | None
) -> PaymentNotices | None:
    payment = await session.get(Payment, payment_id)
    if payment is None:
        return None
    payer = await session.get(User, payment.user_id)
    if payer is None:
        return None
    bonus = REFERRAL_BONUS if referrer_id is not None else 0
    payer_notice = Notice(
        chat_id=payer.telegram_id,
        language=payer.language,
        credits=payment.credits,
        available=(await get_balance(session, payer.id)).available,
        referral_bonus=bonus,
    )
    referrer = await session.get(User, referrer_id) if referrer_id is not None else None
    referrer_notice = (
        Notice(
            chat_id=referrer.telegram_id,
            language=referrer.language,
            credits=0,
            available=(await get_balance(session, referrer.id)).available,
            referral_bonus=REFERRAL_BONUS,
        )
        if referrer is not None
        else None
    )
    return PaymentNotices(payer=payer_notice, referrer=referrer_notice)
