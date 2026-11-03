"""Data access for the API (spec 06, story #134): the only API module that opens DuckDB.

Routers call these functions and never hold SQL. The warehouse is opened read-only for each
request, so a build in another process is never blocked for long and the API never writes it.
User input reaches SQL only as bound parameters, or as a name checked against an allow-list
(the sort columns). Every metric is returned as {value, unit, definition_id}; the ids are the
ones in config/definitions.yaml, so the screens can show each number's definition.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import duckdb

from revint.config import Settings
from revint.data_dictionary import load_definitions, load_evidence_definitions

# Allow-lists: a filter or sort value outside these is refused before any SQL is built.
SORTS = {
    "rank": "o.rank asc",
    "score": "o.score desc, o.rank asc",
    "value_high": "o.value_high desc nulls last, o.rank asc",
}
TYPES = ("dormancy", "recovery", "whitespace", "crosssell")
LEVELS = ("High", "Medium", "Low")
_REQUIRED = ("opp_opportunities", "opp_evidence", "opp_run_summary", "dim_customer")


class NotReadyError(Exception):
    """The warehouse or the opportunity tables are not built."""


class NotFoundError(Exception):
    """No row with that id."""


class NoBriefError(NotFoundError):
    """The opportunity exists but has no valid AI brief yet."""


@dataclass(frozen=True)
class Filters:
    type: str | None = None
    priority: str | None = None
    confidence: str | None = None
    branch: str | None = None
    channel: str | None = None


def metric(value: Any, unit: str, definition_id: str) -> dict[str, Any]:
    """A number with its unit and the id of its definition."""
    if isinstance(value, Decimal):
        value = float(value)
    return {"value": value, "unit": unit, "definition_id": definition_id}


@contextmanager
def connect(settings: Settings) -> Iterator[duckdb.DuckDBPyConnection]:
    warehouse = settings.paths.warehouse
    if not warehouse.is_file():
        raise NotReadyError(
            "the warehouse is not built; run `uv run revint build all` and "
            "`uv run revint opportunities build`"
        )
    try:
        con = duckdb.connect(str(warehouse), read_only=True)
    except duckdb.Error as exc:
        raise NotReadyError(f"cannot open the warehouse ({type(exc).__name__})") from exc
    try:
        have = {
            n for (n,) in con.execute("select table_name from information_schema.tables").fetchall()
        }
        missing = [t for t in _REQUIRED if t not in have]
        if missing:
            raise NotReadyError(
                "the opportunity tables are not built; run `uv run revint opportunities build`"
            )
        yield con
    finally:
        con.close()


def _rows(con: duckdb.DuckDBPyConnection, sql: str, params: list[Any] | None = None) -> list[dict]:
    cursor = con.execute(sql, params or [])
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def health(settings: Settings) -> dict[str, Any]:
    """Ready or not, with what the data was built from; never raises."""
    info: dict[str, Any] = {
        "status": "not_ready",
        "as_of_date": None,
        "net_sales_field": settings.net_sales.field,
        "net_sales_provisional": True,
        "built_at": None,
        "message": None,
    }
    try:
        with connect(settings) as con:
            ((as_of,),) = con.execute("select max(as_of_date) from opp_run_summary").fetchall()
            built = con.execute(
                "select max(started_at) from build_log where stage = 'opportunities' "
                "and status = 'succeeded'"
            ).fetchall()
    except NotReadyError as exc:
        info["message"] = str(exc)
        return info
    except duckdb.Error:
        built = [(None,)]
    info.update(status="ready", as_of_date=as_of, built_at=built[0][0])
    return info


def definitions() -> list[dict[str, Any]]:
    """Every definition: gold and opportunity columns, and the evidence facts."""
    out = []
    for group, items in (("column", load_definitions()), ("evidence", load_evidence_definitions())):
        for item in items:
            out.append(
                {
                    "id": item.id,
                    "group": group,
                    "kind": item.kind,
                    "text": item.text,
                    "applies_to": item.applies_to,
                    "source": item.source,
                    "rule": item.rule,
                }
            )
    return out


_LIST_SELECT = """
select
    o.opp_id, o.type, o.customer_key, c.customer_code, c.customer_name, o.category,
    o.as_of_date, o.score, o.priority, o.confidence, o.value_low, o.value_high, o.value_level,
    o.rank, o.reason_codes, coalesce(c.f_multi_identity, false) as f_multi_identity,
    c.branch, c.channel
from opp_opportunities as o
left join dim_customer as c on o.customer_key = c.customer_key
"""


def _item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "opp_id": row["opp_id"],
        "type": row["type"],
        "rank": row["rank"],
        "customer": {
            "customer_key": row["customer_key"],
            "code": row["customer_code"],
            "name": row["customer_name"],
            "f_multi_identity": row["f_multi_identity"],
        },
        "category": row["category"],
        "branch": row["branch"],
        "channel": row["channel"],
        "as_of_date": row["as_of_date"],
        "score": metric(row["score"], "points", "opp_score"),
        "priority": row["priority"],
        "confidence": row["confidence"],
        "value_low": metric(row["value_low"], "net sales", "opp_value_low"),
        "value_high": metric(row["value_high"], "net sales", "opp_value_high"),
        "value_level": row["value_level"],
        "reason_codes": list(row["reason_codes"] or []),
    }


def _where(filters: Filters) -> tuple[str, list[Any]]:
    clauses, params = [], []
    for column, value in (
        ("o.type", filters.type),
        ("o.priority", filters.priority),
        ("o.confidence", filters.confidence),
        ("c.branch", filters.branch),
        ("c.channel", filters.channel),
    ):
        if value is not None:
            clauses.append(f"{column} = ?")
            params.append(value)
    return (" where " + " and ".join(clauses)) if clauses else "", params


def opportunities(
    settings: Settings, filters: Filters, page: int, page_size: int, sort: str
) -> dict[str, Any]:
    """One page of the ranked list. `sort` must be a key of SORTS (checked by the caller)."""
    order = SORTS[sort]
    where, params = _where(filters)
    with connect(settings) as con:
        ((total,),) = con.execute(
            "select count(*) from opp_opportunities as o "
            f"left join dim_customer as c on o.customer_key = c.customer_key{where}",
            params,
        ).fetchall()
        rows = _rows(
            con,
            f"{_LIST_SELECT}{where} order by {order} limit ? offset ?",
            [*params, page_size, (page - 1) * page_size],
        )
    return {
        "total": int(total),
        "page": page,
        "page_size": page_size,
        "items": [_item(r) for r in rows],
    }


def overview(settings: Settings) -> dict[str, Any]:
    """KPIs, counts by type and priority, and the top N."""
    with connect(settings) as con:
        ((n, low, high, customers),) = con.execute(
            "select count(*), sum(value_low), sum(value_high), count(distinct customer_key) "
            "from opp_opportunities"
        ).fetchall()
        by_type = _rows(
            con,
            "select type, count(*) as n, "
            "count(*) filter (where priority = 'High') as high, "
            "count(*) filter (where priority = 'Medium') as medium, "
            "count(*) filter (where priority = 'Low') as low, "
            "sum(value_low) as value_low, sum(value_high) as value_high "
            "from opp_opportunities group by type order by type",
        )
        top = _rows(con, f"{_LIST_SELECT} order by o.rank limit ?", [settings.api.top_n_overview])
        ((as_of,),) = con.execute("select max(as_of_date) from opp_run_summary").fetchall()
    return {
        "as_of_date": as_of,
        "kpis": {
            "opportunities": metric(int(n), "opportunities", "opp_id"),
            "customers": metric(int(customers), "customers", "opp_customer_key"),
            "value_low": metric(low, "net sales", "opp_value_low"),
            "value_high": metric(high, "net sales", "opp_value_high"),
        },
        "by_type": [
            {
                "type": r["type"],
                "count": metric(int(r["n"]), "opportunities", "opp_type"),
                "by_priority": {
                    "High": int(r["high"]),
                    "Medium": int(r["medium"]),
                    "Low": int(r["low"]),
                },
                "value_low": metric(r["value_low"], "net sales", "opp_value_low"),
                "value_high": metric(r["value_high"], "net sales", "opp_value_high"),
            }
            for r in by_type
        ],
        "top": [_item(r) for r in top],
    }


def opportunity(settings: Settings, opp_id: str) -> dict[str, Any]:
    """One opportunity: identity, measured facts, the estimate and the data-quality notes."""
    with connect(settings) as con:
        rows = _rows(con, f"{_LIST_SELECT} where o.opp_id = ?", [opp_id])
        if not rows:
            raise NotFoundError(opp_id)
        facts = _rows(
            con,
            "select fact, value_number, value_date, unit, kind, definition_id from opp_evidence "
            "where opp_id = ? order by kind desc, fact",
            [opp_id],
        )
        method = con.execute(
            "select value_method from opp_opportunities where opp_id = ?", [opp_id]
        ).fetchall()
    item = _item(rows[0])
    measured = [
        {
            "fact": f["fact"],
            "kind": "measured",
            "value": f["value_date"] if f["value_date"] is not None else _number(f["value_number"]),
            "unit": f["unit"],
            "definition_id": f["definition_id"],
        }
        for f in facts
        if f["kind"] == "Measured"
    ]
    notes = []
    if item["customer"]["f_multi_identity"]:
        notes.append("The customer code may stand for more than one customer (f_multi_identity).")
    if "confidence_capped" in item["reason_codes"]:
        notes.append("Confidence is capped at Medium.")
    if "peer_fallback" in item["reason_codes"]:
        notes.append("The peer group fell back to the wider group.")
    return {
        **item,
        "measured": measured,
        "estimate": {
            "kind": "estimate",
            "value_low": item["value_low"],
            "value_high": item["value_high"],
            "value_level": item["value_level"],
            "method": method[0][0] if method else None,
        },
        "data_quality_notes": notes,
    }


def _number(value: Decimal | float | None) -> float | None:
    return None if value is None else float(value)


def as_json(value: Any) -> Any:
    """Dates and datetimes as ISO text, for the JSON responses."""
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value
