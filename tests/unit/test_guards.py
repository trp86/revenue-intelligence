"""Story #19: secrets and data guards (spec 10 section 8)."""

from __future__ import annotations

import io
import logging
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from revint.guards import env_example_violations, tracked_file_violations
from revint.ingest.raw import RawAccessError, open_raw

ROOT = Path(__file__).resolve().parents[2]
GIT = shutil.which("git")
needs_git = pytest.mark.skipif(GIT is None, reason="git not available")

MARKER = "ROW-LEVEL-VALUE-12345"


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def tracked_files(repo: Path) -> list[str]:
    result = git(repo, "ls-files")
    assert result.returncode == 0, result.stderr
    return result.stdout.splitlines()


@pytest.fixture
def temp_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    assert git(repo, "init", "-q").returncode == 0
    return repo


# AC1: nothing tracked under data/, .env not tracked ---------------------------


@needs_git
def test_ac1_real_repo_tracks_nothing_under_data_and_no_env_file() -> None:
    if git(ROOT, "rev-parse", "--is-inside-work-tree").returncode != 0:
        pytest.skip("not a git checkout")
    assert tracked_file_violations(tracked_files(ROOT)) == []


@needs_git
def test_ac1_guard_fails_when_a_file_under_data_is_tracked(temp_repo: Path) -> None:
    (temp_repo / "data" / "raw").mkdir(parents=True)
    (temp_repo / "data" / "raw" / "sales.xlsx").write_bytes(b"x")
    (temp_repo / "ok.txt").write_text("ok", encoding="utf-8")
    assert git(temp_repo, "add", "-f", "data/raw/sales.xlsx", "ok.txt").returncode == 0
    violations = tracked_file_violations(tracked_files(temp_repo))
    assert violations == ["data/raw/sales.xlsx"]


@needs_git
def test_ac1_guard_fails_when_env_is_tracked(temp_repo: Path) -> None:
    (temp_repo / ".env").write_text("GEMINI_API_KEY=abc\n", encoding="utf-8")
    assert git(temp_repo, "add", "-f", ".env").returncode == 0
    assert tracked_file_violations(tracked_files(temp_repo)) == [".env"]


@needs_git
def test_ac1_guard_passes_on_a_clean_repo(temp_repo: Path) -> None:
    (temp_repo / ".env.example").write_text("GEMINI_API_KEY=\n", encoding="utf-8")
    (temp_repo / "src").mkdir()
    (temp_repo / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    assert git(temp_repo, "add", "-A").returncode == 0
    assert tracked_file_violations(tracked_files(temp_repo)) == []


@pytest.mark.parametrize(
    ("paths", "expected"),
    [
        (["data/bronze/x.parquet"], ["data/bronze/x.parquet"]),
        (["data/.gitkeep"], ["data/.gitkeep"]),
        ([".env"], [".env"]),
        (["sub/.env"], ["sub/.env"]),
        ([".env.example"], []),
        (["src/revint/data_utils.py", "tests/fixtures/data/a.csv", "docs/data.md"], []),
        (["database.py", "datasets/a.csv"], []),
    ],
)
def test_ac1_violation_rules(paths: list[str], expected: list[str]) -> None:
    assert tracked_file_violations(paths) == expected


# AC2: .env.example has no values ---------------------------------------------


def test_ac2_real_env_example_has_no_values() -> None:
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert env_example_violations(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "GEMINI_API_KEY=\n",
        "# comment\n\nGEMINI_API_KEY=\nOTHER=\n",
        "GEMINI_API_KEY=   \n",
        'GEMINI_API_KEY=""\n',
        "GEMINI_API_KEY=''\n",
        "export GEMINI_API_KEY=\n",
        "",
    ],
)
def test_ac2_empty_values_pass(text: str) -> None:
    assert env_example_violations(text) == []


@pytest.mark.parametrize(
    ("text", "names"),
    [
        ("GEMINI_API_KEY=abc123\n", ["GEMINI_API_KEY"]),
        ("GEMINI_API_KEY=\nOTHER=x\n", ["OTHER"]),
        ('GEMINI_API_KEY="abc"\n', ["GEMINI_API_KEY"]),
        ("export GEMINI_API_KEY=abc\n", ["GEMINI_API_KEY"]),
        ("A=1\nB=2\n", ["A", "B"]),
        ("GEMINI_API_KEY = abc\n", ["GEMINI_API_KEY"]),
    ],
)
def test_ac2_non_empty_values_fail_and_name_the_variable(text: str, names: list[str]) -> None:
    assert env_example_violations(text) == names


def test_ac2_violations_never_include_the_value() -> None:
    result = env_example_violations("GEMINI_API_KEY=super-secret-value\n")
    assert result == ["GEMINI_API_KEY"]
    assert "super-secret-value" not in " ".join(result)


# AC3: raw files open read-only -----------------------------------------------


@pytest.fixture
def raw_dir(tmp_path: Path) -> Path:
    raw = tmp_path / "data" / "raw"
    raw.mkdir(parents=True)
    (raw / "sales.xlsx").write_bytes(f"header\n{MARKER}\n".encode())
    return raw


def test_ac3_helper_returns_a_readable_binary_file(raw_dir: Path) -> None:
    with open_raw(raw_dir / "sales.xlsx", raw_dir) as handle:
        assert handle.readable()
        assert not handle.writable()
        assert MARKER.encode() in handle.read()


def test_ac3_write_attempt_raises_and_file_is_unchanged(raw_dir: Path) -> None:
    target = raw_dir / "sales.xlsx"
    before = target.read_bytes()
    with open_raw(target, raw_dir) as handle, pytest.raises(io.UnsupportedOperation):
        handle.write(b"tamper")
    assert target.read_bytes() == before


def test_ac3_helper_takes_no_mode_so_write_modes_cannot_be_requested(raw_dir: Path) -> None:
    with pytest.raises(TypeError):
        open_raw(raw_dir / "sales.xlsx", raw_dir, "wb")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        open_raw(raw_dir / "sales.xlsx", raw_dir, mode="ab")  # type: ignore[call-arg]


def test_ac3_helper_works_on_a_read_only_file(raw_dir: Path) -> None:
    target = raw_dir / "sales.xlsx"
    target.chmod(0o444)
    try:
        with open_raw(target, raw_dir) as handle:
            assert handle.read(6) == b"header"
    finally:
        target.chmod(0o666)


def test_ac3_path_outside_raw_dir_is_refused(raw_dir: Path, tmp_path: Path) -> None:
    outside = tmp_path / "other.xlsx"
    outside.write_bytes(b"x")
    with pytest.raises(RawAccessError, match="outside"):
        open_raw(outside, raw_dir)


def test_ac3_dotdot_traversal_out_of_raw_dir_is_refused(raw_dir: Path, tmp_path: Path) -> None:
    (tmp_path / "secret.txt").write_bytes(b"x")
    with pytest.raises(RawAccessError, match="outside"):
        open_raw(raw_dir / ".." / ".." / "secret.txt", raw_dir)


def test_ac3_sibling_folder_with_same_prefix_is_refused(raw_dir: Path) -> None:
    sibling = raw_dir.parent / "raw_backup"
    sibling.mkdir()
    (sibling / "a.xlsx").write_bytes(b"x")
    with pytest.raises(RawAccessError, match="outside"):
        open_raw(sibling / "a.xlsx", raw_dir)


def test_ac3_relative_path_is_resolved_against_raw_dir(raw_dir: Path) -> None:
    with open_raw(Path("sales.xlsx"), raw_dir) as handle:
        assert MARKER.encode() in handle.read()


def test_ac3_missing_file_raises_file_not_found(raw_dir: Path) -> None:
    with pytest.raises(FileNotFoundError):
        open_raw(raw_dir / "missing.xlsx", raw_dir)


def test_ac3_directory_is_refused(raw_dir: Path) -> None:
    (raw_dir / "sub").mkdir()
    with pytest.raises(RawAccessError, match="not a file"):
        open_raw(raw_dir / "sub", raw_dir)


def test_ac3_default_raw_dir_comes_from_settings() -> None:
    from revint.config import load_settings

    expected = load_settings(env={}).paths.raw
    missing = expected / "does-not-exist.xlsx"
    with pytest.raises(FileNotFoundError):
        open_raw(missing)


# AC4: logs contain counts only -----------------------------------------------


def test_ac4_log_output_has_counts_only_and_no_row_values(
    raw_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG, logger="revint"):
        with open_raw(raw_dir / "sales.xlsx", raw_dir) as handle:
            handle.read()
    assert caplog.records, "the helper should log that it opened a raw file"
    assert MARKER not in caplog.text
    for record in caplog.records:
        assert record.name.startswith("revint")
        assert re.search(r"\d+", record.getMessage()), "message should carry a count"


def test_ac4_log_does_not_include_file_contents_on_refusal(
    raw_dir: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    outside = tmp_path / "other.xlsx"
    outside.write_bytes(MARKER.encode())
    with caplog.at_level(logging.DEBUG, logger="revint"), pytest.raises(RawAccessError):
        open_raw(outside, raw_dir)
    assert MARKER not in caplog.text
