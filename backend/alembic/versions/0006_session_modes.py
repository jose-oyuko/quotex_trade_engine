"""session modes

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-12 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema. Every existing session stays sequential: one pair at a time."""
    with op.batch_alter_table("trading_sessions") as batch:
        batch.add_column(
            sa.Column(
                "mode",
                sa.Enum(
                    "sequential", "every_candle", name="sessionmode", native_enum=False, length=24
                ),
                server_default="sequential",
                nullable=False,
            )
        )
        batch.add_column(
            sa.Column("max_open_pairs", sa.Integer(), server_default="1", nullable=False)
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("trading_sessions") as batch:
        batch.drop_column("max_open_pairs")
        batch.drop_column("mode")
