from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Identity, false
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin
from app.models.enums import Language
from app.models.types import LANGUAGE


class User(CreatedAtMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    language: Mapped[Language] = mapped_column(LANGUAGE, default=Language.UZ, nullable=False)
    referrer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    trial_used: Mapped[bool] = mapped_column(Boolean, server_default=false(), nullable=False)
    is_blocked: Mapped[bool] = mapped_column(Boolean, server_default=false(), nullable=False)
    # Set when the user accepts the usage rules shown before the first generation.
    rules_accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Set when the invited user's first purchase paid out the referral bonus to both sides.
    referral_rewarded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
