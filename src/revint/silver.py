"""Build the silver sales table from bronze (spec 01 S1, S2, S10, S11).

The typing itself is SQL (`sql/10_silver`, run in order by `revint.pipeline`). This module
finds the bronze file for the sheet, checks it has the columns the SQL expects, runs the
stage, and checks that silver kept every bronze row. Messages and logs hold counts and
column names, never cell values.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import duckdb
import polars as pl

from revint.config import Settings
from revint.ingest.bronze import LINEAGE_COLUMNS, bronze_filename
from revint.pipeline import PipelineError, StageResult, run_stage

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

_DATES = ("Date", "SCJ_FISCAL_MONTH")
_INTEGERS = ("Year", "Quantity(PCS)", "UOM")
_DECIMALS = (
    "FOB",
    "TOTAL_FOB_IN_AMOUNT",
    "Selling_Price",
    "Selling_Amount",
    "RBD_DISCOUNT_AMOUNT",
    "Change_to_Ctn",
    "PRICE",
    "NET_AMOUNT_1",
    "DISCOUNT_1",
    "AMOUNT_AF_DIS",
    "Discount_2",
    "Net_Amount_2",
    "Back_Margin_3%",
    "Net_AMOUNT_3",
    "CT_5%",
    "TAX_AMOUNT",
    "UnitPrice",
    "Original_price",
    "Diff_Price",
    "Diff_Amount",
    "Discount(%)_1",
    "Discount(%)_2",
    "DiscountAmount",
)

# The type given to a source column; columns not listed here are text. The SQL file
# `02_silver_sales.sql` lists the same columns; a test compares the two.
COLUMN_TYPES: dict[str, str] = {
    **dict.fromkeys(_DATES, "date"),
    **dict.fromkeys(_INTEGERS, "integer"),
    **dict.fromkeys(_DECIMALS, "decimal"),
}


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


def run_silver(settings: Settings) -> SilverResult:
    """Build `silver_sales` in the warehouse from the bronze file.

    Runs the SQL files in `sql/10_silver` in one transaction, then checks that silver holds
    one row per bronze row (S10); if not, the build fails and the change is rolled back.
    """
    bronze = find_bronze_file(settings)
    check_bronze_columns(bronze, settings)
    expected_rows = bronze_row_count(bronze)
    try:
        stage = run_stage(
            SILVER_DIR,
            settings,
            extra_parameters={"bronze_file": bronze.as_posix()},
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
