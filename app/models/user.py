from sqlalchemy import BigInteger, Boolean, ForeignKey, Identity, false
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
