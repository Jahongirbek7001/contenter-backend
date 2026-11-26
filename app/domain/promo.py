"""Promo codes: a one-off ⚡ gift per customer per code."""

import re
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.credits.service import grant_bonus
from app.models import PromoCode, PromoRedemption

CODE_PATTERN = re.compile(r"^[A-Z0-9_-]{3,32}$")


class PromoError(Exception):
    """`reason`: not_found | expired | used_up | already_used."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def normalize_code(code: str) -> str:
    return code.strip().upper()


def valid_code(code: str) -> bool:
    return CODE_PATTERN.fullmatch(normalize_code(code)) is not None


async def redeem_promo(session: AsyncSession, user_id: int, code: str, now: datetime) -> int:
    """Gives the promo's ⚡ to the user; returns how many. The promo row is locked so
    `max_uses` holds under concurrent redemptions."""
    promo = await session.scalar(
        select(PromoCode).where(PromoCode.code == normalize_code(code)).with_for_update()
    )
    if promo is None or not promo.is_active:
        raise PromoError("not_found")
    if promo.expires_at is not None and promo.expires_at <= now:
        raise PromoError("expired")
    already = await session.scalar(
        select(PromoRedemption.id).where(
            PromoRedemption.promo_id == promo.id, PromoRedemption.user_id == user_id
        )
    )
    if already is not None:
        raise PromoError("already_used")
    if promo.max_uses is not None and await redemptions(session, promo.id) >= promo.max_uses:
        raise PromoError("used_up")
    session.add(PromoRedemption(promo_id=promo.id, user_id=user_id))
    await grant_bonus(session, user_id, promo.credits, f"promo:{promo.code}")
    return promo.credits


async def redemptions(session: AsyncSession, promo_id: int) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(PromoRedemption)
        .where(PromoRedemption.promo_id == promo_id)
    )
    return int(count or 0)
