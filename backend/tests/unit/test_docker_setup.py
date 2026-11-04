"""The Docker setup (decision D-69): what the image and compose file promise, checked as text,
and the start script run for real with a stand-in for Python.

Building the image itself needs Docker; that is done by hand (docs/reports/docker.md). These tests
make sure the promises that matter for safety cannot be quietly broken by an edit."""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app
from tests.api_support import BASE_URL, settings_for

ROOT = Path(__file__).resolve().parents[3]
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
DOCKERIGNORE = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
COMPOSE = (ROOT / "compose.yaml").read_text(encoding="utf-8")
ENTRYPOINT = ROOT / "docker" / "entrypoint.sh"


# --- the setting that lets the application listen inside a container ----------------------------


def test_listening_on_all_addresses_is_refused_unless_it_is_the_container() -> None:
    with pytest.raises(ValidationError, match="CONTAINER=true"):
        Settings(_env_file=None, host="0.0.0.0")  # type: ignore[call-arg]
    inside = Settings(_env_file=None, host="0.0.0.0", container=True)  # type: ignore[call-arg]
    assert inside.host == "0.0.0.0" and inside.allow_public_bind is False


async def test_in_a_container_the_localhost_only_host_check_stays_on(tmp_path: Path) -> None:
    """CONTAINER is not ALLOW_PUBLIC_BIND: a request for any other name is still refused."""
    import httpx

    config = settings_for(tmp_path, host="0.0.0.0", container=True)
    app = create_app(config)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
        hostile = await client.get("/api/v1/health", headers={"Host": "evil.example"})
        assert hostile.status_code == 403
        assert hostile.json()["error"]["code"] == "host_not_allowed"
        assert (await client.get("/api/v1/health", headers={"Host": "127.0.0.1:8000"})).status_code
        assert (
            await client.get("/api/v1/health", headers={"Host": "localhost"})
        ).status_code != 403


# --- the image ---------------------------------------------------------------------------------


def test_the_image_runs_as_an_ordinary_user_with_its_data_in_a_volume() -> None:
    last_stage = DOCKERFILE.split("FROM ")[-1]
    assert re.search(r"^USER qte$", last_stage, re.MULTILINE)  # never root
    assert "useradd" in last_stage and "--uid 10001" in last_stage
    assert 'VOLUME ["/data"]' in last_stage and "DATA_DIR=/data" in last_stage
    assert "CONTAINER=true" in last_stage and "HOST=0.0.0.0" in last_stage
    assert "ENTRYPOINT" in last_stage and "HEALTHCHECK" in last_stage


def test_the_running_image_has_no_build_tools_or_node() -> None:
    stages = DOCKERFILE.split("\nFROM ")[1:]
    assert len(stages) == 3  # the dashboard, the packages, what runs
    runtime = stages[-1]
    code = "\n".join(
        line for line in runtime.splitlines() if not line.lstrip().startswith("#")
    )  # comments may name them; instructions may not use them
    for tool in (r"\bgit\b", r"\bnpm\b", r"apt-get", r"pip install", r"\buv\b"):
        assert not re.search(tool, code), tool
    assert "COPY --from=web" in runtime and "COPY --from=python-deps" in runtime


def test_the_image_is_built_from_the_locked_dependencies_and_pinned_bases() -> None:
    assert "uv sync --frozen --no-dev" in DOCKERFILE
    assert "npm ci" in DOCKERFILE
    bases = re.findall(r"^FROM (\S+)", DOCKERFILE, re.MULTILINE)
    assert all(":" in base and not base.endswith(":latest") for base in bases), bases
    assert re.search(r"uv==\d+\.\d+\.\d+", DOCKERFILE)


def test_no_secret_or_local_state_can_get_into_the_image() -> None:
    copies = [line for line in DOCKERFILE.splitlines() if line.startswith("COPY")]
    assert not any(".env" in line and ".env.example" not in line for line in copies)
    for pattern in (
        "**/.env",
        "**/*.session",
        "**/session.json",
        "backups",
        "backend/data",
        ".git",
    ):
        assert pattern in DOCKERIGNORE, pattern
    assert "**/*.db" in DOCKERIGNORE
    # a bare `COPY . .` would bring in everything the ignore file forgot
    assert not re.search(r"^COPY \. ", DOCKERFILE, re.MULTILINE)
    assert "SECRET_KEY=" not in DOCKERFILE


# --- the compose file --------------------------------------------------------------------------


def test_the_port_is_published_to_this_machine_only() -> None:
    ports = re.findall(r'^\s*-\s*"?([0-9.:]+:\d+:\d+)"?\s*$', COMPOSE, re.MULTILINE)
    assert ports == ["127.0.0.1:8000:8000"]
    assert "0.0.0.0" not in COMPOSE and "network_mode: host" not in COMPOSE


def test_the_compose_file_hardens_the_container_and_keeps_the_data_in_a_named_volume() -> None:
    for line in (
        "read_only: true",
        "no-new-privileges:true",
        "stop_signal: SIGINT",
        "init: true",
        "restart: unless-stopped",
        "qte-data:/data",
    ):
        assert line in COMPOSE, line
    assert re.search(r"cap_drop:\s*\n\s*- ALL", COMPOSE)
    assert re.search(r"mem_limit: \d+m", COMPOSE)
    assert "privileged" not in COMPOSE


def test_the_compose_file_is_valid_yaml_with_the_expected_shape() -> None:
    yaml = pytest.importorskip("yaml")
    document = yaml.safe_load(COMPOSE)
    app = document["services"]["app"]
    assert app["ports"] == ["127.0.0.1:8000:8000"]
    assert app["volumes"] == ["qte-data:/data"] and "qte-data" in document["volumes"]
    assert app["environment"]["SECRET_KEY"] == "${SECRET_KEY:-}"  # optional, never a value


# --- the start script, run for real ------------------------------------------------------------

SH = shutil.which("sh")


@pytest.fixture
def stub_python(tmp_path: Path) -> Path:
    """A `python` that records how it was called and answers the two calls the script makes."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    shim = bin_dir / "python"
    shim.write_text(
        "#!/bin/sh\n"
        'echo "$*" >> "$STUB_LOG"\n'
        'case "$1" in\n'
        '  -c) echo "stub-generated-key" ;;\n'
        '  -m) [ "${STUB_MIGRATION_FAILS:-}" = "1" ] && exit 3 ; exit 0 ;;\n'
        "esac\n",
        encoding="utf-8",
        newline="\n",
    )
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
    return bin_dir


def run_entrypoint(
    tmp_path: Path, stub_python: Path, *command: str, **env: str
) -> subprocess.CompletedProcess[str]:
    assert SH is not None
    base = {
        "PATH": f"{stub_python}{os.pathsep}{os.environ['PATH']}",
        "DATA_DIR": str(tmp_path / "data"),
        "STUB_LOG": str(tmp_path / "calls.log"),
        "HOME": str(tmp_path),
    }
    return subprocess.run(  # noqa: S603 - the repository's own script
        [SH, str(ENTRYPOINT), *command],
        env={**base, **env},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def calls(tmp_path: Path) -> list[str]:
    log = tmp_path / "calls.log"
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


needs_sh = pytest.mark.skipif(SH is None, reason="no POSIX shell on this machine")


def test_the_start_script_uses_unix_line_endings_and_fails_on_the_first_error() -> None:
    raw = ENTRYPOINT.read_bytes()
    assert b"\r" not in raw
    assert raw.startswith(b"#!/bin/sh\n") and b"\nset -eu\n" in raw and b"\numask 077\n" in raw
    assert b"\nexec " in raw  # the application becomes the process Docker stops


@needs_sh
def test_a_first_start_makes_a_private_key_migrates_and_runs_the_command(
    tmp_path: Path, stub_python: Path
) -> None:
    result = run_entrypoint(tmp_path, stub_python, "sh", "-c", 'echo "key=$SECRET_KEY"')
    assert result.returncode == 0, result.stderr
    assert "key=stub-generated-key" in result.stdout  # the command got the key
    keyfile = tmp_path / "data" / "secret_key"
    assert keyfile.read_text(encoding="utf-8").strip() == "stub-generated-key"
    if os.name == "posix":
        assert stat.S_IMODE(keyfile.stat().st_mode) == 0o600  # nobody else can read it
    assert "back that file up SEPARATELY" in result.stderr
    assert "stub-generated-key" not in result.stderr  # the key is never printed
    assert calls(tmp_path)[-1] == "-m alembic upgrade head"  # migrated before the command ran


@needs_sh
def test_a_later_start_reuses_the_key_and_does_not_make_another(
    tmp_path: Path, stub_python: Path
) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "secret_key").write_text("the-existing-key\n", encoding="utf-8")
    result = run_entrypoint(tmp_path, stub_python, "sh", "-c", 'echo "key=$SECRET_KEY"')
    assert "key=the-existing-key" in result.stdout
    assert not any(call.startswith("-c") for call in calls(tmp_path))  # no key was generated
    assert (tmp_path / "data" / "secret_key").read_text(encoding="utf-8") == "the-existing-key\n"


@needs_sh
def test_a_key_given_in_the_environment_wins_and_no_key_file_is_made(
    tmp_path: Path, stub_python: Path
) -> None:
    result = run_entrypoint(
        tmp_path,
        stub_python,
        "sh",
        "-c",
        'echo "key=$SECRET_KEY"',
        SECRET_KEY="from-the-environment",
    )
    assert "key=from-the-environment" in result.stdout
    assert not (tmp_path / "data" / "secret_key").exists()


@needs_sh
def test_a_failed_migration_stops_the_start_and_the_command_never_runs(
    tmp_path: Path, stub_python: Path
) -> None:
    result = run_entrypoint(
        tmp_path, stub_python, "sh", "-c", "echo started", STUB_MIGRATION_FAILS="1"
    )
    assert result.returncode == 3
    assert "started" not in result.stdout


@needs_sh
def test_the_command_replaces_the_script_so_its_exit_code_is_the_containers(
    tmp_path: Path, stub_python: Path
) -> None:
    result = run_entrypoint(tmp_path, stub_python, "sh", "-c", "exit 7")
    assert result.returncode == 7
