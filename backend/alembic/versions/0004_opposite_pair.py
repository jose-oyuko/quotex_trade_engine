"""opposite pair

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-06 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema. Every existing group keeps today's behaviour (the pair is off)."""
    op.add_column(
        "group_settings",
        sa.Column("allow_opposite_pair", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("group_settings") as batch:
        batch.drop_column("allow_opposite_pair")
