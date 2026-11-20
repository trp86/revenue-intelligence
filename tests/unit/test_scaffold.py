"""Story #15: repo and uv scaffold (spec 10 sections 2, 3 and 8)."""

from __future__ import annotations

import importlib
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

LAYOUT_DIRS = [
    "config",
    "sql/10_silver",
    "sql/20_gold",
    "sql/30_opportunities",
    "sql/checks",
    "tests/unit",
    "tests/sql",
    "tests/api",
    "tests/fixtures",
    "src/revint",
]
SUBPACKAGES = ["ingest", "pipeline", "query", "ai", "api", "backtest", "cli"]


def test_ac1_project_declares_python_312_and_lockfile_exists() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["requires-python"] == ">=3.12"
    assert (ROOT / "uv.lock").is_file()


def test_ac1_runtime_and_dev_dependencies_declared() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    runtime = " ".join(pyproject["project"]["dependencies"]).lower()
    for name in ["polars", "duckdb", "fastapi", "pydantic", "typer", "google-genai"]:
        assert name in runtime, f"missing runtime dependency {name}"
    dev = " ".join(pyproject["dependency-groups"]["dev"]).lower()
    for name in ["pytest", "ruff", "sqlfluff"]:
        assert name in dev, f"missing dev dependency {name}"


@pytest.mark.parametrize("rel", LAYOUT_DIRS)
def test_ac2_layout_directory_exists(rel: str) -> None:
    assert (ROOT / rel).is_dir(), f"missing directory {rel}"


@pytest.mark.parametrize("rel", ["config", "sql/10_silver", "sql/20_gold",
                                 "sql/30_opportunities", "sql/checks",
                                 "tests/sql", "tests/api", "tests/fixtures"])
def test_ac2_empty_layout_directories_are_tracked_by_a_placeholder(rel: str) -> None:
    assert any((ROOT / rel).iterdir()), f"{rel} would not survive a git clone"


def test_ac2_no_invented_config_files() -> None:
    # settings.yaml arrived with story #16, definitions.yaml with story #86 and the hosting
    # overlay settings.production.yaml with story #193; explore.yaml belongs to a later epic.
    names = {p.name for p in (ROOT / "config").glob("*.yaml")}
    assert names <= {"settings.yaml", "definitions.yaml", "settings.production.yaml"}


def test_ac2_import_revint() -> None:
    assert importlib.import_module("revint").__name__ == "revint"


@pytest.mark.parametrize("name", SUBPACKAGES)
def test_ac2_subpackage_importable(name: str) -> None:
    assert importlib.import_module(f"revint.{name}").__name__ == f"revint.{name}"


def test_ac2_frontend_lives_in_its_own_folder() -> None:
    # story #15 left frontend/ to E7; story #135 created it, as CLAUDE.md's commands expect
    assert (ROOT / "frontend" / "package.json").is_file()
    assert not (ROOT / "src" / "revint" / "frontend").exists()


def test_ac3_env_example_lists_gemini_key_without_value() -> None:
    lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    entries = [ln for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]
    assert entries, ".env.example has no variables"
    parsed = dict(ln.split("=", 1) for ln in entries)
    assert "GEMINI_API_KEY" in parsed
    assert all(v.strip() == "" for v in parsed.values()), "values must be empty"


@pytest.mark.skipif(shutil.which("git") is None, reason="git not available")
@pytest.mark.parametrize("path", ["data/x", ".env"])
def test_ac4_gitignore_covers_data_and_env(path: str) -> None:
    result = subprocess.run(
        ["git", "check-ignore", "-q", path],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, f"{path} is not git-ignored"
