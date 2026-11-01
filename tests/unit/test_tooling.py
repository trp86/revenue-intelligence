"""Story #18: ruff, sqlfluff and pytest configuration (spec 10 sections 3 and 6)."""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _run(*args: str, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


# AC1: pytest passes without data/ -------------------------------------------


def test_ac1_pytest_is_configured_to_collect_from_tests_only() -> None:
    options = _pyproject()["tool"]["pytest"]["ini_options"]
    assert options["testpaths"] == ["tests"]


def test_ac1_test_layout_directories_exist() -> None:
    for name in ("unit", "sql", "api"):
        assert (ROOT / "tests" / name).is_dir(), f"missing tests/{name}"


# AC2: ruff ------------------------------------------------------------------


def test_ac2_ruff_is_configured_for_python_312() -> None:
    ruff = _pyproject()["tool"]["ruff"]
    assert ruff["target-version"] == "py312"
    assert ruff["lint"]["select"], "ruff has no rule selection"


def test_ac2_ruff_flags_an_unused_import(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text("import os\n", encoding="utf-8")
    result = _run("ruff", "check", "--config", str(ROOT / "pyproject.toml"), str(sample))
    assert result.returncode == 1, result.stdout
    assert "F401" in result.stdout


def test_ac2_ruff_check_passes_on_the_repo() -> None:
    result = _run("ruff", "check", ".")
    assert result.returncode == 0, result.stdout + result.stderr


# AC3: sqlfluff, DuckDB dialect, lowercase keywords --------------------------


def _sqlfluff_config() -> str:
    return (ROOT / ".sqlfluff").read_text(encoding="utf-8")


def test_ac3_sqlfluff_uses_duckdb_dialect() -> None:
    assert "dialect = duckdb" in _sqlfluff_config()


def test_ac3_sqlfluff_requires_lowercase_keywords() -> None:
    text = _sqlfluff_config()
    assert "[sqlfluff:rules:capitalisation.keywords]" in text
    assert "capitalisation_policy = lower" in text


def test_ac3_sqlfluff_accepts_lowercase_and_rejects_uppercase_keywords(tmp_path: Path) -> None:
    config = str(ROOT / ".sqlfluff")
    good = tmp_path / "good.sql"
    good.write_text("select 1 as one\n", encoding="utf-8")
    bad = tmp_path / "bad.sql"
    bad.write_text("SELECT 1 AS one\n", encoding="utf-8")

    ok = _run("sqlfluff", "lint", "--config", config, str(good))
    assert ok.returncode == 0, ok.stdout + ok.stderr
    nok = _run("sqlfluff", "lint", "--config", config, str(bad))
    assert nok.returncode != 0
    assert "CP01" in nok.stdout


def test_ac3_sqlfluff_lint_passes_on_the_sql_folder() -> None:
    result = _run("sqlfluff", "lint", "sql")
    assert result.returncode == 0, result.stdout + result.stderr


# AC4: realdata marker -------------------------------------------------------

REALDATA_TEST = """\
import pytest


@pytest.mark.realdata
def test_needs_real_data():
    raise AssertionError("must not run without data/")


def test_plain():
    assert True
"""


def _make_project(root: Path, with_data: bool) -> None:
    """A minimal project: the real tests/conftest.py plus the real marker config."""
    markers = _pyproject()["tool"]["pytest"]["ini_options"]["markers"]
    marker_lines = "".join(f"    {m}\n" for m in markers)
    (root / "pytest.ini").write_text(
        f"[pytest]\nmarkers =\n{marker_lines}addopts = --strict-markers\n"
        "filterwarnings = error\n",
        encoding="utf-8",
    )
    tests = root / "tests"
    tests.mkdir()
    # the real conftest and the helper it imports (the repository snapshot guard, story #65)
    for name in ("conftest.py", "repo_snapshot.py"):
        text = (ROOT / "tests" / name).read_text(encoding="utf-8")
        (tests / name).write_text(text, encoding="utf-8")
    (tests / "test_sample.py").write_text(REALDATA_TEST, encoding="utf-8")
    if with_data:
        (root / "data").mkdir()


def test_ac4_marker_is_registered_in_pyproject() -> None:
    markers = _pyproject()["tool"]["pytest"]["ini_options"]["markers"]
    assert any(m.startswith("realdata") for m in markers)


def test_ac4_realdata_test_is_skipped_not_failed_when_data_is_absent(tmp_path: Path) -> None:
    _make_project(tmp_path, with_data=False)
    result = _run("pytest", "-rs", "-p", "no:cacheprovider", cwd=tmp_path)
    assert result.returncode == 0, result.stdout
    assert "1 passed, 1 skipped" in result.stdout
    assert "warning" not in result.stdout.lower()
    assert "data/ not present" in result.stdout


def test_ac4_realdata_test_runs_when_data_is_present(tmp_path: Path) -> None:
    _make_project(tmp_path, with_data=True)
    result = _run("pytest", "-p", "no:cacheprovider", cwd=tmp_path)
    assert result.returncode == 1
    assert "1 failed, 1 passed" in result.stdout
