"""Admin accounts and cookie sessions for the admin cabinet."""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.passwords import hash_password, verify_password
from app.models import AdminSession, AdminUser
from app.models.enums import AdminRole

SESSION_TTL = timedelta(days=7)
MIN_PASSWORD_LENGTH = 12
# Verified against when the email is unknown, so response time does not reveal which emails exist.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


@dataclass(frozen=True)
class IssuedSession:
    token: str
    expires_at: datetime


def normalize_email(email: str) -> str:
    return email.strip().lower()


async def create_admin(
    session: AsyncSession, email: str, password: str, role: AdminRole
) -> AdminUser:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    admin = AdminUser(
        email=normalize_email(email), password_hash=hash_password(password), role=role
    )
    session.add(admin)
    await session.flush()
    return admin


async def authenticate(session: AsyncSession, email: str, password: str) -> AdminUser | None:
    admin = await session.scalar(select(AdminUser).where(AdminUser.email == normalize_email(email)))
    if admin is None:
        verify_password(password, _DUMMY_HASH)
        return None
    if not admin.is_active or not verify_password(password, admin.password_hash):
        return None
    return admin


async def start_session(session: AsyncSession, admin: AdminUser) -> IssuedSession:
    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    expires_at = now + SESSION_TTL
    session.add(
        AdminSession(token_hash=_hash_token(token), admin_id=admin.id, expires_at=expires_at)
    )
    admin.last_login_at = now
    await session.flush()
    return IssuedSession(token=token, expires_at=expires_at)


async def resolve_session(session: AsyncSession, token: str) -> AdminUser | None:
    admin = await session.scalar(
        select(AdminUser)
        .join(AdminSession, AdminSession.admin_id == AdminUser.id)
        .where(
            AdminSession.token_hash == _hash_token(token),
            AdminSession.expires_at > datetime.now(UTC),
            AdminUser.is_active,
        )
    )
    return admin


async def end_session(session: AsyncSession, token: str) -> None:
    await session.execute(delete(AdminSession).where(AdminSession.token_hash == _hash_token(token)))


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
