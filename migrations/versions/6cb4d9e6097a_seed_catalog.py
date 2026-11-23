"""seed catalog: prices, packs, model routes (docs/plan.md)

Revision ID: 6cb4d9e6097a
Revises: 45ffc8e8c95d
Create Date: 2026-11-23 16:47:44.007403

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "6cb4d9e6097a"
down_revision: str | Sequence[str] | None = "45ffc8e8c95d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Upscale rows are cumulative from 360p per 10 s segment:
# cost = (price[target] - price[source]) * segments, with price[360p] = 0.
PRODUCT_PRICES = [
    ("trend", "1080p", 2),
    ("talking", "360p", 1),
    ("talking", "720p", 3),
    ("talking", "1080p", 5),
    ("series", "360p", 3),
    ("series", "720p", 9),
    ("series", "1080p", 15),
    ("upscale", "720p", 2),
    ("upscale", "1080p", 4),
]

PACKS = [
    # code, title_uz, title_ru, price_uzs, credits, bonus, one_time, sort
    ("trial", "Sinov", "Пробный", 7_777, 2, 0, True, 10),
    ("start", "Start", "Старт", 33_333, 5, 0, False, 20),
    ("popular", "Ommabop", "Популярный", 99_999, 15, 1, False, 30),
    ("pro", "Pro / Biznes", "Про / Бизнес", 555_555, 100, 0, False, 40),
]

# Model ids are verified by scripts/model_probe and editable from the admin cabinet.
MODEL_ROUTES = [
    ("trend", "vertex", "veo-3.1-lite-generate-001"),
    ("talking", "gemini", "gemini-omni-1.2-flash"),
    ("series", "gemini", "gemini-omni-1.2-flash"),
    ("upscale", "gemini", "gemini-omni-1.2-flash"),
]


def upgrade() -> None:
    bind = op.get_bind()
    for product, resolution, credits in PRODUCT_PRICES:
        bind.execute(
            sa.text(
                "INSERT INTO product_prices (product, resolution, credits) "
                "VALUES (CAST(:product AS product), CAST(:resolution AS resolution), :credits)"
            ),
            {"product": product, "resolution": resolution, "credits": credits},
        )
    for code, title_uz, title_ru, price, credits, bonus, one_time, sort in PACKS:
        bind.execute(
            sa.text(
                "INSERT INTO packs (code, title_uz, title_ru, price_uzs, credits, bonus_credits, "
                "is_one_time, sort_order) VALUES (:code, :title_uz, :title_ru, :price, :credits, "
                ":bonus, :one_time, :sort)"
            ),
            {
                "code": code,
                "title_uz": title_uz,
                "title_ru": title_ru,
                "price": price,
                "credits": credits,
                "bonus": bonus,
                "one_time": one_time,
                "sort": sort,
            },
        )
    for product, provider, model in MODEL_ROUTES:
        bind.execute(
            sa.text(
                "INSERT INTO model_routes (product, provider, model) "
                "VALUES (CAST(:product AS product), :provider, :model)"
            ),
            {"product": product, "provider": provider, "model": model},
        )


def downgrade() -> None:
    op.execute("DELETE FROM model_routes")
    op.execute("DELETE FROM packs")
    op.execute("DELETE FROM product_prices")
