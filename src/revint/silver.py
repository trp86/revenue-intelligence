"""Build the silver sales table from bronze (spec 01 S1, S2, S10, S11).

The typing itself is SQL (`sql/10_silver`, run in order by `revint.pipeline`). This module
finds the bronze file for the sheet, checks it has the columns the SQL expects, runs the
stage, and checks that silver kept every bronze row. Messages and logs hold counts and
column names, never cell values.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from pathlib import Path

import duckdb
import polars as pl

from revint.build_log import BuildLogError, StageCounts, run_logged
from revint.config import Settings
from revint.ingest.bronze import LINEAGE_COLUMNS, bronze_filename
from revint.pipeline import (
    EXIT_STAGE_FAILED,
    EXIT_WAREHOUSE_LOCKED,
    PipelineError,
    StageResult,
    WarehouseLockedError,
    run_stage,
)
from revint.silver_schema import COLUMN_TYPES

logger = logging.getLogger(__name__)

SILVER_DIR = Path(__file__).resolve().parents[2] / "sql" / "10_silver"

# S11: the six candidate amount columns, all typed and kept. Which one is net sales is
# decided in the gold layer (spec 02); the net sales field must be one of these.
AMOUNT_COLUMNS = (
    "Selling_Amount",
    "NET_AMOUNT_1",
    "AMOUNT_AF_DIS",
    "Net_Amount_2",
    "Net_AMOUNT_3",
    "TAX_AMOUNT",
)

# S10: the only reasons for which silver marks a row as excluded. `99_checks.sql` fails the
# stage if any other reason appears; a test compares this tuple with that file.
ALLOWED_EXCLUSION_REASONS = ("stray_row", "exact_duplicate")


class SilverError(Exception):
    """The silver build could not be completed."""


@dataclass(frozen=True)
class SilverResult:
    rows: int
    bronze_file: str
    stage: StageResult


def column_type(name: str) -> str:
    return COLUMN_TYPES.get(name, "text")


def bronze_row_count(path: Path) -> int:
    """Rows in the bronze Parquet file, read from its metadata."""
    return int(pl.scan_parquet(path).select(pl.len()).collect().item())


def find_bronze_file(settings: Settings) -> Path:
    """The one bronze file for the configured sheet (`<source>__<sheet>.parquet`)."""
    sheet = settings.ingest.sheets[0]
    suffix = "__" + bronze_filename("x", sheet).split("__", 1)[1]
    found = (
        sorted(settings.paths.bronze.glob(f"*{suffix}")) if settings.paths.bronze.is_dir() else []
    )
    if not found:
        raise SilverError(
            f"bronze file not found for sheet '{sheet}' in {settings.paths.bronze}; "
            "run `uv run revint build bronze` first"
        )
    if len(found) > 1:
        names = ", ".join(p.name for p in found)
        raise SilverError(f"more than one bronze file for sheet '{sheet}': {names}")
    return found[0]


def check_bronze_columns(path: Path, settings: Settings) -> None:
    """The bronze file must hold exactly the expected source columns plus the lineage columns."""
    actual = pl.read_parquet_schema(path)
    expected = [*settings.ingest.expected_columns, *LINEAGE_COLUMNS]
    missing = [c for c in expected if c not in actual]
    extra = [c for c in actual if c not in expected]
    if missing:
        raise SilverError(f"bronze file lacks columns: {', '.join(missing)}")
    if extra:
        raise SilverError(f"bronze file has unexpected columns: {', '.join(extra)}")


def check_duplicate_key_columns(path: Path, settings: Settings) -> None:
    """The columns that define an exact duplicate must exist in the bronze file (S5).

    The SQL selects them by name and would silently ignore a name that is not there, which
    would make rows look more alike than they are. An empty list is refused for the same
    reason: every row would be a duplicate of the first.
    """
    keys = settings.duplicate_key_columns
    if not keys:
        raise SilverError(
            "duplicates.key_columns is empty and ingest.expected_columns gives no columns "
            "to compare; exact duplicates cannot be detected"
        )
    actual = pl.read_parquet_schema(path)
    missing = [c for c in keys if c not in actual]
    if missing:
        raise SilverError(
            f"duplicates.key_columns names columns that are not in the bronze file: "
            f"{', '.join(missing)}"
        )


def check_value_flag_columns(settings: Settings) -> None:
    """The columns the value flags read must be typed numbers (S7, S8).

    A text column cannot be tested for zero or below, so naming one in config fails the build
    with the key name, before the SQL would fail with a type error.
    """
    net = settings.net_sales
    not_numeric = [c for c in net.candidate_columns if column_type(c) not in {"decimal", "integer"}]
    if not_numeric:
        raise SilverError(
            "net_sales.candidate_columns names columns that silver does not type as numbers: "
            + ", ".join(not_numeric)
        )
    if column_type(net.quantity_field) not in {"decimal", "integer"}:
        raise SilverError(
            f"net_sales.quantity_field '{net.quantity_field}' is not a typed number "
            "column in silver"
        )


def check_label_columns(settings: Settings) -> None:
    """The columns the label rule reads must be text, and no column may be in both lists (S3).

    A typed column (a date or a number) has no label to map, and a column in both lists would
    get one twin column built twice. Either fails the build with the key name.
    """
    labels = settings.labels
    for role in ("channel_columns", "branch_columns"):
        typed = [c for c in getattr(labels, role) if column_type(c) != "text"]
        if typed:
            raise SilverError(
                f"labels.{role} names columns that silver types and so cannot hold labels: "
                + ", ".join(typed)
            )
    both = sorted(set(labels.channel_columns) & set(labels.branch_columns))
    if both:
        raise SilverError(
            "labels.channel_columns and labels.branch_columns both name: " + ", ".join(both)
        )


def silver_stage_parameters(bronze: Path) -> dict[str, object]:
    """The extra SQL parameters the silver stage needs beyond `Settings`.

    `bronze_file` is the bronze Parquet file. `dq_decimal_columns` lists the decimal columns
    and `dq_decimal_raw_columns` their `<column>_raw` twins, in the same order, so the quality
    SQL can find rows where rounding to four decimals changed a value (rule S1) without naming
    any column itself.
    """
    decimals = [name for name, kind in COLUMN_TYPES.items() if kind == "decimal"]
    return {
        "bronze_file": bronze.as_posix(),
        "dq_decimal_columns": decimals,
        "dq_decimal_raw_columns": [f"{name}_raw" for name in decimals],
    }


def run_silver(settings: Settings) -> SilverResult:
    """Build `silver_sales` in the warehouse from the bronze file.

    Runs the SQL files in `sql/10_silver` in one transaction, then checks that silver holds
    one row per bronze row (S10); if not, the build fails and the change is rolled back.
    """
    bronze = find_bronze_file(settings)
    check_bronze_columns(bronze, settings)
    check_duplicate_key_columns(bronze, settings)
    check_value_flag_columns(settings)
    check_label_columns(settings)
    expected_rows = bronze_row_count(bronze)
    try:
        stage = run_stage(
            SILVER_DIR,
            settings,
            extra_parameters=silver_stage_parameters(bronze),
        )
    except PipelineError as exc:
        raise SilverError(str(exc)) from exc
    con = duckdb.connect(str(settings.paths.warehouse), read_only=True)
    try:
        silver_rows = int(con.execute("select count(*) from silver_sales").fetchone()[0])
    finally:
        con.close()
    if silver_rows != expected_rows:
        raise SilverError(
            f"silver row count {silver_rows:,} does not match bronze row count {expected_rows:,}"
        )
    logger.info("silver_sales: %d rows, %d statements", silver_rows, stage.statements)
    return SilverResult(rows=silver_rows, bronze_file=bronze.name, stage=stage)


def execute_silver(settings: Settings) -> int:
    """Build silver for the command line and record the run in `build_log`.

    Prints one line with the file, statement and row counts and returns an exit code: 0 done,
    4 the build failed (a missing bronze file, a bad column, a failing SQL file), 5 the
    warehouse is in use by another process. Messages hold counts and names, never values.
    """
    try:
        result = run_logged(
            settings,
            "silver",
            lambda: run_silver(settings),
            lambda r: StageCounts(
                files=len(r.stage.files), statements=r.stage.statements, rows_out=r.rows
            ),
        )
    except SilverError as exc:
        locked = isinstance(exc.__cause__, WarehouseLockedError)
        print(f"silver failed: {exc}; no changes were made to silver", file=sys.stderr)
        return EXIT_WAREHOUSE_LOCKED if locked else EXIT_STAGE_FAILED
    except BuildLogError as exc:
        print(f"silver was built but {exc}", file=sys.stderr)
        return EXIT_STAGE_FAILED
    print(
        f"silver: {len(result.stage.files)} files, {result.stage.statements} statements, "
        f"{result.rows:,} rows from {result.bronze_file}"
    )
    return 0
