"""trading sessions

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-12 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema. Every existing group stays a Telegram group; no chain belongs to a run."""
    op.create_table(
        "trading_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("asset", sa.String(length=32), nullable=False),
        sa.Column("duration_s", sa.Integer(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column(
            "repeat",
            sa.Enum("once", "weekdays", name="repeatkind", native_enum=False, length=24),
            nullable=False,
        ),
        sa.Column("weekdays", sa.JSON(), nullable=False),
        sa.Column("pause_s", sa.Integer(), nullable=False),
        sa.Column("profit_target", sa.BigInteger(), nullable=True),
        sa.Column("loss_limit", sa.BigInteger(), nullable=True),
        sa.Column("max_pairs", sa.Integer(), nullable=True),
        sa.Column("once_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("duration_s > 0", name=op.f("ck_trading_sessions_duration_positive")),
        sa.CheckConstraint("pause_s >= 0", name=op.f("ck_trading_sessions_pause_not_negative")),
        sa.ForeignKeyConstraint(
            ["group_id"], ["groups.id"], name=op.f("fk_trading_sessions_group_id_groups")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trading_sessions")),
        sa.UniqueConstraint("group_id", name=op.f("uq_trading_sessions_group_id")),
    )
    op.create_table(
        "session_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("started_by", sa.String(length=16), nullable=False),
        sa.Column(
            "account_type",
            sa.Enum("demo", "real", name="accounttype", native_enum=False, length=24),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "state",
            sa.Enum("running", "stopping", "ended", name="runstate", native_enum=False, length=24),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pairs_opened", sa.Integer(), nullable=False),
        sa.Column("rounds_skipped", sa.Integer(), nullable=False),
        sa.Column("lopsided_pairs", sa.Integer(), nullable=False),
        sa.Column("profit", sa.BigInteger(), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "end_reason",
            sa.Enum(
                "window_ended",
                "profit_target",
                "loss_limit",
                "max_pairs",
                "stopped",
                "kill_switch",
                "engine_stopped",
                "interrupted",
                "error",
                name="runendreason",
                native_enum=False,
                length=24,
            ),
            nullable=True,
        ),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["trading_sessions.id"],
            name=op.f("fk_session_runs_session_id_trading_sessions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_session_runs")),
    )
    op.create_index(
        "ix_session_runs_session_id_started_at", "session_runs", ["session_id", "started_at"]
    )
    op.create_index("ix_session_runs_state", "session_runs", ["state"])

    with op.batch_alter_table("groups") as batch:
        batch.alter_column("telegram_chat_id", existing_type=sa.BigInteger(), nullable=True)
        batch.add_column(
            sa.Column(
                "source",
                sa.Enum("telegram", "session", name="groupsource", native_enum=False, length=24),
                server_default="telegram",
                nullable=False,
            )
        )
    with op.batch_alter_table("chains") as batch:
        batch.add_column(sa.Column("session_run_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("pair_no", sa.SmallInteger(), nullable=True))
        batch.create_foreign_key(
            op.f("fk_chains_session_run_id_session_runs"),
            "session_runs",
            ["session_run_id"],
            ["id"],
        )


def downgrade() -> None:
    """Downgrade schema. The hidden groups of sessions go with the sessions."""
    with op.batch_alter_table("chains") as batch:
        batch.drop_constraint(op.f("fk_chains_session_run_id_session_runs"), type_="foreignkey")
        batch.drop_column("pair_no")
        batch.drop_column("session_run_id")
    op.drop_index("ix_session_runs_state", table_name="session_runs")
    op.drop_index("ix_session_runs_session_id_started_at", table_name="session_runs")
    op.drop_table("session_runs")
    op.drop_table("trading_sessions")
    op.execute(
        "DELETE FROM group_settings "
        "WHERE group_id IN (SELECT id FROM groups WHERE source = 'session')"
    )
    op.execute("DELETE FROM groups WHERE source = 'session'")
    with op.batch_alter_table("groups") as batch:
        batch.drop_column("source")
        batch.alter_column("telegram_chat_id", existing_type=sa.BigInteger(), nullable=False)
