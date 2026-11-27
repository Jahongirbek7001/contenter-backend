"""s5: customer names, app settings, bonus campaigns

Revision ID: a4d8c2e7f915
Revises: f3c9a1b6e204
Create Date: 2026-11-27 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a4d8c2e7f915"
down_revision: str | Sequence[str] | None = "f3c9a1b6e204"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Telegram profile, refreshed whenever the customer talks to the bot or logs in.
    op.add_column("users", sa.Column("first_name", sa.String(64), nullable=True))
    op.add_column("users", sa.Column("last_name", sa.String(64), nullable=True))
    op.add_column("users", sa.Column("username", sa.String(32), nullable=True))

    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_app_settings")),
    )

    op.create_table(
        "bonus_campaigns",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("credits", sa.Integer(), nullable=False),
        sa.Column("segment", sa.String(16), nullable=False),
        sa.Column("message_uz", sa.String(1000), nullable=False),
        sa.Column("message_ru", sa.String(1000), nullable=False),
        sa.Column("created_by", sa.String(254), nullable=False),
        sa.Column("recipients", sa.Integer(), server_default="0", nullable=False),
        sa.Column("sent", sa.Integer(), server_default="0", nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("credits > 0", name=op.f("ck_bonus_campaigns_credits_positive")),
        sa.CheckConstraint(
            "segment IN ('all', 'buyers', 'non_buyers', 'active_30d')",
            name=op.f("ck_bonus_campaigns_segment_known"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bonus_campaigns")),
    )

    op.add_column("credit_ledger", sa.Column("campaign_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("fk_credit_ledger_campaign_id_bonus_campaigns"),
        "credit_ledger",
        "bonus_campaigns",
        ["campaign_id"],
        ["id"],
    )
    # A campaign gives each customer its ⚡ once.
    op.create_index(
        "uq_credit_ledger_campaign_user",
        "credit_ledger",
        ["campaign_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("campaign_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_credit_ledger_campaign_user", table_name="credit_ledger")
    op.drop_constraint(
        op.f("fk_credit_ledger_campaign_id_bonus_campaigns"), "credit_ledger", type_="foreignkey"
    )
    op.drop_column("credit_ledger", "campaign_id")
    op.drop_table("bonus_campaigns")
    op.drop_table("app_settings")
    op.drop_column("users", "username")
    op.drop_column("users", "last_name")
    op.drop_column("users", "first_name")
