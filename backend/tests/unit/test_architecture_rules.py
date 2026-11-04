"""Rules from CLAUDE.md / docs/DECISIONS.md that are cheap to check mechanically."""

from __future__ import annotations

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "app"


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_only_the_quotex_package_imports_pyquotex() -> None:
    """Decision D-6: one adapter, one place to fix when the unofficial library breaks."""
    offenders = [
        str(path.relative_to(APP))
        for path in APP.rglob("*.py")
        if "quotex" not in path.relative_to(APP).parts[:1]
        and any(m == "pyquotex" or m.startswith("pyquotex.") for m in imported_modules(path))
    ]
    assert offenders == []


def test_within_the_quotex_package_only_the_two_library_modules_import_pyquotex() -> None:
    """The adapter logic stays testable without the library: only the connection
    (pyquotex_client.py) and the dashboard login (pyquotex_login.py, D-66) import it."""
    importers = sorted(
        path.name
        for path in (APP / "quotex").rglob("*.py")
        if any(m == "pyquotex" or m.startswith("pyquotex.") for m in imported_modules(path))
    )
    assert importers == ["pyquotex_client.py", "pyquotex_login.py"]


def test_the_guard_actually_sees_imports() -> None:
    """Make sure the check above is not vacuous."""
    assert "pyquotex.stable_api" in imported_modules(APP / "quotex" / "pyquotex_client.py")


def test_only_the_telethon_wrapper_imports_telethon() -> None:
    """Same idea as pyquotex: the Telegram library sits behind one small module."""
    importers = sorted(
        str(path.relative_to(APP))
        for path in APP.rglob("*.py")
        if any(m == "telethon" or m.startswith("telethon.") for m in imported_modules(path))
    )
    assert importers == [str(Path("telegram") / "telethon_source.py")]


def test_the_signals_package_knows_nothing_about_telegram_the_database_or_quotex() -> None:
    """Parsing and the pipeline are pure: they take messages and events, whoever sends them."""
    forbidden = ("app.telegram", "app.db", "app.quotex", "app.api", "telethon", "sqlalchemy")
    offenders = [
        f"{path.name}: {module}"
        for path in (APP / "signals").rglob("*.py")
        for module in imported_modules(path)
        if module.startswith(forbidden)
    ]
    assert offenders == []


def test_the_telegram_package_does_not_reach_into_the_database_or_quotex() -> None:
    forbidden = ("app.db", "app.quotex", "app.api", "pyquotex", "sqlalchemy")
    offenders = [
        f"{path.name}: {module}"
        for path in (APP / "telegram").rglob("*.py")
        for module in imported_modules(path)
        if module.startswith(forbidden)
    ]
    assert offenders == []


def test_the_engine_never_sleeps_or_waits_a_fixed_time() -> None:
    """Decision D-13: results are awaited as events. No `sleep(duration + N)` or any other sleep
    anywhere in the engine."""
    problems: list[str] = []
    for path in (APP / "engine").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call):
                name = ast.unparse(node.func)
                if name.endswith("sleep"):
                    problems.append(f"{path.name}:{node.lineno} {name}")
    assert problems == []


def test_the_engine_has_no_database_access_on_its_hot_path() -> None:
    """Decision D-4: the executor, the chain and the strategies cannot reach the database at all;
    the manager and engine only need the type of the start-up recovery result. The life-cycle
    modules (decision D-63: they run only when the engine is started or stopped, from the
    dashboard) may use the database, and nothing on the signal-to-order path may import them."""
    forbidden = ("sqlalchemy", "app.db")
    lifecycle = {"controller.py", "flags.py", "logins.py"}
    hot = [
        p
        for p in (APP / "engine").glob("*.py")
        if p.name not in {"manager.py", "engine.py"} | lifecycle
    ]
    offenders = [
        f"{path.name}: {module}"
        for path in hot
        for module in imported_modules(path)
        if module.startswith(forbidden)
    ]
    assert offenders == []
    for name in ("manager.py", "engine.py"):
        db_imports = {m for m in imported_modules(APP / "engine" / name) if m.startswith(forbidden)}
        assert db_imports <= {"app.db.recovery"}, (name, db_imports)
    reaching_lifecycle = [
        f"{path.name}: {module}"
        for path in (APP / "engine").glob("*.py")
        if path.name not in lifecycle
        for module in imported_modules(path)
        if module in {"app.engine.controller", "app.engine.flags", "app.engine.logins"}
    ]
    assert reaching_lifecycle == []


def test_the_engine_does_not_know_the_api_or_the_telethon_wrapper() -> None:
    """`engine` is below `api` in the layering and reaches Telegram only through the listener."""
    offenders = [
        f"{path.name}: {module}"
        for path in (APP / "engine").glob("*.py")
        for module in imported_modules(path)
        if module.startswith(("app.api", "fastapi", "telethon", "app.telegram.telethon_source"))
    ]
    assert offenders == []


def test_no_blocking_calls_in_the_application() -> None:
    """Decisions D-13/D-14: no time.sleep, no requests, no input() anywhere in app/."""
    problems: list[str] = []
    for path in APP.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                    if (func.value.id, func.attr) == ("time", "sleep"):
                        problems.append(f"{path.name}:{node.lineno} time.sleep")
                    if func.value.id == "requests":
                        problems.append(f"{path.name}:{node.lineno} requests.{func.attr}")
                if isinstance(func, ast.Name) and func.id == "input":
                    problems.append(f"{path.name}:{node.lineno} input()")
    assert problems == []


def test_only_the_api_layer_knows_the_web_framework() -> None:
    """Everything below the API (engine, services, database, domain) is plain Python, so it can be
    tested and reused without FastAPI."""
    importers = sorted(
        str(path.relative_to(APP))
        for path in APP.rglob("*.py")
        if any(m.split(".")[0] in {"fastapi", "starlette"} for m in imported_modules(path))
    )
    allowed = ("api", "main.py")
    assert [p for p in importers if Path(p).parts[0] not in allowed] == []
    assert importers, "the check must see the API's own imports"


def test_lower_layers_never_import_the_layers_above_them() -> None:
    """docs/CONVENTIONS.md: `api` -> `engine/services` -> repositories / quotex / telegram."""
    above = {
        "domain": ("app.api", "app.services", "app.engine", "app.db", "app.quotex", "app.telegram"),
        "events": ("app.api", "app.services", "app.engine", "app.db"),
        "db": ("app.api", "app.services", "app.engine"),
        "quotex": ("app.api", "app.services", "app.engine"),
        "engine": ("app.api", "app.services"),
        "services": ("app.api",),
    }
    offenders = [
        f"{path.relative_to(APP)}: {module}"
        for layer, forbidden in above.items()
        for path in (APP / layer).rglob("*.py")
        for module in imported_modules(path)
        if module.startswith(forbidden)
    ]
    assert offenders == []


def test_the_api_reaches_the_outside_world_only_through_the_engine_and_services() -> None:
    """The API never talks to Quotex or Telegram directly (decision D-6): only their error types."""
    offenders = [
        f"{path.relative_to(APP)}: {module}"
        for path in (APP / "api").rglob("*.py")
        for module in imported_modules(path)
        if module.startswith(("pyquotex", "telethon", "app.telegram"))
        or (module.startswith("app.quotex") and module != "app.quotex.errors")
    ]
    assert offenders == []
