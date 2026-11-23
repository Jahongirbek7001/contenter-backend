from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin
from app.models.enums import HoldStatus, LedgerKind
from app.models.types import HOLD_STATUS, LEDGER_KIND


class CreditLedgerEntry(CreatedAtMixin, Base):
    """Append-only. Settled balance = SUM(amount) per user."""

    __tablename__ = "credit_ledger"
    __table_args__ = (
        CheckConstraint("amount <> 0", name="amount_non_zero"),
        # A payment is credited once and a generation is charged once, even under retries.
        Index(
            "uq_credit_ledger_purchase_payment",
            "payment_id",
            unique=True,
            postgresql_where=text("kind = 'purchase'"),
        ),
        Index(
            "uq_credit_ledger_spend_generation",
            "generation_id",
            unique=True,
            postgresql_where=text("kind = 'spend'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    kind: Mapped[LedgerKind] = mapped_column(LEDGER_KIND, nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    payment_id: Mapped[int | None] = mapped_column(ForeignKey("payments.id"), nullable=True)
    generation_id: Mapped[int | None] = mapped_column(ForeignKey("generations.id"), nullable=True)
    note: Mapped[str | None] = mapped_column(String(256), nullable=True)


class CreditHold(CreatedAtMixin, Base):
    """Credits reserved while a generation runs. Available = ledger sum - active holds."""

    __tablename__ = "credit_holds"
    __table_args__ = (CheckConstraint("amount > 0", name="amount_positive"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    generation_id: Mapped[int] = mapped_column(
        ForeignKey("generations.id"), unique=True, nullable=False
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[HoldStatus] = mapped_column(
        HOLD_STATUS, default=HoldStatus.ACTIVE, nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
