"""Response contracts of the API (spec 06 section 3, story #134).

Every number a screen shows is a `Metric`: its value, its unit and the id of its definition in
config/definitions.yaml (served by /definitions), so the UI can show what each number means.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class Metric(BaseModel):
    value: float | int | None
    unit: str
    definition_id: str


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


class HealthResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    as_of_date: date | None
    net_sales_field: str
    net_sales_provisional: bool
    built_at: datetime | None
    message: str | None


class Definition(BaseModel):
    id: str
    group: Literal["column", "evidence"]
    kind: str
    text: str
    applies_to: list[str]
    source: str | None
    rule: str | None


class DefinitionsResponse(BaseModel):
    definitions: list[Definition]


class Customer(BaseModel):
    customer_key: int
    code: str | None
    name: str | None
    f_multi_identity: bool


class OpportunityItem(BaseModel):
    opp_id: str
    type: str
    rank: int
    customer: Customer
    category: str | None
    branch: str | None
    channel: str | None
    as_of_date: date
    score: Metric
    priority: str
    confidence: str
    value_low: Metric
    value_high: Metric
    value_level: str
    reason_codes: list[str]


class OpportunitiesResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[OpportunityItem]


class Kpis(BaseModel):
    opportunities: Metric
    customers: Metric
    value_low: Metric
    value_high: Metric


class TypeSummary(BaseModel):
    type: str
    count: Metric
    by_priority: dict[str, int]
    value_low: Metric
    value_high: Metric


class OverviewResponse(BaseModel):
    as_of_date: date | None
    kpis: Kpis
    by_type: list[TypeSummary]
    top: list[OpportunityItem]


class Fact(BaseModel):
    fact: str
    kind: Literal["measured"]
    value: float | date | None
    unit: str
    definition_id: str


class Estimate(BaseModel):
    kind: Literal["estimate"]
    value_low: Metric
    value_high: Metric
    value_level: str
    method: str | None


class BriefAction(BaseModel):
    text: str
    suggested_owner_role: str
    evidence_ids: list[str]


class Brief(BaseModel):
    headline: str
    explanation: str
    recommendation: str
    actions: list[BriefAction]
    risks: list[str]
    confidence_label: Literal["High", "Medium", "Low"]
    evidence_ids_used: list[str]


class BriefProvenance(BaseModel):
    model: str
    prompt_version: str
    generated_at: datetime
    validation_status: str
    review_status: str
    cached: bool


class BriefResponse(BaseModel):
    kind: Literal["ai"]
    opp_id: str
    brief: Brief
    provenance: BriefProvenance


class OpportunityDetail(OpportunityItem):
    measured: list[Fact]
    estimate: Estimate
    data_quality_notes: list[str]
