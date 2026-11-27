"""⚡ gifts: campaigns for a group of customers and the bot messages announcing them."""

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from sqlalchemy import Select, exists, func, insert, literal, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.credits.service import get_balance
from app.models import BonusCampaign, CreditLedgerEntry, Generation, Payment, User
from app.models.enums import Language, LedgerKind, PaymentStatus
from app.models.types import LEDGER_KIND

SEGMENTS = ("all", "buyers", "non_buyers", "active_30d")
ACTIVE_WINDOW = timedelta(days=30)
BATCH = 200
# Telegram allows about 30 messages a second; stay well below it.
SEND_INTERVAL_SECONDS = 0.05


class Sender(Protocol):
    async def send(self, chat_id: int, text: str) -> bool:
        """False when the customer cannot be reached (blocked the bot, never started it)."""


@dataclass(frozen=True)
class Recipient:
    user_id: int
    chat_id: int
    language: Language


def _segment_users(segment: str, now: datetime) -> Select[int]:
    if segment not in SEGMENTS:
        raise ValueError(f"unknown segment {segment}")
    query = select(User.id).where(User.is_blocked.is_(False))
    paid = exists().where(Payment.user_id == User.id, Payment.status == PaymentStatus.PAID)
    if segment == "buyers":
        query = query.where(paid)
    elif segment == "non_buyers":
        query = query.where(~paid)
    elif segment == "active_30d":
        since = now - ACTIVE_WINDOW
        query = query.where(
            or_(
                exists().where(Generation.user_id == User.id, Generation.created_at >= since),
                exists().where(Payment.user_id == User.id, Payment.created_at >= since),
            )
        )
    return query


async def segment_size(session: AsyncSession, segment: str, now: datetime) -> int:
    subquery = _segment_users(segment, now).subquery()
    return int(await session.scalar(select(func.count()).select_from(subquery)) or 0)


async def create_campaign(
    session: AsyncSession,
    *,
    credits: int,
    segment: str,
    message_uz: str,
    message_ru: str,
    created_by: str,
    now: datetime,
) -> BonusCampaign:
    """Credits every customer in the segment at once; the bot messages go out later."""
    if credits <= 0:
        raise ValueError("credits must be positive")
    campaign = BonusCampaign(
        credits=credits,
        segment=segment,
        message_uz=message_uz.strip(),
        message_ru=message_ru.strip(),
        created_by=created_by,
    )
    session.add(campaign)
    await session.flush()
    users = _segment_users(segment, now).subquery()
    await session.execute(
        insert(CreditLedgerEntry).from_select(
            ["user_id", "kind", "amount", "note", "campaign_id"],
            select(
                users.c.id,
                literal(LedgerKind.BONUS, LEDGER_KIND),
                literal(credits),
                literal(f"campaign:{campaign.id}"),
                literal(campaign.id),
            ),
        )
    )
    campaign.recipients = int(
        await session.scalar(
            select(func.count()).where(CreditLedgerEntry.campaign_id == campaign.id)
        )
        or 0
    )
    await session.flush()
    return campaign


async def _recipients(
    session: AsyncSession, campaign_id: int, after_user_id: int
) -> Sequence[Recipient]:
    rows = await session.execute(
        select(User.id, User.telegram_id, User.language)
        .join(CreditLedgerEntry, CreditLedgerEntry.user_id == User.id)
        .where(CreditLedgerEntry.campaign_id == campaign_id, User.id > after_user_id)
        .order_by(User.id)
        .limit(BATCH)
    )
    return [Recipient(user_id, chat_id, language) for user_id, chat_id, language in rows]


# (campaign, customer language, customer balance) -> message text
Render = Callable[[BonusCampaign, Language, int], str]


async def broadcast_campaign(
    session_factory: async_sessionmaker[AsyncSession],
    sender: Sender,
    render: Render,
    campaign_id: int,
    now: datetime,
    interval: float = SEND_INTERVAL_SECONDS,
) -> int:
    """Messages every recipient once; returns how many were delivered."""
    delivered, last_user = 0, 0
    while True:
        async with session_factory() as session:
            campaign = await session.get(BonusCampaign, campaign_id)
            if campaign is None or campaign.finished_at is not None:
                return delivered
            batch = await _recipients(session, campaign_id, last_user)
            texts = [
                render(
                    campaign,
                    recipient.language,
                    (await get_balance(session, recipient.user_id)).available,
                )
                for recipient in batch
            ]
        if not batch:
            break
        sent_now = 0
        for recipient, text in zip(batch, texts, strict=True):
            if await sender.send(recipient.chat_id, text):
                sent_now += 1
            await asyncio.sleep(interval)
        delivered += sent_now
        last_user = batch[-1].user_id
        async with session_factory() as session, session.begin():
            await session.execute(
                update(BonusCampaign)
                .where(BonusCampaign.id == campaign_id)
                .values(sent=BonusCampaign.sent + sent_now)
            )
    async with session_factory() as session, session.begin():
        await session.execute(
            update(BonusCampaign).where(BonusCampaign.id == campaign_id).values(finished_at=now)
        )
    return delivered


async def gift_recipient(session: AsyncSession, user_id: int) -> Recipient | None:
    user = await session.get(User, user_id)
    return None if user is None else Recipient(user.id, user.telegram_id, user.language)
