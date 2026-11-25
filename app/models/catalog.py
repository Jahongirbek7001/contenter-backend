from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Identity,
    Integer,
    String,
    Text,
    UniqueConstraint,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin
from app.models.enums import Product, Resolution, TrendAudience, TrendBadge
from app.models.types import PRODUCT, RESOLUTION, TREND_AUDIENCE, TREND_BADGE


class ProductPrice(Base):
    __tablename__ = "product_prices"
    __table_args__ = (
        UniqueConstraint("product", "resolution"),
        CheckConstraint("credits > 0", name="credits_positive"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    product: Mapped[Product] = mapped_column(PRODUCT, nullable=False)
    resolution: Mapped[Resolution] = mapped_column(RESOLUTION, nullable=False)
    credits: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true(), nullable=False)


class Pack(Base):
    __tablename__ = "packs"
    __table_args__ = (
        CheckConstraint("price_uzs > 0", name="price_positive"),
        CheckConstraint("credits > 0", name="credits_positive"),
        CheckConstraint("bonus_credits >= 0", name="bonus_non_negative"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    title_uz: Mapped[str] = mapped_column(String(64), nullable=False)
    title_ru: Mapped[str] = mapped_column(String(64), nullable=False)
    price_uzs: Mapped[int] = mapped_column(Integer, nullable=False)
    credits: Mapped[int] = mapped_column(Integer, nullable=False)
    bonus_credits: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_one_time: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true(), nullable=False)


class TrendTemplate(CreatedAtMixin, Base):
    __tablename__ = "trend_templates"

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    title_uz: Mapped[str] = mapped_column(String(128), nullable=False)
    title_ru: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    audience: Mapped[TrendAudience] = mapped_column(
        TREND_AUDIENCE, server_default=TrendAudience.ALL.value, nullable=False
    )
    badge: Mapped[TrendBadge] = mapped_column(
        TREND_BADGE, server_default=TrendBadge.NONE.value, nullable=False
    )
    preview_storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Telegram file_id of the preview video once it has been sent through the bot.
    preview_file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    prompt_skeleton: Mapped[str] = mapped_column(Text, nullable=False)
    first_frame_instructions: Mapped[str] = mapped_column(Text, nullable=False)
    music_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true(), nullable=False)


class MusicTrack(CreatedAtMixin, Base):
    __tablename__ = "music_tracks"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    template_id: Mapped[int] = mapped_column(
        ForeignKey("trend_templates.id", ondelete="CASCADE"), index=True, nullable=False
    )
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    mood: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true(), nullable=False)


class ModelRoute(Base):
    """Which provider/model serves a product; edited from the admin cabinet."""

    __tablename__ = "model_routes"

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    product: Mapped[Product] = mapped_column(PRODUCT, unique=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, server_default=true(), nullable=False)
