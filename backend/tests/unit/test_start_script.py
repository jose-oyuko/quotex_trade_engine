"""`npm start`: the preparation steps, their order, and the advice given when one cannot be done."""

from __future__ import annotations

import os
import socket
import time
from collections.abc import Sequence
from pathlib import Path

import pytest

from app.core.config import Settings
from app.vault.crypto import generate_key
from scripts.start import (
    StartError,
    dashboard_needs_build,
    newest_source_time,
    port_in_use,
    prepare,
    summarise,
)

NPM = "/fake/npm"


def settings_for(tmp_path: Path, **overrides: object) -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None, data_dir=tmp_path / "data", port=18999, **overrides
    )


class Recorder:
    """Stands in for running commands, the database migration and the port check."""

    def __init__(self, *, exit_codes: dict[str, int] | None = None, busy: bool = False) -> None:
        self.commands: list[list[str]] = []
        self.said: list[str] = []
        self.migrated = 0
        self._codes = exit_codes or {}
        self.busy = busy

    def run(self, command: Sequence[str], cwd: Path) -> int:
        del cwd
        self.commands.append(list(command))
        return self._codes.get(" ".join(command[1:]), 0)

    def migrate(self, settings: Settings) -> None:
        del settings
        self.migrated += 1

    def port_busy(self, host: str, port: int) -> bool:
        del host, port
        return self.busy


def frontend(tmp_path: Path, *, modules: bool = True, built: bool = True) -> Path:
    root = tmp_path / "frontend"
    (root / "src").mkdir(parents=True)
    (root / "src" / "main.tsx").write_text("// source", encoding="utf-8")
    (root / "package.json").write_text("{}", encoding="utf-8")
    if modules:
        (root / "node_modules").mkdir()
    if built:
        (root / "dist").mkdir()
        index = root / "dist" / "index.html"
        index.write_text("<html/>", encoding="utf-8")
        later = time.time() + 5  # built after the source was last touched
        os.utime(index, (later, later))
    return root


def run_prepare(  # type: ignore[no-untyped-def]
    tmp_path: Path, rec: Recorder, root: Path, *, with_key: bool = True, **kwargs: object
):
    env = tmp_path / ".env"
    if with_key and not env.exists():
        env.write_text(f"SECRET_KEY={generate_key()}\n", encoding="utf-8")
    return prepare(
        settings_for(tmp_path),
        run=rec.run,
        which=lambda name: NPM if name == "npm" else None,
        frontend=root,
        say=rec.said.append,
        migrate=rec.migrate,
        port_busy=rec.port_busy,
        **{"env_file": tmp_path / ".env", **kwargs},  # type: ignore[arg-type]
    )


def test_when_everything_is_ready_it_only_prepares_the_database(tmp_path: Path) -> None:
    rec = Recorder()
    summary = run_prepare(tmp_path, rec, frontend(tmp_path))
    assert rec.commands == []  # no install, no build
    assert rec.migrated == 1 and rec.said == ["Preparing the database..."]
    assert summary.url == "http://127.0.0.1:18999"


def test_a_new_installation_installs_then_builds_then_migrates_in_that_order(
    tmp_path: Path,
) -> None:
    rec = Recorder()
    run_prepare(tmp_path, rec, frontend(tmp_path, modules=False, built=False))
    assert rec.commands == [[NPM, "install"], [NPM, "run", "build"]]
    assert rec.migrated == 1
    assert [s.split(" ")[0] for s in rec.said] == ["Installing", "Building", "Preparing"]


def test_the_dashboard_is_rebuilt_when_its_source_is_newer(tmp_path: Path) -> None:
    root = frontend(tmp_path)
    assert dashboard_needs_build(root) is False
    newer = time.time() + 60
    os.utime(root / "src" / "main.tsx", (newer, newer))  # someone edited the source
    assert dashboard_needs_build(root) is True
    rec = Recorder()
    run_prepare(tmp_path, rec, root)
    assert rec.commands == [[NPM, "run", "build"]]


def test_a_missing_build_is_a_build(tmp_path: Path) -> None:
    assert dashboard_needs_build(frontend(tmp_path, built=False)) is True


def test_only_source_files_decide_whether_to_rebuild(tmp_path: Path) -> None:
    root = frontend(tmp_path)
    notes = root / "src" / "notes.txt"
    notes.write_text("not part of the build", encoding="utf-8")
    later = time.time() + 600
    os.utime(notes, (later, later))
    assert dashboard_needs_build(root) is False
    assert newest_source_time(root / "src", []) < later


def test_without_node_it_says_what_to_install(tmp_path: Path) -> None:
    rec = Recorder()
    with pytest.raises(StartError, match=r"Node\.js is not installed"):
        prepare(
            settings_for(tmp_path),
            run=rec.run,
            which=lambda name: None,
            env_file=tmp_path / ".env",
            frontend=frontend(tmp_path),
            say=rec.said.append,
            migrate=rec.migrate,
            port_busy=rec.port_busy,
        )
    assert rec.migrated == 0 and rec.commands == []


def test_a_failed_install_stops_with_advice_and_does_nothing_further(tmp_path: Path) -> None:
    rec = Recorder(exit_codes={"install": 1})
    with pytest.raises(StartError, match=r"npm install.*internet"):
        run_prepare(tmp_path, rec, frontend(tmp_path, modules=False, built=False))
    assert rec.commands == [[NPM, "install"]] and rec.migrated == 0


def test_a_failed_build_stops_before_the_database(tmp_path: Path) -> None:
    rec = Recorder(exit_codes={"run build": 2})
    with pytest.raises(StartError, match="Building the dashboard failed"):
        run_prepare(tmp_path, rec, frontend(tmp_path, built=False))
    assert rec.migrated == 0


def test_a_busy_port_is_explained(tmp_path: Path) -> None:
    rec = Recorder(busy=True)
    with pytest.raises(StartError) as caught:
        run_prepare(tmp_path, rec, frontend(tmp_path))
    message = str(caught.value)
    assert "Port 18999 is already in use" in message and "already running" in message
    assert "http://127.0.0.1:18999" in message and "PORT=" in message


def test_the_port_check_sees_a_real_listener() -> None:
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        port = server.getsockname()[1]
        assert port_in_use("127.0.0.1", port) is True
    assert port_in_use("127.0.0.1", port) is False  # closed again


def test_the_summary_never_contains_a_secret(tmp_path: Path) -> None:
    secret_password, secret_hash = "hunter2-hunter2", "feedfacefeedfacefeedfacefeedface"
    settings = settings_for(
        tmp_path,
        quotex_email="me@example.com",
        quotex_password=secret_password,
        telegram_api_id=12345,
        telegram_api_hash=secret_hash,
    )
    text = "\n".join(summarise(settings, env_file_exists=True).lines())
    assert secret_password not in text and secret_hash not in text and "me@example.com" not in text
    assert "Settings page" in text


def test_with_nothing_decided_it_says_where_the_engine_is_started(tmp_path: Path) -> None:
    summary = summarise(settings_for(tmp_path), env_file_exists=False)
    text = "\n".join(summary.lines())
    assert "Settings page" in text
    assert "demo" in text and "no backend/.env" in text
    assert "Log file" in text  # where to look when something goes wrong


def test_the_summary_says_real_money_is_only_allowed_on_the_dashboard(tmp_path: Path) -> None:
    text = "\n".join(summarise(settings_for(tmp_path), env_file_exists=True).lines())
    assert "demo" in text and "only on the dashboard" in text


def test_a_secret_key_is_created_once_and_the_owner_is_told_to_keep_a_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SECRET_KEY", raising=False)
    rec = Recorder()
    root = frontend(tmp_path)
    run_prepare(tmp_path, rec, root, with_key=False)
    created = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "SECRET_KEY=" in created
    assert any("SECRET_KEY" in line and "Keep a copy" in line for line in rec.said)
    assert all(line.split("=")[-1] not in " ".join(rec.said) for line in created.splitlines()[-1:])

    rec2 = Recorder()
    run_prepare(tmp_path, rec2, root, with_key=False)  # the second start changes nothing
    assert (tmp_path / ".env").read_text(encoding="utf-8") == created
    assert not any("SECRET_KEY" in line for line in rec2.said)
