from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    String,
    UniqueConstraint,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin


class PromoCode(CreatedAtMixin, Base):
    __tablename__ = "promo_codes"
    __table_args__ = (
        CheckConstraint("credits > 0", name="credits_positive"),
        CheckConstraint("max_uses > 0", name="max_uses_positive"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    # Stored uppercased, so codes are case-insensitive.
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    credits: Mapped[int] = mapped_column(Integer, nullable=False)
    # None: unlimited customers (each still redeems once).
    max_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true(), nullable=False)


class PromoRedemption(CreatedAtMixin, Base):
    __tablename__ = "promo_redemptions"
    __table_args__ = (UniqueConstraint("promo_id", "user_id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    promo_id: Mapped[int] = mapped_column(ForeignKey("promo_codes.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
