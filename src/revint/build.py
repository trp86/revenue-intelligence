"""The build commands: `revint build bronze|silver|gold|all` (spec 10 section 5).

Each stage is recorded in `build_log` (story #30), whether it succeeds or fails. `build all`
runs bronze, then silver, then gold, and stops at the first stage that fails. Output holds
counts and file names, never cell values.
"""

from __future__ import annotations

import sys

from revint.build_log import BuildLogError, StageCounts, run_logged
from revint.config import Settings
from revint.gold import GoldError, fact_row_count, run_gold
from revint.ingest.bronze import BronzeResult, execute_bronze
from revint.pipeline import (
    EXIT_STAGE_FAILED,
    EXIT_WAREHOUSE_LOCKED,
    StageResult,
    WarehouseLockedError,
)
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


def execute_gold(settings: Settings) -> int:
    """Build the gold layer from silver and record the run in `build_log`; return an exit code.

    Prints one line with the file, statement and fact row counts. Exit codes: 0 done, 4 the
    stage failed (silver is missing, a column setting is wrong, a failing SQL file), 5 the
    warehouse is in use by another process. Messages hold counts and names, never values.
    """

    def run() -> tuple[StageResult, int]:
        stage = run_gold(settings)
        return stage, fact_row_count(settings)

    try:
        stage, fact_rows = run_logged(
            settings,
            "gold",
            run,
            lambda r: StageCounts(files=len(r[0].files), statements=r[0].statements, rows_out=r[1]),
        )
    except GoldError as exc:
        locked = isinstance(exc.__cause__, WarehouseLockedError)
        print(f"gold failed: {exc}; no changes were made to gold", file=sys.stderr)
        return EXIT_WAREHOUSE_LOCKED if locked else EXIT_STAGE_FAILED
    except BuildLogError as exc:
        print(f"gold was built but {exc}", file=sys.stderr)
        return EXIT_STAGE_FAILED
    print(f"gold: {len(stage.files)} files, {stage.statements} statements, {fact_rows:,} fact rows")
    return 0


def execute_build_all(settings: Settings) -> int:
    """Build every layer: bronze, then silver, then gold. Return an exit code."""
    code = execute_bronze_stage(settings)
    if code:
        print("build all: stopped at the bronze stage", file=sys.stderr)
        return code
    code = execute_silver(settings)
    if code:
        print("build all: stopped at the silver stage", file=sys.stderr)
        return code
    code = execute_gold(settings)
    if code:
        print("build all: stopped at the gold stage", file=sys.stderr)
        return code
    print("build all: bronze, silver and gold built")
    return 0
