"""Story #48: local check command `revint-gate` (spec 10 section 7)."""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

from revint import gate

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def ok_step(name: str) -> gate.Step:
    return gate.Step(name, (sys.executable, "-c", "pass"))


def failing_step(name: str, code: int) -> gate.Step:
    return gate.Step(name, (sys.executable, "-c", f"raise SystemExit({code})"))


class Recorder:
    """A stand-in for subprocess.run that records calls and returns set exit codes."""

    def __init__(self, codes: dict[str, int] | None = None) -> None:
        self.codes = codes or {}
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, argv, **kwargs) -> subprocess.CompletedProcess[str]:
        self.calls.append(tuple(argv))
        return subprocess.CompletedProcess(argv, self.codes.get(argv[2], 0))


# AC1: runs ruff, sqlfluff, pytest in CI order, exit 0 when all pass ------------


def test_ac1_steps_are_ruff_sqlfluff_pytest_in_that_order() -> None:
    assert [s.name for s in gate.CHECK_STEPS] == ["ruff", "sqlfluff", "pytest"]
    assert [s.command for s in gate.CHECK_STEPS] == [
        'uv run ruff check .',
        'uv run sqlfluff lint sql',
        'uv run pytest -m "not realdata"',
    ]


def test_ac1_pytest_step_excludes_realdata() -> None:
    pytest_step = next(s for s in gate.CHECK_STEPS if s.name == "pytest")
    assert pytest_step.argv[-2:] == ("-m", "not realdata")


def test_ac1_all_steps_pass_gives_exit_zero_and_runs_in_order(
    capsys: pytest.CaptureFixture[str],
) -> None:
    runner = Recorder()
    code = gate.run_gate(gate.CHECK_STEPS, runner=runner)
    assert code == 0
    assert [call[:3] for call in runner.calls] == [
        ("uv", "run", "ruff"),
        ("uv", "run", "sqlfluff"),
        ("uv", "run", "pytest"),
    ]
    out = capsys.readouterr().out
    assert "ruff" in out and "sqlfluff" in out and "pytest" in out
    assert "gate: all 3 checks passed" in out


def test_ac1_steps_run_from_the_project_root() -> None:
    seen: list[object] = []

    def runner(argv, **kwargs):
        seen.append(kwargs.get("cwd"))
        return subprocess.CompletedProcess(argv, 0)

    gate.run_gate([ok_step("a")], runner=runner)
    assert seen == [gate.PROJECT_ROOT]


def test_ac1_main_runs_the_real_step_list(monkeypatch: pytest.MonkeyPatch) -> None:
    # The runner is replaced, so this never starts ruff, sqlfluff or pytest itself
    # (the real gate runs pytest, which would run this test again).
    runner = Recorder()
    monkeypatch.setattr(gate.subprocess, "run", runner)
    assert gate.main() == 0
    assert [call[2] for call in runner.calls] == ["ruff", "sqlfluff", "pytest"]


# AC2: stops at the failing step, names it, exits non-zero ---------------------


def test_ac2_failing_step_stops_the_run_and_names_the_step(
    capsys: pytest.CaptureFixture[str],
) -> None:
    runner = Recorder({"sqlfluff": 1})
    code = gate.run_gate(gate.CHECK_STEPS, runner=runner)
    assert code != 0
    assert [call[2] for call in runner.calls] == ["ruff", "sqlfluff"], "pytest must not run"
    out = capsys.readouterr().out
    assert "gate: step 'sqlfluff' failed" in out
    assert "uv run sqlfluff lint sql" in out


def test_ac2_exit_code_is_the_failing_steps_code(capsys: pytest.CaptureFixture[str]) -> None:
    steps = [ok_step("first"), failing_step("second", 7), ok_step("third")]
    assert gate.run_gate(steps) == 7
    assert "gate: step 'second' failed (exit 7)" in capsys.readouterr().out


def test_ac2_first_step_failing_skips_all_later_steps(
    capsys: pytest.CaptureFixture[str],
) -> None:
    runner = Recorder({"ruff": 1})
    assert gate.run_gate(gate.CHECK_STEPS, runner=runner) == 1
    assert len(runner.calls) == 1
    assert "gate: step 'ruff' failed" in capsys.readouterr().out


def test_ac2_missing_tool_gives_a_clear_message_and_non_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def runner(argv, **kwargs):
        raise FileNotFoundError(argv[0])

    assert gate.run_gate(gate.CHECK_STEPS, runner=runner) != 0
    out = capsys.readouterr().out
    assert "gate: step 'ruff' could not start" in out
    assert "uv" in out


def test_ac2_a_failing_exit_code_never_becomes_zero(capsys: pytest.CaptureFixture[str]) -> None:
    runner = Recorder({"ruff": 256})  # code that would truncate to 0 on some platforms
    assert gate.run_gate(gate.CHECK_STEPS, runner=runner) != 0


def test_ac2_real_subprocess_failure_is_reported(capsys: pytest.CaptureFixture[str]) -> None:
    code = gate.run_gate([ok_step("one"), failing_step("two", 3)])
    assert code == 3
    assert "step 'two' failed" in capsys.readouterr().out


# Entry point -------------------------------------------------------------------


def test_entry_point_is_declared_and_not_revint_check() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = pyproject["project"]["scripts"]
    assert scripts["revint-gate"] == "revint.gate:main"
    assert scripts["revint"] == "revint.cli:app"


def test_installed_script_exists() -> None:
    name = "revint-gate.exe" if sys.platform == "win32" else "revint-gate"
    script = Path(sys.executable).parent / name
    assert script.is_file(), f"entry point script not installed: {script}"


# AC3: ci.yml and the local command share one command list ----------------------


def workflow_commands() -> list[str]:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return [
        step["run"].strip()
        for job in data["jobs"].values()
        for step in job["steps"]
        if "run" in step
    ]


def test_ac3_ci_runs_uv_sync_then_exactly_the_gate_commands() -> None:
    commands = workflow_commands()
    assert commands[0] == "uv sync"
    assert commands[1:] == [s.command for s in gate.CHECK_STEPS]


def test_ac3_step_command_text_matches_its_argv() -> None:
    for step in gate.CHECK_STEPS:
        assert step.command == gate.render(step.argv)


@pytest.mark.parametrize(
    ("argv", "text"),
    [
        (("uv", "run", "ruff", "check", "."), "uv run ruff check ."),
        (("uv", "run", "pytest", "-m", "not realdata"), 'uv run pytest -m "not realdata"'),
    ],
)
def test_ac3_render_quotes_only_arguments_with_spaces(argv: tuple[str, ...], text: str) -> None:
    assert gate.render(argv) == text


# AC4: ci.yml is manual-only but still runs the commands ------------------------


def test_ac4_workflow_triggers_only_on_workflow_dispatch() -> None:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    # PyYAML (YAML 1.1) reads the bare key `on` as the boolean True.
    triggers = data.get("on", data.get(True))
    assert triggers is not None
    assert set(triggers) == {"workflow_dispatch"}
    assert "pull_request" not in triggers
    assert "push" not in triggers


def test_ac4_workflow_still_runs_the_same_four_commands() -> None:
    assert workflow_commands() == ["uv sync", *[s.command for s in gate.CHECK_STEPS]]


# AC5: process doc states the rule ----------------------------------------------


def process_text() -> str:
    return (ROOT / "docs" / "process.md").read_text(encoding="utf-8")


def test_ac5_process_doc_names_the_local_command_as_evidence() -> None:
    text = process_text()
    assert "uv run revint-gate" in text
    assert "no runner" in text.lower()


def test_ac5_process_doc_requires_the_evidence_comment_to_state_it_was_run() -> None:
    text = process_text().lower()
    assert "evidence comment" in text
    assert "states" in text and "revint-gate" in text


def test_ac5_definition_of_done_points_at_the_local_command() -> None:
    done = process_text().split("## Definition of Done")[1].split("## Claude Code workflow")[0]
    assert "revint-gate" in done
