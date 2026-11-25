from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Identity, String, true
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin
from app.models.enums import AdminRole
from app.models.types import ADMIN_ROLE


class AdminUser(CreatedAtMixin, Base):
    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    # Stored lowercased, so lookups are case-insensitive.
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[AdminRole] = mapped_column(ADMIN_ROLE, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true(), nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AdminSession(CreatedAtMixin, Base):
    """Login session. Only the SHA-256 of the cookie token is stored, never the token itself."""

    __tablename__ = "admin_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    admin_id: Mapped[int] = mapped_column(
        ForeignKey("admin_users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
