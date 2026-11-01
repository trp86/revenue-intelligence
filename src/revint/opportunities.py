"""The opportunity engines (spec 03): as-of inputs, the opportunity schema and run summary, and
the engines in later stories.

Engines read only the as-of inputs, never the all-data marts. `mart_customer_profile` and
`mart_peer_category_share` hold values computed over every sale up to the data's last day, so an
engine run for an earlier as-of date would see the future through them. The inputs repeat the
marts' logic with one difference: only sales lines dated on or before the as-of date count. At the
last day of the data they equal the marts, which a test checks (story #106).

The as-of date is `asof.date`; `with_asof` gives a copy of the settings with another date for one
run, without editing the config file. Messages and logs hold counts, never a cell value.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date as Date
from pathlib import Path

import duckdb

from revint.config import Settings
from revint.pipeline import PipelineError, StageResult, run_stage

logger = logging.getLogger(__name__)

OPPORTUNITIES_DIR = Path(__file__).resolve().parents[2] / "sql" / "30_opportunities"
ASOF_INPUT_TABLES = (
    "asof_orders",
    "asof_customer_month",
    "asof_customer_category_month",
    "asof_customer_profile",
    "asof_peer_category_share",
)
_REQUIRED_TABLES = ("fact_sales", "v_net_sales", "dim_date", "dim_product")

# The four engines of spec 03. Each stores its algo_version (opp_engines in 02_schema.sql).
ENGINES = ("dormancy", "recovery", "whitespace", "crosssell")

# The columns of opp_opportunities, the unified and ranked table (spec 03 section 2).
OPPORTUNITY_COLUMNS = (
    "opp_id",
    "type",
    "customer_key",
    "category",
    "as_of_date",
    "algo_version",
    "score",
    "priority",
    "confidence",
    "value_low",
    "value_high",
    "value_level",
    "value_method",
    "rank",
    "reason_codes",
)


def opp_id(type_: str, customer_key: int, category: str | None, as_of: Date) -> str:
    """The opportunity id, as the SQL macro opp_id makes it: md5 of a JSON list of the four
    values (a NULL category is JSON null, so it differs from an empty one)."""
    values = [type_, str(customer_key), category, as_of.isoformat()]
    return hashlib.md5(json.dumps(values, separators=(",", ":")).encode("utf-8")).hexdigest()


class OpportunitiesError(Exception):
    """The opportunity stage could not be run."""


def with_asof(settings: Settings, as_of: Date) -> Settings:
    """A copy of the settings with another as-of date; the original is not changed."""
    return settings.model_copy(update={"asof": settings.asof.model_copy(update={"date": as_of})})


def _check_gold(settings: Settings) -> None:
    warehouse = settings.paths.warehouse
    if not warehouse.is_file():
        raise OpportunitiesError(
            f"warehouse not found: {warehouse}; run `uv run revint build gold` first"
        )
    try:
        con = duckdb.connect(str(warehouse), read_only=True)
    except duckdb.Error as exc:
        raise OpportunitiesError(f"cannot open the warehouse: {type(exc).__name__}") from exc
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
        raise OpportunitiesError(
            f"the warehouse has no table {', '.join(missing)}; run `uv run revint build gold` first"
        )


def run_opportunities(settings: Settings, stage_dir: Path = OPPORTUNITIES_DIR) -> StageResult:
    """Run the opportunity stage for `settings.asof.date`: the as-of inputs, the schema, the
    engines and the run summary, in one transaction; rebuilt in full on every run. `stage_dir`
    lets a test run a copy of the stage with an extra file."""
    _check_gold(settings)
    try:
        result = run_stage(stage_dir, settings)
    except PipelineError as exc:
        raise OpportunitiesError(str(exc)) from exc
    logger.info(
        "opportunity stage: %d files, %d statements, as of %s",
        len(result.files),
        result.statements,
        settings.asof.date.isoformat(),
    )
    return result


def build_asof_inputs(settings: Settings) -> StageResult:
    """Build the as-of inputs (story #106). They are the first file of the opportunity stage, so
    this runs the whole stage, which also rebuilds the schema and the run summary."""
    return run_opportunities(settings)
