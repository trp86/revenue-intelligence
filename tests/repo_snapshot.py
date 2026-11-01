"""A cheap snapshot of the repository's code and docs, to catch a test that writes into it.

Tests run in parallel (pytest-xdist, `-n auto`), so a test that writes into the repository tree
instead of its own temporary folder could break another worker. `tests/conftest.py` takes a
snapshot when a run starts and compares it when the run ends; a difference fails the run and
names the files. Not a test module.
"""

from __future__ import annotations

from pathlib import Path

WATCHED = ("src", "sql", "config", "docs", "tests", "pyproject.toml")
_IGNORED_PARTS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".venv", "node_modules"}
_IGNORED_SUFFIXES = {".pyc", ".pyo"}


def snapshot(root: Path, watched: tuple[str, ...] = WATCHED) -> dict[str, tuple[int, int]]:
    """Every watched file as {relative path: (size, modified time in ns)}."""
    found: dict[str, tuple[int, int]] = {}
    for name in watched:
        base = root / name
        paths = [base] if base.is_file() else sorted(base.rglob("*")) if base.is_dir() else []
        for path in paths:
            relative = path.relative_to(root)
            if not path.is_file():
                continue
            if _IGNORED_PARTS & set(relative.parts) or path.suffix in _IGNORED_SUFFIXES:
                continue
            stat = path.stat()
            found[relative.as_posix()] = (stat.st_size, stat.st_mtime_ns)
    return found


def differences(before: dict[str, tuple[int, int]], after: dict[str, tuple[int, int]]) -> list[str]:
    """The files added, removed or changed between two snapshots, as readable lines."""
    lines = [f"added: {p}" for p in sorted(after.keys() - before.keys())]
    lines += [f"removed: {p}" for p in sorted(before.keys() - after.keys())]
    lines += [
        f"changed: {p}"
        for p in sorted(p for p in before.keys() & after.keys() if before[p] != after[p])
    ]
    return lines
