"""The build commands: `revint build bronze|silver|all` (spec 10 section 5).

Each stage is recorded in `build_log` (story #30), whether it succeeds or fails. `build all`
runs bronze, then silver, and stops at the first stage that fails. There is no gold stage yet
(epic E2), and the command says so. Output holds counts and file names, never cell values.
"""

from __future__ import annotations

import sys

from revint.build_log import BuildLogError, StageCounts, run_logged
from revint.config import Settings
from revint.ingest.bronze import BronzeResult, execute_bronze
from revint.pipeline import EXIT_STAGE_FAILED
from revint.silver import execute_silver


class _StageExit(Exception):
    """A stage ended with a non-zero exit code (its own message is already printed)."""

    def __init__(self, code: int) -> None:
        super().__init__(f"exit code {code}")
        self.code = code


def _bronze_counts(results: list[BronzeResult]) -> StageCounts:
    sheets = [sheet for result in results for sheet in result.sheets]
    if not sheets:
        return StageCounts()
    return StageCounts(files=len(sheets), rows_out=sum(s.data_rows for s in sheets))


def execute_bronze_stage(settings: Settings) -> int:
    """Run the bronze build and record it in `build_log`; return an exit code."""
    sink: list[BronzeResult] = []

    def run() -> list[BronzeResult]:
        code = execute_bronze(settings, None, sink)
        if code:
            raise _StageExit(code)
        return sink

    try:
        run_logged(settings, "bronze", run, _bronze_counts)
    except _StageExit as stop:
        return stop.code
    except BuildLogError as exc:
        print(f"bronze was built but {exc}", file=sys.stderr)
        return EXIT_STAGE_FAILED
    return 0


def execute_build_all(settings: Settings) -> int:
    """Build every layer that exists: bronze, then silver. Return an exit code."""
    code = execute_bronze_stage(settings)
    if code:
        print("build all: stopped at the bronze stage", file=sys.stderr)
        return code
    code = execute_silver(settings)
    if code:
        print("build all: stopped at the silver stage", file=sys.stderr)
        return code
    print("build all: bronze and silver built; no gold stage exists yet")
    return 0
