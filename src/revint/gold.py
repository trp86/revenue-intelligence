"""Run the gold stage: the numbered SQL files in `sql/20_gold` (spec 02).

Gold is built from the silver tables in the warehouse file. This module checks that silver
exists and runs the stage with `revint.pipeline` (one transaction, stop on the failing file).
The command line (`revint build gold`) and the build log are wired in story #87; the SQL files
arrive one story at a time (net sales view, dimensions, fact, marts).
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb

from revint.config import Settings
from revint.pipeline import PipelineError, StageResult, run_stage
from revint.silver_schema import COLUMN_TYPES, SILVER_FLAG_COLUMNS

logger = logging.getLogger(__name__)

GOLD_DIR = Path(__file__).resolve().parents[2] / "sql" / "20_gold"
_REQUIRED_TABLES = ("silver_sales", "silver_excluded_rows")


class GoldError(Exception):
    """The gold stage could not be run."""


def _check_silver(settings: Settings) -> None:
    warehouse = settings.paths.warehouse
    if not warehouse.is_file():
        raise GoldError(f"warehouse not found: {warehouse}; run `uv run revint build silver` first")
    try:
        con = duckdb.connect(str(warehouse), read_only=True)
    except duckdb.Error as exc:
        raise GoldError(f"cannot open the warehouse: {type(exc).__name__}") from exc
    try:
        present = {
            name
            for (name,) in con.execute(
                "select table_name from information_schema.tables"
            ).fetchall()
        }
    finally:
        con.close()
    missing = [name for name in _REQUIRED_TABLES if name not in present]
    if missing:
        raise GoldError(
            f"the warehouse has no table {', '.join(missing)}; "
            "run `uv run revint build silver` first"
        )


def _check_columns(settings: Settings) -> None:
    """Column names that gold reads by name must be the right kind of silver column."""
    date_column = settings.calendar.date_column
    if COLUMN_TYPES.get(date_column) != "date":
        raise GoldError(
            f"calendar.date_column '{date_column}' is not a date column that silver types"
        )
    branch_columns = settings.labels.branch_columns
    if len(branch_columns) != 1:
        raise GoldError(
            "labels.branch_columns must name exactly one column for dim_branch, "
            f"not {len(branch_columns)}"
        )
    channel_columns = settings.labels.channel_columns
    if len(channel_columns) != 1:
        raise GoldError(
            "labels.channel_columns must name exactly one column for dim_customer, "
            f"not {len(channel_columns)}"
        )
    for key, column in (
        ("customers.code_column", settings.customers.code_column),
        ("customers.name_column", settings.customers.name_column),
    ):
        if COLUMN_TYPES.get(column, "text") != "text":
            raise GoldError(f"{key} '{column}' is a typed column; it must be text")
    for key in ("code_column", "name_column", "brand_column", "category_column"):
        column = getattr(settings.product, key)
        if COLUMN_TYPES.get(column, "text") != "text":
            raise GoldError(f"product.{key} '{column}' is a typed column; it must be text")
    for column in settings.peer_groups.columns:
        if COLUMN_TYPES.get(column, "text") != "text":
            raise GoldError(
                f"peer_groups.columns names '{column}', a typed column; a peer key must be text"
            )
    region_column = settings.regions.source_column
    if COLUMN_TYPES.get(region_column, "text") != "text":
        raise GoldError(
            f"regions.source_column '{region_column}' is a typed column; a region is text"
        )


def gold_stage_parameters() -> dict[str, object]:
    """The extra SQL parameters the gold stage needs beyond `Settings`.

    `silver_flag_columns` lists the silver flag columns, so the fact can carry every flag
    without the SQL naming any of them.
    """
    return {"silver_flag_columns": list(SILVER_FLAG_COLUMNS)}


def run_gold(settings: Settings) -> StageResult:
    """Build the gold tables and views from silver; rebuilt in full on every run."""
    _check_silver(settings)
    _check_columns(settings)
    try:
        return run_stage(GOLD_DIR, settings, extra_parameters=gold_stage_parameters())
    except PipelineError as exc:
        raise GoldError(str(exc)) from exc
