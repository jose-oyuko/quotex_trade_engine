"""brokers

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-17 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Every table that says which broker a row belongs to (decision D-75)
TABLES = ("groups", "trading_sessions", "chains", "trades", "balance_snapshots")
# (table, index name, columns): looked up by broker and account type
INDEXES = (
    (
        "chains",
        "ix_chains_broker_account_type_created_at",
        ["broker", "account_type", "created_at"],
    ),
    (
        "trades",
        "ix_trades_broker_account_type_settled_at",
        ["broker", "account_type", "settled_at"],
    ),
    (
        "balance_snapshots",
        "ix_balance_snapshots_broker_account_type_taken_at",
        ["broker", "account_type", "taken_at"],
    ),
)


def upgrade() -> None:
    """Upgrade schema. Everything that exists was on Quotex, the only broker until now."""
    for table in TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(
                sa.Column(
                    "broker",
                    sa.Enum("quotex", "deriv", name="broker", native_enum=False, length=24),
                    server_default="quotex",
                    nullable=False,
                )
            )
    for table, name, columns in INDEXES:
        with op.batch_alter_table(table) as batch:
            batch.create_index(name, columns, unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    for table, name, _ in INDEXES:
        with op.batch_alter_table(table) as batch:
            batch.drop_index(name)
    for table in reversed(TABLES):
        with op.batch_alter_table(table) as batch:
            batch.drop_column("broker")
