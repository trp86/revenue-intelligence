"""The evidence package sent to Gemini (spec 05 section 3, story #137).

This is the only code that builds what Gemini sees (CLAUDE.md rule 5). A package is built from
`opp_evidence` and `opp_opportunities` only: the measured facts of one opportunity, its value
estimate and its labels. It never holds a sales line, a customer code or a customer name: the
customer is a masked label (`Customer C-0042`), and the masking map is kept in app.duckdb by
`revint.ai.store`, never sent. Category names are product data, not customer data, so they are
kept. The package is hashed, and the hash is part of the cache key.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

import duckdb
from pydantic import BaseModel, Field

from revint.config import Settings
from revint.data_dictionary import load_evidence_definitions

FACT_LABELS = {
    "days_since_last_order": "Days since the last order",
    "median_interval_days": "Usual days between orders",
    "n_orders": "Orders up to the as-of date",
    "last_order_date": "Last order date",
    "lookback_net_sales": "Net sales in the months before going quiet",
    "prior_net_sales": "Net sales in the same months last year",
    "current_net_sales": "Net sales in the latest months",
    "prior_orders": "Orders in the same months last year",
    "decline_pct": "Decline on last year, percent",
    "n_peers": "Peers in the group",
    "n_buying_peers": "Peers that buy the category",
    "peer_penetration": "Share of peers that buy the category",
    "peer_median_net_sales": "Median net sales of the buying peers",
    "support": "Customers who bought both categories",
    "confidence": "Share of buyers of the first category who bought the second",
    "lift": "Lift of the category pair",
    "median_b_net_sales": "Median net sales in the second category of those customers",
}


class PackageFact(BaseModel):
    id: str
    label: str
    value: float | str
    unit: str
    definition: str
    # the value as the screens show it (story #172); the prompt asks Gemini to quote this form
    display: str


class PackageEstimate(BaseModel):
    kind: str = "Estimate"
    value_low: float | None
    value_high: float | None
    value_level: str
    method: str | None
    value_low_display: str | None = None
    value_high_display: str | None = None


class EvidencePackage(BaseModel):
    opp_id: str
    type: str
    as_of_date: str
    algo_version: str
    entity: str
    category: str | None
    category_a: str | None
    priority: str
    confidence: str
    reason_codes: list[str]
    facts: list[PackageFact] = Field(max_length=50)
    estimate: PackageEstimate
    data_quality_notes: list[str]
    net_sales_definition: str

    def to_json(self) -> str:
        return json.dumps(self.model_dump(), sort_keys=True, separators=(",", ":"))

    def evidence_hash(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    def fact_ids(self) -> set[str]:
        return {f.id for f in self.facts}


def _grouped(number: float, places: int) -> str:
    """en-US grouping, rounded half up (like the screens' Intl.NumberFormat), no trailing zeros."""
    quantum = Decimal(1).scaleb(-places)
    text = f"{Decimal(str(number)).quantize(quantum, rounding=ROUND_HALF_UP):,f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def display_value(value: float | str, unit: str) -> str:
    """A value as the screens format it (frontend/src/format.ts formatValue, story #172)."""
    if isinstance(value, str):
        return value
    if unit == "share":
        return f"{_grouped(value * 100, 2)}%"
    if unit == "percent":
        return f"{_grouped(value, 2)}%"
    if unit in ("ratio", "points"):
        return _grouped(value, 2)
    return _grouped(value, 0) if abs(value) >= 100 else _grouped(value, 2)


class PackageError(Exception):
    """The opportunity does not exist or the warehouse is not ready."""


def _value(number: Decimal | float | None, day: date | None) -> float | str:
    if day is not None:
        return day.isoformat()
    return round(float(number), 4) if number is not None else 0.0


def build_package(settings: Settings, opp_id: str, entity: str) -> EvidencePackage:
    """The package of one opportunity; `entity` is the masked label from the store."""
    definitions = {d.id: d.text for d in load_evidence_definitions()}
    try:
        con = duckdb.connect(str(settings.paths.warehouse), read_only=True)
    except duckdb.Error as exc:
        raise PackageError(f"cannot open the warehouse ({type(exc).__name__})") from exc
    try:
        rows = con.execute(
            "select o.type, o.as_of_date, o.algo_version, o.category, o.priority, o.confidence, "
            "o.reason_codes, o.value_low, o.value_high, o.value_level, o.value_method, "
            "coalesce(c.f_multi_identity, false), x.category_a "
            "from opp_opportunities o "
            "left join dim_customer c on o.customer_key = c.customer_key "
            "left join opp_crosssell x on o.opp_id = x.opp_id "
            "where o.opp_id = ?",
            [opp_id],
        ).fetchall()
        if not rows:
            raise PackageError("no opportunity with that id")
        facts = con.execute(
            "select fact, value_number, value_date, unit, definition_id from opp_evidence "
            "where opp_id = ? and kind = 'Measured' order by fact",
            [opp_id],
        ).fetchall()
    except duckdb.Error as exc:
        raise PackageError(f"the opportunity tables are not ready ({type(exc).__name__})") from exc
    finally:
        con.close()
    (
        kind,
        as_of,
        version,
        category,
        priority,
        confidence,
        reasons,
        low,
        high,
        level,
        method,
        multi,
        category_a,
    ) = rows[0]
    notes = []
    if multi:
        notes.append("The customer code may stand for more than one customer.")
    if "confidence_capped" in (reasons or []):
        notes.append("Confidence is capped at Medium.")
    if "peer_fallback" in (reasons or []):
        notes.append("The peer group fell back to the wider channel group.")
    return EvidencePackage(
        opp_id=opp_id,
        type=kind,
        as_of_date=as_of.isoformat(),
        algo_version=version,
        entity=entity,
        category=category,
        category_a=category_a,
        priority=priority,
        confidence=confidence,
        reason_codes=list(reasons or []),
        facts=[
            PackageFact(
                id=fact,
                label=FACT_LABELS.get(fact, fact),
                value=_value(number, day),
                unit=unit,
                definition=definitions.get(definition_id, ""),
                display=display_value(_value(number, day), unit),
            )
            for fact, number, day, unit, definition_id in facts
        ][: settings.ai.max_facts],
        estimate=PackageEstimate(
            value_low=None if low is None else round(float(low), 2),
            value_high=None if high is None else round(float(high), 2),
            value_level=level,
            method=method,
            value_low_display=None if low is None else display_value(float(low), "net sales"),
            value_high_display=None if high is None else display_value(float(high), "net sales"),
        ),
        data_quality_notes=notes,
        net_sales_definition=f"{settings.net_sales.field} (provisional, to be confirmed)",
    )
