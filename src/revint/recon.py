"""Reconciliation checks R1 to R4 (spec 01 section 6).

The checks are SQL files in `sql/checks`, run in order by `revint.pipeline` in one
transaction; they write `recon_results` to the warehouse. The one number SQL cannot get is the
count of data rows in the Excel sheet (R1), so this module reads it straight from the workbook
and passes it in as `$excel_rows`.

A failed check does not stop the run: every check is written, and the outcome says whether
all passed. Messages, logs and the table hold counts and sums, never cell values.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import duckdb
import polars as pl

from revint.config import Settings
from revint.ingest.excel import find_workbook, read_sheet
from revint.ingest.header import HeaderError, detect_header_from_settings
from revint.ingest.raw import RawAccessError, open_raw
from revint.pipeline import PipelineError, WarehouseLockedError, run_stage
from revint.silver import SilverError, find_bronze_file

logger = logging.getLogger(__name__)

RECON_DIR = Path(__file__).resolve().parents[2] / "sql" / "checks"
EXIT_CHECK_FAILED = 7
EXIT_RECON_FAILED = 4
EXIT_WAREHOUSE_LOCKED = 5


class ReconError(Exception):
    """The reconciliation could not be run (not the same as a check that failed)."""


@dataclass(frozen=True)
class ReconResult:
    check_id: str
    subject: str
    description: str
    status: str  # pass | fail | info
    expected: Decimal | None
    actual: Decimal | None
    difference: Decimal | None
    tolerance: float | None
    detail: str | None


@dataclass(frozen=True)
class ReconOutcome:
    results: tuple[ReconResult, ...]

    @property
    def passed(self) -> bool:
        return all(r.status != "fail" for r in self.results)

    @property
    def failed(self) -> tuple[ReconResult, ...]:
        return tuple(r for r in self.results if r.status == "fail")


def excel_data_rows(settings: Settings) -> int:
    """Data rows in the first configured sheet: from the row under the header to the last
    row that holds any value. Blank rows between data rows count; trailing blanks do not.

    Read straight from the workbook (read-only), not from bronze, so R1 compares two
    independent counts.
    """
    sheet_name = settings.ingest.sheets[0]
    raw_dir = settings.paths.raw
    try:
        workbook = find_workbook(raw_dir, sheet_name)
        with open_raw(Path(workbook.name), raw_dir) as handle:
            data = handle.read()
        sheet = read_sheet(data, sheet_name)
        info = detect_header_from_settings(sheet, settings)
    except (ValueError, HeaderError, RawAccessError, OSError) as exc:
        raise ReconError(
            f"R1 cannot count the Excel rows: workbook for sheet '{sheet_name}' in {raw_dir}: {exc}"
        ) from exc
    body = sheet.frame.slice(info.header_row - sheet.first_row + 1)
    if body.height == 0:
        return 0
    filled = body.select(
        pl.any_horizontal([pl.col(c).is_not_null() & (pl.col(c) != "") for c in body.columns])
    ).to_series()
    last = filled.arg_true()
    return int(last.max()) + 1 if len(last) else 0


def _check_warehouse(settings: Settings) -> None:
    warehouse = settings.paths.warehouse
    if not warehouse.is_file():
        raise ReconError(
            f"warehouse not found: {warehouse}; build bronze and silver before the checks"
        )
    try:
        con = duckdb.connect(str(warehouse), read_only=True)
    except duckdb.IOException as exc:
        raise WarehouseLockedError(
            f"the warehouse {warehouse} is in use by another process; "
            "stop it and run the checks again"
        ) from exc
    try:
        missing = [
            t
            for t in ("silver_sales", "silver_excluded_rows")
            if not con.execute(
                "select count(*) from information_schema.tables where table_name = ?", [t]
            ).fetchone()[0]
        ]
    finally:
        con.close()
    if missing:
        raise ReconError(
            f"the warehouse has no table {', '.join(missing)}; build silver before the checks"
        )


def _read_results(settings: Settings) -> tuple[ReconResult, ...]:
    con = duckdb.connect(str(settings.paths.warehouse), read_only=True)
    try:
        rows = con.execute(
            "select check_id, subject, description, status, expected, actual, difference, "
            "tolerance, detail from recon_results order by check_id, subject"
        ).fetchall()
    finally:
        con.close()
    return tuple(ReconResult(*row) for row in rows)


def run_recon(settings: Settings) -> ReconOutcome:
    """Run the checks in `sql/checks` and return what `recon_results` now holds.

    Raises `ReconError` when the checks cannot run (no warehouse, no silver, no workbook, a
    failing SQL file); a check that fails is a result, not an error.
    """
    _check_warehouse(settings)
    excel_rows = excel_data_rows(settings)
    try:
        bronze = find_bronze_file(settings)
    except SilverError as exc:
        raise ReconError(str(exc)) from exc
    try:
        run_stage(
            RECON_DIR,
            settings,
            extra_parameters={"bronze_file": bronze.as_posix(), "excel_rows": excel_rows},
        )
    except WarehouseLockedError:
        raise
    except PipelineError as exc:
        raise ReconError(str(exc)) from exc
    results = _read_results(settings)
    outcome = ReconOutcome(results)
    logger.info("recon: %d results, %d failed", len(results), len(outcome.failed))
    return outcome


def _format(result: ReconResult) -> str:
    parts = []
    for label, value in (
        ("expected", result.expected),
        ("actual", result.actual),
        ("difference", result.difference),
    ):
        if value is not None:
            parts.append(f"{label} {value:,}")
    if result.detail:
        parts.append(result.detail)
    tail = f" ({', '.join(parts)})" if parts else ""
    return f"{result.check_id} {result.subject}: {result.status}{tail}"


def execute_recon(settings: Settings) -> int:
    """Run the checks for the command line: print every result, return an exit code."""
    try:
        outcome = run_recon(settings)
    except WarehouseLockedError as exc:
        print(f"check: {exc}", file=sys.stderr)
        return EXIT_WAREHOUSE_LOCKED
    except ReconError as exc:
        print(f"check failed: {exc}", file=sys.stderr)
        return EXIT_RECON_FAILED
    for result in outcome.results:
        print(_format(result))
    failed = len(outcome.failed)
    if failed:
        print(f"check: {failed} of {len(outcome.results)} results failed", file=sys.stderr)
        return EXIT_CHECK_FAILED
    print(f"check: {len(outcome.results)} results, none failed")
    return 0
