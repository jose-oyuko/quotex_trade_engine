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


def test_within_the_quotex_package_only_the_client_module_imports_pyquotex() -> None:
    """The adapter logic stays testable without the library: only pyquotex_client.py imports it."""
    importers = sorted(
        path.name
        for path in (APP / "quotex").rglob("*.py")
        if any(m == "pyquotex" or m.startswith("pyquotex.") for m in imported_modules(path))
    )
    assert importers == ["pyquotex_client.py"]


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
