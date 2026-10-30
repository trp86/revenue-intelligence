"""Helpers shared by the silver tests: a synthetic bronze file and queries on the warehouse.

Synthetic data only. Not a test module (pytest does not collect it).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import duckdb
import polars as pl

from revint.config import Settings, load_settings
from revint.ingest.bronze import LINEAGE_COLUMNS
from revint.pipeline import StageResult, run_stage
from revint.silver import SILVER_DIR, run_silver

# The silver SQL names the real 75 columns, so the synthetic bronze file has all of them.
EXPECTED = load_settings(env={}).ingest.expected_columns
SIX_AMOUNTS = [
    "Selling_Amount",
    "NET_AMOUNT_1",
    "AMOUNT_AF_DIS",
    "Net_Amount_2",
    "Net_AMOUNT_3",
    "TAX_AMOUNT",
]
COLUMN_TYPES_SQL = (
    "select column_name, data_type from information_schema.columns "
    "where table_name = 'silver_sales'"
)


def bronze_row(source_row: int, **cells: str | None) -> dict[str, str | None]:
    base: dict[str, str | None] = dict.fromkeys(EXPECTED)
    base.update(cells)
    return {
        **base,
        "_source_file": "sales.xlsx",
        "_sheet": "RAW SCJ SALES",
        "_source_row": str(source_row),
        "_ingested_at": "2026-10-30T09:00:00Z",
        "_file_hash": "h" * 64,
    }


def write_bronze(settings: Settings, rows: list[dict[str, str | None]]) -> Path:
    settings.paths.bronze.mkdir(parents=True, exist_ok=True)
    target = settings.paths.bronze / "sales__RAW_SCJ_SALES.parquet"
    columns = [*EXPECTED, *LINEAGE_COLUMNS]
    pl.DataFrame(
        {c: [r.get(c) for r in rows] for c in columns}, schema=dict.fromkeys(columns, pl.String)
    ).write_parquet(target)
    return target


def query(settings: Settings, sql: str, *args: Any) -> list[tuple[Any, ...]]:
    con = duckdb.connect(str(settings.paths.warehouse), read_only=True)
    try:
        return con.execute(sql, list(args)).fetchall()
    finally:
        con.close()


def build(settings: Settings, rows: list[dict[str, str | None]]) -> None:
    write_bronze(settings, rows)
    run_silver(settings)


def one(settings: Settings, column: str, source_row: int = 8) -> Any:
    return query(
        settings, f'select "{column}" from silver_sales where _source_row = ?', source_row
    )[0][0]


def audit_table_sql() -> str:
    """The statement in 06_excluded_rows.sql that builds silver_excluded_rows.

    A test that forces a row into an excluded state runs this afterwards, as the real stage
    does, so the audit table matches silver again.
    """
    return (SILVER_DIR / "06_excluded_rows.sql").read_text(encoding="utf-8")


def force_exact_duplicate_sql(source_row: int) -> str:
    """SQL that marks one row as an exact duplicate, as 04_duplicates.sql does for a real one.

    Used to reach a state the data does not contain, and to see whether the checks catch a
    broken one.
    """
    return (
        "update silver_sales set is_excluded = true, exclusion_reason = 'exact_duplicate', "
        f"is_duplicate = true where _source_row = {source_row};"
    )


def run_custom_stage(
    settings: Settings,
    rows: list[dict[str, str | None]],
    stage_dir: Path,
    extra_files: dict[str, str] | None = None,
    skip: tuple[str, ...] = (),
) -> StageResult:
    """Run a copy of the real silver stage with extra SQL files added (or some left out).

    Used to put a chosen row into a state the real rules cannot produce yet, for example an
    exact duplicate, and to see whether the checks catch a broken state.
    """
    bronze = write_bronze(settings, rows)
    stage_dir.mkdir(parents=True, exist_ok=True)
    for path in SILVER_DIR.glob("*.sql"):
        if path.name not in skip:
            shutil.copy(path, stage_dir / path.name)
    for name, text in (extra_files or {}).items():
        (stage_dir / name).write_text(text, encoding="utf-8")
    return run_stage(stage_dir, settings, extra_parameters={"bronze_file": bronze.as_posix()})
