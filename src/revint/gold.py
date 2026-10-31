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


def run_gold(settings: Settings) -> StageResult:
    """Build the gold tables and views from silver; rebuilt in full on every run."""
    _check_silver(settings)
    try:
        return run_stage(GOLD_DIR, settings)
    except PipelineError as exc:
        raise GoldError(str(exc)) from exc
