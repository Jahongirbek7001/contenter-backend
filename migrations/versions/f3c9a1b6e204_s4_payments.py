"""s4: Stars prices, Payme/Click order fields, site sessions, referral reward, promo codes

Revision ID: f3c9a1b6e204
Revises: e2b7f4a9d613
Create Date: 2026-11-26 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3c9a1b6e204"
down_revision: str | Sequence[str] | None = "e2b7f4a9d613"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Stars cost the buyer about $0.02 and pay us about $0.013, so ~1.5x the site price
# (docs/plan.md) nets roughly the same as Payme/Click. 1 USD = 12 000 so'm.
STARS_PRICES = {"trial": 50, "start": 210, "popular": 625, "pro": 3500}


def upgrade() -> None:
    op.add_column("packs", sa.Column("price_stars", sa.Integer(), nullable=True))
    op.create_check_constraint(op.f("ck_packs_price_stars_positive"), "packs", "price_stars > 0")
    bind = op.get_bind()
    for code, stars in STARS_PRICES.items():
        bind.execute(
            sa.text("UPDATE packs SET price_stars = :stars WHERE code = :code"),
            {"stars": stars, "code": code},
        )

    # A site order exists before Payme/Click assign their transaction id.
    op.alter_column("payments", "provider_tx_id", existing_type=sa.String(128), nullable=True)
    # Payme's own `time` of the transaction (ms) and when we accepted it.
    op.add_column("payments", sa.Column("provider_time", sa.BigInteger(), nullable=True))
    op.add_column(
        "payments",
        sa.Column("provider_created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("payments", sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("payments", sa.Column("cancel_reason", sa.Integer(), nullable=True))

    op.add_column(
        "users", sa.Column("referral_rewarded_at", sa.DateTime(timezone=True), nullable=True)
    )

    op.create_table(
        "site_sessions",
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_site_sessions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("token_hash", name=op.f("pk_site_sessions")),
    )
    op.create_index(op.f("ix_site_sessions_user_id"), "site_sessions", ["user_id"])

    op.create_table(
        "promo_codes",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("credits", sa.Integer(), nullable=False),
        sa.Column("max_uses", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("credits > 0", name=op.f("ck_promo_codes_credits_positive")),
        sa.CheckConstraint("max_uses > 0", name=op.f("ck_promo_codes_max_uses_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_promo_codes")),
        sa.UniqueConstraint("code", name=op.f("uq_promo_codes_code")),
    )
    op.create_table(
        "promo_redemptions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("promo_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["promo_id"], ["promo_codes.id"], name=op.f("fk_promo_redemptions_promo_id_promo_codes")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_promo_redemptions_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_promo_redemptions")),
        sa.UniqueConstraint("promo_id", "user_id", name=op.f("uq_promo_redemptions_promo_id")),
    )
    op.create_index(op.f("ix_promo_redemptions_user_id"), "promo_redemptions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_promo_redemptions_user_id", table_name="promo_redemptions")
    op.drop_table("promo_redemptions")
    op.drop_table("promo_codes")
    op.drop_index("ix_site_sessions_user_id", table_name="site_sessions")
    op.drop_table("site_sessions")
    op.drop_column("users", "referral_rewarded_at")
    op.drop_column("payments", "cancel_reason")
    op.drop_column("payments", "cancelled_at")
    op.drop_column("payments", "provider_created_at")
    op.drop_column("payments", "provider_time")
    op.execute("DELETE FROM payments WHERE provider_tx_id IS NULL")
    op.alter_column("payments", "provider_tx_id", existing_type=sa.String(128), nullable=False)
    op.drop_constraint("ck_packs_price_stars_positive", "packs", type_="check")
    op.drop_column("packs", "price_stars")
