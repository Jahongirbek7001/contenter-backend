from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin
from app.models.enums import PaymentProvider, PaymentStatus
from app.models.types import PAYMENT_PROVIDER, PAYMENT_STATUS


class Payment(CreatedAtMixin, Base):
    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("provider", "provider_tx_id", name="uq_payments_provider_tx"),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("credits > 0", name="credits_positive"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    pack_id: Mapped[int] = mapped_column(ForeignKey("packs.id"), nullable=False)
    provider: Mapped[PaymentProvider] = mapped_column(PAYMENT_PROVIDER, nullable=False)
    # Assigned by the provider: Payme/Click send it after the site created the order.
    provider_tx_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # UZS for Payme/Click, Stars count for Telegram Stars.
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    credits: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(
        PAYMENT_STATUS, default=PaymentStatus.PENDING, nullable=False
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Payme: its own transaction `time` (ms) and when we accepted the transaction.
    provider_time: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    provider_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_reason: Mapped[int | None] = mapped_column(Integer, nullable=True)
