"""Story #65: the suite runs in parallel and no test writes into the repository.

The parallel run, the isolation guard in `tests/conftest.py` and the documented gate time are
the speed-up. These tests cover the parts that can be tested without timing the whole suite;
the timings themselves are measured with `pytest --durations` and stated in the story's evidence
comment and in docs/process.md.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
from repo_snapshot import differences, snapshot

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    for rel in (
        "src/a.py",
        "sql/b.sql",
        "config/c.yaml",
        "docs/d.md",
        "tests/e.py",
        "pyproject.toml",
    ):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")
    return tmp_path


# AC4: a test that writes into the repository is caught --------------------------------------------


def test_ac4_an_unchanged_tree_has_no_differences(tree: Path) -> None:
    assert differences(snapshot(tree), snapshot(tree)) == []


def test_ac4_an_added_file_is_reported(tree: Path) -> None:
    before = snapshot(tree)
    (tree / "sql" / "99_broken").mkdir()
    (tree / "sql" / "99_broken" / "01.sql").write_text("select 1;", encoding="utf-8")
    assert differences(before, snapshot(tree)) == ["added: sql/99_broken/01.sql"]


def test_ac4_a_removed_file_is_reported(tree: Path) -> None:
    before = snapshot(tree)
    (tree / "docs" / "d.md").unlink()
    assert differences(before, snapshot(tree)) == ["removed: docs/d.md"]


def test_ac4_a_changed_file_is_reported(tree: Path) -> None:
    before = snapshot(tree)
    (tree / "config" / "c.yaml").write_text("a much longer replacement", encoding="utf-8")
    assert differences(before, snapshot(tree)) == ["changed: config/c.yaml"]


def test_ac4_a_rewrite_with_the_same_size_is_still_reported(tree: Path) -> None:
    before = snapshot(tree)
    path = tree / "src" / "a.py"
    stat = path.stat()
    path.write_text("y", encoding="utf-8")  # same size, newer time
    import os

    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    assert differences(before, snapshot(tree)) == ["changed: src/a.py"]


@pytest.mark.parametrize(
    "rel", ["src/__pycache__/a.cpython-312.pyc", "tests/.pytest_cache/v/cache", "src/x.pyc"]
)
def test_ac4_cache_files_are_ignored(tree: Path, rel: str) -> None:
    before = snapshot(tree)
    path = tree / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("cache", encoding="utf-8")
    assert differences(before, snapshot(tree)) == []


def test_ac4_files_outside_the_watched_folders_are_ignored(tree: Path) -> None:
    before = snapshot(tree)
    (tree / "data").mkdir()
    (tree / "data" / "warehouse.duckdb").write_text("w", encoding="utf-8")
    (tree / "reports").mkdir()
    (tree / "reports" / "r.md").write_text("r", encoding="utf-8")
    assert differences(before, snapshot(tree)) == []


def test_ac4_a_missing_watched_folder_is_not_an_error(tmp_path: Path) -> None:
    assert snapshot(tmp_path) == {}


def test_ac4_the_real_repository_is_watched() -> None:
    files = snapshot(ROOT)
    assert "pyproject.toml" in files
    assert any(name.startswith("sql/20_gold/") for name in files)
    assert any(name.startswith("tests/unit/") for name in files)
    assert not any("__pycache__" in name for name in files)


def test_ac4_the_conftest_takes_the_snapshot_only_in_the_main_process() -> None:
    text = (ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert "workerinput" in text
    assert "pytest_sessionstart" in text and "pytest_sessionfinish" in text
    assert "TESTS_FAILED" in text


def test_ac4_no_test_writes_a_folder_next_to_the_sql_stages() -> None:
    """The two tests that did (story #87) use a temporary folder now."""
    offenders = []
    for path in sorted((ROOT / "tests" / "unit").glob("test_*.py")):
        text = path.read_text(encoding="utf-8")
        if re.search(
            r"(GOLD_DIR|SILVER_DIR|RECON_DIR)\.parent\s*/\s*[\"'][^\"']+[\"']\)?\s*\n\s*\w+\.mkdir",
            text,
        ):
            offenders.append(path.name)
        if re.search(
            r"(GOLD_DIR|SILVER_DIR|RECON_DIR)(\.parent)?\s*/\s*[\"'][^\"']+[\"']\)\.(write_text|mkdir)",
            text,
        ):
            offenders.append(path.name)
    assert offenders == []


# The parallel configuration -----------------------------------------------------------------------


def _pytest_options() -> dict:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["tool"]["pytest"]["ini_options"]


def test_the_suite_runs_in_parallel_by_default() -> None:
    assert "-n auto" in _pytest_options()["addopts"]


def test_the_strict_markers_option_is_kept() -> None:
    assert "--strict-markers" in _pytest_options()["addopts"]


def test_xdist_is_a_declared_dev_dependency() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert any(d.startswith("pytest-xdist") for d in data["dependency-groups"]["dev"])


def test_the_gate_and_ci_still_run_the_same_pytest_command() -> None:
    # parallel comes from the pytest config, not from a different command line
    from revint import gate

    pytest_step = next(s for s in gate.CHECK_STEPS if s.name == "pytest")
    assert pytest_step.argv == ("uv", "run", "pytest", "-m", "not realdata")


def test_the_realdata_tests_are_still_excluded_from_the_gate() -> None:
    from revint import gate

    assert "not realdata" in gate.CHECK_STEPS[-1].argv


def test_documented_in_the_process_doc() -> None:
    text = (ROOT / "docs" / "process.md").read_text(encoding="utf-8")
    assert "-n 0" in text and "minutes" in text.lower()
