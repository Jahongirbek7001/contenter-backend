"""s3: a generation is refunded at most once

Revision ID: e2b7f4a9d613
Revises: d5a8e3f1c720
Create Date: 2026-11-26 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e2b7f4a9d613"
down_revision: str | Sequence[str] | None = "d5a8e3f1c720"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_credit_ledger_refund_generation",
        "credit_ledger",
        ["generation_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'refund'"),
    )


def downgrade() -> None:
    op.drop_index("uq_credit_ledger_refund_generation", table_name="credit_ledger")
