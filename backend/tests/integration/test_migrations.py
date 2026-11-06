import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.util.exc import CommandError

from app.db.engine import create_engine
from app.db.migrations import alembic_config, head_revision, schema_is_current

EXPECTED_TABLES = {
    "app_settings",
    "auth_sessions",
    "balance_snapshots",
    "chains",
    "group_settings",
    "groups",
    "risk_events",
    "secrets",
    "signals",
    "trades",
    "users",
}


@pytest.fixture
def db_file(tmp_path: Path) -> Path:
    return tmp_path / "migrate.db"


def url_of(db_file: Path) -> str:
    return f"sqlite+aiosqlite:///{db_file.as_posix()}"


def tables_in(db_file: Path) -> set[str]:
    with sqlite3.connect(db_file) as connection:
        rows = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {name for (name,) in rows} - {"alembic_version"}


def test_upgrade_head_on_an_empty_database_creates_all_tables(db_file: Path) -> None:
    command.upgrade(alembic_config(url_of(db_file)), "head")
    assert tables_in(db_file) == EXPECTED_TABLES


def test_downgrade_base_removes_everything(db_file: Path) -> None:
    config = alembic_config(url_of(db_file))
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    assert tables_in(db_file) == set()


def test_upgrade_downgrade_upgrade_again(db_file: Path) -> None:
    config = alembic_config(url_of(db_file))
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    assert tables_in(db_file) == EXPECTED_TABLES


def test_models_and_migrations_agree(db_file: Path) -> None:
    """Fails if a model was changed without writing a migration (alembic would have changes)."""
    config = alembic_config(url_of(db_file))
    command.upgrade(config, "head")
    try:
        command.check(config)
    except CommandError as error:  # pragma: no cover - only on drift
        pytest.fail(f"models and migrations differ: {error}")


def test_migration_creates_the_report_indexes(db_file: Path) -> None:
    command.upgrade(alembic_config(url_of(db_file)), "head")
    with sqlite3.connect(db_file) as connection:
        rows = connection.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
    names = {name for (name,) in rows}
    assert {
        "ix_trades_account_type_settled_at",
        "ix_trades_group_id_account_type_settled_at",
        "ix_trades_chain_id_step",
        "ix_chains_status",
        "ix_signals_group_id_received_at",
    } <= names


def test_schema_uses_only_portable_column_types(db_file: Path) -> None:
    """No SQLite-only constructs: every column type is a standard SQL type."""
    command.upgrade(alembic_config(url_of(db_file)), "head")
    allowed = {
        "INTEGER",
        "BIGINT",
        "SMALLINT",
        "BOOLEAN",
        "DATETIME",
        "JSON",
        "TEXT",
        "CHAR(32)",
    }
    with sqlite3.connect(db_file) as connection:
        found: set[str] = set()
        for table in EXPECTED_TABLES:
            for _, _, column_type, *_ in connection.execute(f"PRAGMA table_info({table})"):
                found.add(column_type)
    unexpected = {t for t in found if t not in allowed and not t.startswith("VARCHAR(")}
    assert unexpected == set()


async def test_schema_is_current_detects_missing_and_applied_migrations(db_file: Path) -> None:
    engine = create_engine(url_of(db_file))
    try:
        assert await schema_is_current(engine) is False  # new file, nothing applied
        import asyncio

        await asyncio.to_thread(command.upgrade, alembic_config(url_of(db_file)), "head")
        assert await schema_is_current(engine) is True
    finally:
        await engine.dispose()


def test_there_is_a_single_head() -> None:
    assert head_revision() == "0004"


def test_the_opposite_pair_column_arrives_switched_off_for_existing_groups(db_file: Path) -> None:
    config = alembic_config(url_of(db_file))
    command.upgrade(config, "0003")
    with sqlite3.connect(db_file) as connection:
        connection.execute(
            "INSERT INTO groups (id, telegram_chat_id, title, enabled, created_at, updated_at) "
            "VALUES (1, -1001, 'old', 1, '2026-11-01 00:00:00', '2026-11-01 00:00:00')"
        )
        connection.execute(
            "INSERT INTO group_settings (group_id, parser, asset_suffix_mode, timezone, strategy, "
            "base_stake, max_steps, multipliers, min_payout_pct, updated_at) VALUES "
            "(1, 'legacy_v1', 'none', 'UTC', 'flip_every_loss', '1.00', 0, '[]', 0, "
            "'2026-11-01 00:00:00')"
        )
    command.upgrade(config, "head")
    with sqlite3.connect(db_file) as connection:
        (value,) = connection.execute(
            "SELECT allow_opposite_pair FROM group_settings WHERE group_id = 1"
        ).fetchone()
    assert value == 0  # the old behaviour: one chain at a time
    command.downgrade(config, "0003")
    with sqlite3.connect(db_file) as connection:
        columns = [row[1] for row in connection.execute("PRAGMA table_info(group_settings)")]
    assert "allow_opposite_pair" not in columns
