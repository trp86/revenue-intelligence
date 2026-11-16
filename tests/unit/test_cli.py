"""Story #17: typer `revint` CLI skeleton (spec 10 section 5)."""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from collections.abc import Iterator
from pathlib import Path

import pytest
import typer.main
from typer.testing import CliRunner

from revint import config
from revint.cli import app

ROOT = Path(__file__).resolve().parents[2]
runner = CliRunner()

GROUPS = ["build", "check", "report", "opportunities", "backtest", "ai", "app", "serve"]

# Every leaf command in spec 10 section 5, as the argument list that runs it.
LEAF_COMMANDS = [
    ["build", "bronze"],
    ["build", "silver"],
    ["build", "gold"],
    ["build", "all"],
    ["check"],
    ["report", "dq"],
    ["report", "dictionary"],
    ["opportunities", "build"],
    ["opportunities", "build", "--as-of", "2020-01-31"],
    ["backtest", "run"],
    ["backtest", "report"],
    ["ai", "generate"],
    ["app", "init"],
    ["serve"],
    ["user", "add"],  # story #191
    ["user", "remove"],
    ["user", "list"],
]

# These commands are real: build bronze (#33), build silver and build all (#45,
# tests/unit/test_build_commands.py), build gold (#87), check (#43), report dq (#42),
# report dictionary (#86), opportunities build (#116, tests/unit/test_opportunities_build.py),
# serve (#134, tests/unit/test_api.py), ai generate and app init (#137,
# tests/unit/test_ai.py).
# The rest stay stubs.
REAL_COMMANDS = [
    ["build", "bronze"],
    ["build", "silver"],
    ["build", "gold"],
    ["build", "all"],
    ["check"],
    ["report", "dq"],
    ["report", "dictionary"],
    ["opportunities", "build"],
    ["opportunities", "build", "--as-of", "2020-01-31"],
    ["serve"],
    ["ai", "generate"],
    ["app", "init"],
    ["user", "add"],  # story #191, tests/unit/test_auth.py
    ["user", "remove"],
    ["user", "list"],
]
STUB_COMMANDS = [args for args in LEAF_COMMANDS if args not in REAL_COMMANDS]

VALID_YAML = """\
paths:
  raw: data/raw
  bronze: data/bronze
  warehouse: data/warehouse.duckdb
  app_db: data/app.duckdb
asof:
  date: 2020-02-29
"""


def ids(args: list[str]) -> str:
    return " ".join(args)


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A temporary project root with valid settings; the CLI is pointed at it."""
    settings = tmp_path / "config" / "settings.yaml"
    settings.parent.mkdir()
    settings.write_text(VALID_YAML, encoding="utf-8")
    monkeypatch.setattr(config, "DEFAULT_SETTINGS_FILE", settings)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def snapshot(root: Path) -> dict[str, int]:
    return {str(p.relative_to(root)): p.stat().st_size for p in root.rglob("*")}


def leaf_paths(command: object, prefix: tuple[str, ...] = ()) -> Iterator[tuple[str, ...]]:
    # Duck-typed: the group class returned by typer is not always click.Group.
    subcommands = getattr(command, "commands", None)
    if subcommands:
        for name, sub in subcommands.items():
            yield from leaf_paths(sub, (*prefix, name))
    else:
        yield prefix


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the installed `revint` script; decode output as UTF-8 on every OS."""
    script = Path(sys.executable).parent / ("revint.exe" if sys.platform == "win32" else "revint")
    assert script.is_file(), f"entry point script not installed: {script}"
    return subprocess.run(
        [str(script), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        check=False,
    )


# AC1: --help lists the command groups ----------------------------------------


def test_ac1_help_lists_every_command_group(project: Path) -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0, result.output
    for name in GROUPS:
        assert name in result.output, f"'{name}' missing from revint --help"


def test_ac1_registered_commands_match_the_spec(project: Path) -> None:
    registered = {path for path in leaf_paths(typer.main.get_command(app))}
    expected = {
        tuple(a for a in args if not a.startswith("-") and a != "2020-01-31")
        for args in LEAF_COMMANDS
    }
    assert registered == expected


@pytest.mark.parametrize(
    ("group", "subcommands"),
    [
        ("build", ["bronze", "silver", "gold", "all"]),
        ("report", ["dq", "dictionary"]),
        ("opportunities", ["build"]),
        ("backtest", ["run", "report"]),
        ("ai", ["generate"]),
        ("app", ["init"]),
        ("user", ["add", "remove", "list"]),
    ],
)
def test_ac1_group_help_lists_its_subcommands(
    project: Path, group: str, subcommands: list[str]
) -> None:
    result = runner.invoke(app, [group, "--help"])
    assert result.exit_code == 0, result.output
    for name in subcommands:
        assert name in result.output


def test_ac1_opportunities_build_documents_the_as_of_option(project: Path) -> None:
    result = runner.invoke(app, ["opportunities", "build", "--help"])
    assert result.exit_code == 0, result.output
    assert "--as-of" in result.output


def test_ac1_entry_point_is_declared_in_pyproject() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["scripts"]["revint"] == "revint.cli:app"


def test_ac1_installed_script_prints_help() -> None:
    result = run_script("--help")
    assert result.returncode == 0, result.stderr
    for name in GROUPS:
        assert name in result.stdout


# AC2: every stub exits non-zero, says "not implemented", does no work ---------


@pytest.mark.parametrize("args", STUB_COMMANDS, ids=ids)
def test_ac2_stub_exits_non_zero_with_not_implemented_message(
    project: Path, args: list[str]
) -> None:
    result = runner.invoke(app, args)
    assert result.exit_code == 3, result.output
    assert "not implemented" in result.output.lower()
    assert f"revint {args[0]}" in result.output


@pytest.mark.parametrize("args", STUB_COMMANDS, ids=ids)
def test_ac2_stub_creates_no_files_or_databases(project: Path, args: list[str]) -> None:
    before = snapshot(project)
    runner.invoke(app, args)
    assert snapshot(project) == before
    assert not (project / "data").exists()
    assert not list(project.rglob("*.duckdb"))
    assert not list(project.rglob("*.parquet"))


def test_serve_starts_the_api_on_the_configured_address(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # story #134: serve is real; uvicorn is replaced so the test does not start a server
    import uvicorn

    calls: list[dict] = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: calls.append(kw))
    result = runner.invoke(app, ["serve"])
    assert result.exit_code == 0, result.output
    assert calls == [{"host": "127.0.0.1", "port": 8000}]
    assert "http://127.0.0.1:8000/api/v1" in result.output


def test_ac2_real_script_stub_exits_non_zero() -> None:
    # serve was the stub checked here until story #134 made it start the API
    result = run_script("backtest", "run")
    assert result.returncode == 3
    assert "not implemented" in result.stderr.lower()


# AC3: invalid settings fail every command -------------------------------------


# commands that take a name get one, so they reach the settings check (story #191)
WITH_ARGS = [
    a + ["anna"] if a in (["user", "add"], ["user", "remove"]) else a for a in LEAF_COMMANDS
]


@pytest.mark.parametrize("args", WITH_ARGS, ids=ids)
def test_ac3_unknown_settings_key_fails_with_the_validation_error(
    project: Path, args: list[str]
) -> None:
    (project / "config" / "settings.yaml").write_text(
        VALID_YAML + "typo_section:\n  x: 1\n", encoding="utf-8"
    )
    result = runner.invoke(app, args)
    assert result.exit_code == 1, result.output
    assert "typo_section" in result.output
    assert "not implemented" not in result.output.lower()
    assert isinstance(result.exception, SystemExit), "error must be reported, not raised"


def test_ac3_missing_required_key_names_the_key(project: Path) -> None:
    (project / "config" / "settings.yaml").write_text(
        VALID_YAML.replace("  date: 2020-02-29\n", ""), encoding="utf-8"
    )
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 1
    assert "asof.date" in result.output


def test_ac3_missing_settings_file_fails_with_its_path(project: Path) -> None:
    (project / "config" / "settings.yaml").unlink()
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 1
    assert "settings.yaml" in result.output
    assert isinstance(result.exception, SystemExit)


def test_ac3_settings_are_loaded_once_per_invocation(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[Path] = []
    real_load = config.load_settings

    def counting_load(path: Path = config.DEFAULT_SETTINGS_FILE, **kwargs):
        calls.append(path)
        return real_load(path, **kwargs)

    monkeypatch.setattr(config, "load_settings", counting_load)
    runner.invoke(app, ["backtest", "run"])  # a stub; serve would start a server (#134)
    assert len(calls) == 1


def test_ac3_help_does_not_need_valid_settings(project: Path) -> None:
    (project / "config" / "settings.yaml").write_text("not: [valid", encoding="utf-8")
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
