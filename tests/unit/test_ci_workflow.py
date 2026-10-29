"""Story #20: CI workflow (spec 10 section 7)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"

EXPECTED_COMMANDS = [
    "uv sync",
    "uv run ruff check .",
    "uv run sqlfluff lint sql",
    'uv run pytest -m "not realdata"',
]


@pytest.fixture(scope="module")
def text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def workflow(text: str) -> dict[str, Any]:
    data = yaml.safe_load(text)
    assert isinstance(data, dict)
    return data


def steps_of(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    jobs = workflow["jobs"]
    assert jobs, "workflow has no jobs"
    return [step for job in jobs.values() for step in job["steps"]]


def run_commands(workflow: dict[str, Any]) -> list[str]:
    return [step["run"].strip() for step in steps_of(workflow) if "run" in step]


# AC1: triggers on PRs and runs the four commands ------------------------------


def test_ac1_workflow_file_exists_and_is_valid_yaml(workflow: dict[str, Any]) -> None:
    assert "jobs" in workflow


def test_ac1_is_started_by_hand_while_no_runner_exists(workflow: dict[str, Any]) -> None:
    # Story #48: the host has no runner, so a pull_request trigger would leave a queued
    # check on every PR. Story #27 restores pull_request once a runner exists; this test
    # and test_gate.py::test_ac4_workflow_triggers_only_on_workflow_dispatch change then.
    # PyYAML (YAML 1.1) reads the bare key `on` as the boolean True.
    triggers = workflow.get("on", workflow.get(True))
    assert triggers is not None, "workflow has no trigger"
    assert set(triggers) == {"workflow_dispatch"}


def test_ac1_runs_the_four_commands_in_order(workflow: dict[str, Any]) -> None:
    commands = run_commands(workflow)
    positions = [commands.index(c) for c in EXPECTED_COMMANDS]
    assert positions == sorted(positions), f"commands out of order: {commands}"


def test_ac1_pytest_excludes_realdata(workflow: dict[str, Any]) -> None:
    pytest_steps = [c for c in run_commands(workflow) if c.startswith("uv run pytest")]
    assert pytest_steps
    for command in pytest_steps:
        assert '-m "not realdata"' in command


def test_ac1_checks_out_the_repo_and_installs_uv(workflow: dict[str, Any]) -> None:
    uses = [step["uses"] for step in steps_of(workflow) if "uses" in step]
    assert any(u.startswith("actions/checkout@") for u in uses)
    assert any(u.startswith("astral-sh/setup-uv@") for u in uses)


def test_ac1_does_not_provide_or_fetch_data(text: str) -> None:
    # data/ is git-ignored, so a checkout has none; nothing may create or download it.
    assert not re.search(r"\bdata/", text)
    assert "REVINT_PATHS_" not in text


def test_ac1_uses_a_standard_hosted_runner(workflow: dict[str, Any]) -> None:
    for name, job in workflow["jobs"].items():
        runs_on = job["runs-on"]
        assert isinstance(runs_on, str), f"job {name}: expected a single runner label"
        assert runs_on.endswith("-latest"), f"job {name}: not a standard runner: {runs_on}"


def test_ac1_actions_are_pinned_to_a_version(workflow: dict[str, Any]) -> None:
    for step in steps_of(workflow):
        if "uses" in step:
            assert re.search(r"@v\d", step["uses"]), f"unpinned action: {step['uses']}"


def test_ac1_least_privilege_permissions(workflow: dict[str, Any]) -> None:
    assert workflow["permissions"] == {"contents": "read"}


# AC2: a failing check fails the job -------------------------------------------
# Shown by a documented local equivalent: the workflow has no way to swallow a
# failure, and each command exits non-zero on a failure (proved in test_tooling.py:
# ruff on an unused import exits 1, sqlfluff on uppercase keywords exits non-zero,
# and a failing pytest test exits 1).


def test_ac2_no_step_or_job_can_ignore_a_failure(text: str, workflow: dict[str, Any]) -> None:
    assert "continue-on-error" not in text
    for command in run_commands(workflow):
        assert "|| true" not in command
        assert "set +e" not in command
        assert not re.search(r";\s*exit\s+0", command)
        assert "&&" not in command, "one command per step so the failing step is named"


def test_ac2_default_shell_fails_fast(workflow: dict[str, Any]) -> None:
    # On the hosted runner `run` steps use bash -e by default (no `shell:` override that
    # would disable that). A pwsh/cmd override is the only way to lose fail-fast here.
    for step in steps_of(workflow):
        shell = step.get("shell")
        assert shell in (None, "bash"), f"unexpected shell override: {shell}"
    assert "defaults" not in workflow


def test_ac2_jobs_are_not_conditional_on_other_results(workflow: dict[str, Any]) -> None:
    for job in workflow["jobs"].values():
        assert "if" not in job
    for step in steps_of(workflow):
        assert "if" not in step, f"conditional step could skip a check: {step}"


# AC3 and AC5: no secrets, no Gemini calls (automated) -------------------------


def test_ac3_workflow_references_no_secrets(text: str) -> None:
    assert "secrets." not in text
    assert "secrets:" not in text
    assert not re.search(r"\$\{\{\s*secrets", text)


def test_ac3_workflow_has_no_gemini_or_api_key_reference(text: str) -> None:
    lowered = text.lower()
    for forbidden in ("gemini", "generativelanguage", "google", "api_key", "api-key", "token"):
        assert forbidden not in lowered, f"unexpected reference: {forbidden}"


def test_ac3_workflow_makes_no_network_calls_of_its_own(workflow: dict[str, Any]) -> None:
    for command in run_commands(workflow):
        assert not re.search(r"\b(curl|wget|Invoke-WebRequest|Invoke-RestMethod)\b", command)
        assert "http://" not in command and "https://" not in command


def test_ac3_no_environment_variables_are_injected(text: str, workflow: dict[str, Any]) -> None:
    assert "env:" not in text
    for job in workflow["jobs"].values():
        assert "env" not in job


def test_ac3_the_test_suite_needs_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # CI provides no GEMINI_API_KEY; settings must still load without one.
    from revint.config import load_settings

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert load_settings(env={}).asof.date.year == 2020
