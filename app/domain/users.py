from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.credits.service import grant_bonus
from app.domain.settings import WELCOME_BONUS, get_setting
from app.models import User
from app.models.enums import Language

WELCOME_NOTE = "welcome"


@dataclass(frozen=True)
class UserLookup:
    user: User
    created: bool
    # ⚡ gift a brand-new customer just received (0 when off or not new).
    welcome_bonus: int = 0


@dataclass(frozen=True)
class Profile:
    """Name fields Telegram shares with the bot, the mini app and the login widget."""

    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None


def language_from_telegram(language_code: str | None) -> Language:
    """Telegram's client language decides the default; the user can change it in the bot."""
    return Language.RU if (language_code or "").lower().startswith("ru") else Language.UZ


def _clip(value: str | None, limit: int) -> str | None:
    value = (value or "").strip()
    return value[:limit] or None


def _apply_profile(user: User, profile: Profile | None) -> None:
    if profile is None:
        return
    user.first_name = _clip(profile.first_name, 64)
    user.last_name = _clip(profile.last_name, 64)
    user.username = _clip(profile.username, 32)


async def get_or_create_user(
    session: AsyncSession,
    telegram_id: int,
    language_code: str | None,
    referrer_telegram_id: int | None = None,
    profile: Profile | None = None,
) -> UserLookup:
    user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
    if user is not None:
        _apply_profile(user, profile)
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
    _apply_profile(user, profile)
    session.add(user)
    await session.flush()
    bonus = await get_setting(session, WELCOME_BONUS)
    if bonus > 0:
        await grant_bonus(session, user.id, bonus, WELCOME_NOTE)
    return UserLookup(user=user, created=True, welcome_bonus=bonus)


def display_name(user: User) -> str:
    """Full name, else @username, else the Telegram id."""
    full = " ".join(part for part in (user.first_name, user.last_name) if part)
    if full:
        return full
    return f"@{user.username}" if user.username else str(user.telegram_id)
