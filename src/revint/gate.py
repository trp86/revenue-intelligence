"""Local check gate: the same checks as .github/workflows/ci.yml, run by hand.

While the host has no CI runner, a passing `uv run revint-gate` is the evidence
of green checks (docs/process.md). CHECK_STEPS is the single list of checks;
tests/unit/test_gate.py asserts the workflow runs exactly these commands.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def render(argv: Sequence[str]) -> str:
    """The command as a person would type it: arguments with spaces are quoted."""
    return " ".join(f'"{a}"' if " " in a else a for a in argv)


@dataclass(frozen=True)
class Step:
    name: str
    argv: tuple[str, ...]

    @property
    def command(self) -> str:
        return render(self.argv)


# Order matches the steps in .github/workflows/ci.yml (after `uv sync`).
CHECK_STEPS: tuple[Step, ...] = (
    Step("ruff", ("uv", "run", "ruff", "check", ".")),
    Step("sqlfluff", ("uv", "run", "sqlfluff", "lint", "sql")),
    Step("pytest", ("uv", "run", "pytest", "-m", "not realdata")),
)

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


def run_gate(steps: Sequence[Step] = CHECK_STEPS, runner: Runner | None = None) -> int:
    """Run the steps in order and stop at the first failure.

    Returns 0 when every step passes, otherwise the failing step's exit code
    (never 0 for a failure). `runner` defaults to `subprocess.run`, looked up at
    call time so tests can replace it.
    """
    runner = runner or subprocess.run
    for number, step in enumerate(steps, start=1):
        print(f"gate: [{number}/{len(steps)}] {step.name}: {step.command}", flush=True)
        try:
            result = runner(list(step.argv), cwd=PROJECT_ROOT, check=False)
        except FileNotFoundError as exc:
            print(f"gate: step '{step.name}' could not start: {exc.args[0]} not found")
            return 127
        if result.returncode != 0:
            code = result.returncode if result.returncode % 256 else 1
            print(f"gate: step '{step.name}' failed (exit {result.returncode}): {step.command}")
            return code
    print(f"gate: all {len(steps)} checks passed")
    return 0


def main() -> int:
    return run_gate()


if __name__ == "__main__":
    sys.exit(main())
