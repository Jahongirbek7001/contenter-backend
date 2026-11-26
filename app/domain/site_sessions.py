"""Customer cookie sessions on the site (after Telegram Login)."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SiteSession, User

SESSION_TTL = timedelta(days=30)


async def start_session(session: AsyncSession, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    session.add(
        SiteSession(
            token_hash=_hash(token), user_id=user_id, expires_at=datetime.now(UTC) + SESSION_TTL
        )
    )
    await session.flush()
    return token


async def resolve_session(session: AsyncSession, token: str) -> User | None:
    return await session.scalar(
        select(User)
        .join(SiteSession, SiteSession.user_id == User.id)
        .where(SiteSession.token_hash == _hash(token), SiteSession.expires_at > datetime.now(UTC))
    )


async def end_session(session: AsyncSession, token: str) -> None:
    await session.execute(delete(SiteSession).where(SiteSession.token_hash == _hash(token)))


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
