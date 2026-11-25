"""s2: generation input photo key, user rules acceptance

Revision ID: c41a7d2e9b35
Revises: b7e2c91d4f10
Create Date: 2026-11-25 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c41a7d2e9b35"
down_revision: str | Sequence[str] | None = "b7e2c91d4f10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("generations", sa.Column("input_media_key", sa.String(length=256), nullable=True))
    op.add_column(
        "users", sa.Column("rules_accepted_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("users", "rules_accepted_at")
    op.drop_column("generations", "input_media_key")
