from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Identity, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin


class AppSetting(Base):
    """Numbers the owner changes from the admin cabinet without a deploy."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class BonusCampaign(CreatedAtMixin, Base):
    """A ⚡ gift to a group of customers, announced in the bot."""

    __tablename__ = "bonus_campaigns"
    __table_args__ = (
        CheckConstraint("credits > 0", name="credits_positive"),
        CheckConstraint(
            "segment IN ('all', 'buyers', 'non_buyers', 'active_30d')", name="segment_known"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    credits: Mapped[int] = mapped_column(Integer, nullable=False)
    segment: Mapped[str] = mapped_column(String(16), nullable=False)
    message_uz: Mapped[str] = mapped_column(String(1000), nullable=False)
    message_ru: Mapped[str] = mapped_column(String(1000), nullable=False)
    created_by: Mapped[str] = mapped_column(String(254), nullable=False)
    recipients: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    sent: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
