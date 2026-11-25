from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.models.enums import Language


@dataclass(frozen=True)
class UserLookup:
    user: User
    created: bool


def language_from_telegram(language_code: str | None) -> Language:
    """Telegram's client language decides the default; the user can change it in the bot."""
    return Language.RU if (language_code or "").lower().startswith("ru") else Language.UZ


async def get_or_create_user(
    session: AsyncSession,
    telegram_id: int,
    language_code: str | None,
    referrer_telegram_id: int | None = None,
) -> UserLookup:
    user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
    if user is not None:
        return UserLookup(user=user, created=False)
    referrer_id = None
    if referrer_telegram_id is not None and referrer_telegram_id != telegram_id:
        referrer_id = await session.scalar(
            select(User.id).where(User.telegram_id == referrer_telegram_id)
        )
    user = User(
        telegram_id=telegram_id,
        language=language_from_telegram(language_code),
        referrer_id=referrer_id,
    )
    session.add(user)
    await session.flush()
    return UserLookup(user=user, created=True)
