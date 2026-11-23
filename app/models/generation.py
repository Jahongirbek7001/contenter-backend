from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin
from app.models.enums import GenerationStatus, Product, Resolution
from app.models.types import GENERATION_STATUS, PRODUCT, RESOLUTION


class Generation(CreatedAtMixin, Base):
    __tablename__ = "generations"
    __table_args__ = (CheckConstraint("credits_cost > 0", name="credits_cost_positive"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    product: Mapped[Product] = mapped_column(PRODUCT, nullable=False)
    resolution: Mapped[Resolution] = mapped_column(RESOLUTION, nullable=False)
    status: Mapped[GenerationStatus] = mapped_column(
        GENERATION_STATUS, default=GenerationStatus.PENDING, nullable=False
    )
    credits_cost: Mapped[int] = mapped_column(Integer, nullable=False)
    template_id: Mapped[int | None] = mapped_column(ForeignKey("trend_templates.id"), nullable=True)
    source_generation_id: Mapped[int | None] = mapped_column(
        ForeignKey("generations.id"), nullable=True
    )
    user_input: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    script: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provider_job_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    telegram_file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
