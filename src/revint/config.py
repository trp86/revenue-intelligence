"""Settings model and loader for config/settings.yaml (spec 10 section 4).

Business decisions live in the YAML file and change through a PR. Environment
variables may override paths only, never thresholds or other business keys.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from datetime import date as Date
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    ValidationError,
    field_validator,
    model_validator,
)

from revint.silver_schema import SILVER_FLAG_COLUMNS

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SETTINGS_FILE = PROJECT_ROOT / "config" / "settings.yaml"
ENV_PREFIX = "REVINT_PATHS_"

# Sections left out of the config hash: they describe where files live on this
# machine, not what the business decided.
HASH_EXCLUDED_SECTIONS = {"paths"}


class ConfigError(Exception):
    """Settings could not be loaded or failed validation."""


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PathsSettings(_Section):
    raw: Path = Field(description="Folder with the source Excel files (read-only).")
    bronze: Path = Field(description="Folder for bronze Parquet files.")
    warehouse: Path = Field(description="DuckDB warehouse file (silver and gold).")
    app_db: Path = Field(description="DuckDB app state file (AI output, actions).")
    reports: Path = Field(
        default=Path("reports"),
        description="Folder for generated reports (git-ignored); relative to the project root.",
    )
    users: Path = Field(
        default=Path("data/users.json"),
        description="Users who can sign in, with argon2id password hashes (story #191); "
        "git-ignored, created by `revint user add`. Never committed.",
    )


class AsofSettings(_Section):
    date: Date = Field(description="As-of date for the data; 2020-02-29 for the POC.")


class IngestSettings(_Section):
    """Bronze ingestion (spec 01 B2, B3, B7)."""

    sheets: list[str] = Field(
        default=["RAW SCJ SALES"], min_length=1, description="Sheet names to load."
    )
    header_search_rows: int = Field(
        default=30, gt=0, description="How many leading rows to search for the header."
    )
    header_min_match: float = Field(
        default=0.8,
        gt=0,
        le=1,
        description="Share of expected_columns that must match for a row to be the header.",
    )
    expected_columns: list[str] = Field(
        default=[],
        description="The source column names after suffixing; filled from profiling (D2).",
    )


class VoidSettings(_Section):
    """Void handling (spec 01 S6, decision D3, provisional)."""

    blank_means: Literal["not_void", "void"] = Field(
        default="not_void", description="What a blank Void means; not_void sets void_flag = 0."
    )
    value_map: dict[str, Literal[0, 1]] = Field(
        default={},
        description="Non-blank Void value -> void_flag (0 or 1); empty until profiling lists them.",
    )


class DuplicatesSettings(_Section):
    """Exact duplicates (spec 01 S5, decision D4, provisional)."""

    exclude_from_net_sales: StrictBool = Field(
        default=True,
        description="Whether gold omits the extra copies; silver marks them either way.",
    )
    key_columns: list[str] | None = Field(
        default=None,
        description="Columns compared for duplicates; unset means ingest.expected_columns "
        "minus _source_row (see Settings.duplicate_key_columns).",
    )


def _check_text_map(value: dict[str, str]) -> dict[str, str]:
    """A key matches after trimming both ends, so two keys that trim to the same text would be
    ambiguous, and a blank key or value maps nothing useful."""
    trimmed: dict[str, str] = {}
    for key, canonical in value.items():
        if not key.strip():
            raise ValueError("a label key is blank")
        if not canonical.strip():
            raise ValueError(f"the canonical name for '{key.strip()}' is blank")
        if key.strip() in trimmed:
            raise ValueError(f"two keys are the same once trimmed: {key.strip()}")
        trimmed[key.strip()] = canonical
    return value


class LabelsSettings(_Section):
    """Label normalisation (spec 01 S3).

    A map turns a source label into its canonical name; a label with no entry is kept as it is
    and flagged. The columns the labels come from are listed separately, because a flat map
    has no column in it. Channel labels come from `Channel_Category` and branch labels from
    `Branch_Name` (maintainer's decision on issue #37), and the maps hold only the obvious
    spelling variants. Column names are final names (spec 01 B3); the cross-check against
    `ingest.expected_columns` is in `Settings`.
    """

    channel_columns: list[str] = Field(
        default=["Channel_Category"],
        min_length=1,
        description="Columns whose values are channel labels.",
    )
    branch_columns: list[str] = Field(
        default=["Branch_Name"],
        min_length=1,
        description="Columns whose values are branch labels.",
    )
    channel_map: dict[str, str] = Field(default={}, description="Source channel -> canonical.")
    branch_map: dict[str, str] = Field(default={}, description="Source branch -> canonical.")

    @field_validator("channel_columns", "branch_columns")
    @classmethod
    def _no_repeated_columns(cls, value: list[str]) -> list[str]:
        repeated = sorted({name for name in value if value.count(name) > 1})
        if repeated:
            raise ValueError(f"names repeat: {', '.join(repeated)}")
        return value

    @field_validator("channel_map", "branch_map")
    @classmethod
    def _keys_and_values_are_usable(cls, value: dict[str, str]) -> dict[str, str]:
        return _check_text_map(value)


class NetSalesSettings(_Section):
    """Which source column is net sales (provisional, docs/decisions.md section 3).

    Column names are the final bronze and silver names (spec 01 B3). The cross-check against
    `ingest.expected_columns` is in `Settings`, which holds both sections.
    """

    field: str = Field(
        default="Net_Amount_2",
        min_length=1,
        description="Final name of the column treated as net sales: source column 46 (Excel "
        "AT), net of discounts and before the 3% back margin. Must be a candidate.",
    )
    candidate_columns: list[str] = Field(
        default=[
            "Selling_Amount",
            "NET_AMOUNT_1",
            "AMOUNT_AF_DIS",
            "Net_Amount_2",
            "Net_AMOUNT_3",
            "TAX_AMOUNT",
        ],
        min_length=1,
        description="The amount columns net sales may be chosen from (spec 01 S11, spec 02 N2).",
    )
    quantity_field: str = Field(
        default="Quantity(PCS)",
        min_length=1,
        description="Final name of the quantity column, used for free goods (spec 01 S7).",
    )

    exclude_flags: list[str] = Field(
        default=[],
        description="Silver flag columns whose rows get included = false in v_net_sales (spec 02 "
        "N3); the rows stay in the fact. Empty means every loaded row is included.",
    )

    @field_validator("candidate_columns", "exclude_flags")
    @classmethod
    def _no_repeated_candidates(cls, value: list[str]) -> list[str]:
        repeated = sorted({name for name in value if value.count(name) > 1})
        if repeated:
            raise ValueError(f"names repeat: {', '.join(repeated)}")
        return value

    @field_validator("exclude_flags")
    @classmethod
    def _flags_are_silver_flags(cls, value: list[str]) -> list[str]:
        unknown = [name for name in value if name not in SILVER_FLAG_COLUMNS]
        if unknown:
            raise ValueError(f"not silver flag columns: {', '.join(unknown)}")
        return value

    @model_validator(mode="after")
    def _field_is_a_candidate(self) -> NetSalesSettings:
        if self.field not in self.candidate_columns:
            raise ValueError(
                f"net_sales.field '{self.field}' is not one of net_sales.candidate_columns"
            )
        return self


class CustomersSettings(_Section):
    """The source columns the customer-code table is built from (spec 01 S4).

    Customer identity is an open business question: the code is the key and near-duplicate
    codes are not merged. Which columns hold the code, the name and the branch is a business
    input, so it is config. Names are final column names (spec 01 B3); the cross-check against
    `ingest.expected_columns` is in `Settings`.
    """

    code_column: str = Field(
        default="CustomerCode", min_length=1, description="Column holding the customer code."
    )
    name_column: str = Field(
        default="Customer", min_length=1, description="Column holding the customer name."
    )
    branch_column: str = Field(
        default="Branch_Name", min_length=1, description="Column holding the branch name."
    )


class MartsSettings(_Section):
    """Marts (spec 02 section 6)."""

    zero_fill: StrictBool = Field(
        default=True,
        description="Whether a month with no sales is a row with 0 (true) or absent (false) in "
        "the monthly marts, so engines that need continuity can rely on it.",
    )


class CalendarSettings(_Section):
    """The date dimension (spec 02 section 4; the fiscal calendar is an open question)."""

    fiscal_year_start_month: StrictInt = Field(
        default=1,
        ge=1,
        le=12,
        description="Month (1 to 12) the fiscal year starts; 1 makes the fiscal year the "
        "calendar year.",
    )
    date_column: str = Field(
        default="Date",
        min_length=1,
        description="Typed silver date column whose first and last date set the range of "
        "dim_date. Final column name (spec 01 B3); gold checks it is a date column.",
    )


class RegionsSettings(_Section):
    """Where a branch's region comes from (spec 02 section 4)."""

    source_column: str = Field(
        default="Region",
        min_length=1,
        description="Source column holding a region; the default for a branch with no entry in "
        "branch_to_region. Final column name (spec 01 B3).",
    )
    branch_to_region: dict[str, str] = Field(
        default={}, description="Normalised branch name -> region; overrides the source column."
    )

    @field_validator("branch_to_region")
    @classmethod
    def _keys_and_values_are_usable(cls, value: dict[str, str]) -> dict[str, str]:
        return _check_text_map(value)


class PeerGroupsSettings(_Section):
    """Peer groups for the peer category share mart (spec 02 section 6).

    Only the group definition and its minimum size live here; the whitespace thresholds are
    spec 03's. A group below min_size falls back to the group made of fallback_columns.
    """

    columns: list[str] = Field(
        default=["Channel_Category", "Branch_Name"],
        min_length=1,
        description="Source columns that together define a peer group.",
    )
    min_size: StrictInt = Field(
        default=10, ge=1, description="Fewest customers a peer group may have before it falls back."
    )
    fallback_columns: list[str] = Field(
        default=["Channel_Category"],
        description="Columns of the wider group used below min_size; a subset of columns, empty "
        "for no fallback.",
    )

    @field_validator("columns", "fallback_columns")
    @classmethod
    def _no_repeated_columns(cls, value: list[str]) -> list[str]:
        repeated = sorted({name for name in value if value.count(name) > 1})
        if repeated:
            raise ValueError(f"names repeat: {', '.join(repeated)}")
        return value

    @model_validator(mode="after")
    def _fallback_is_part_of_the_group(self) -> PeerGroupsSettings:
        outside = [c for c in self.fallback_columns if c not in self.columns]
        if outside:
            raise ValueError(
                "peer_groups.fallback_columns has names not in peer_groups.columns: "
                + ", ".join(outside)
            )
        return self


class ProductSettings(_Section):
    """The source columns the product dimension is built from (spec 02 section 4).

    The brand and category columns were chosen from profiling (story #73, spec 02 section 12);
    the choice is provisional until the maintainer confirms it.
    """

    code_column: str = Field(
        default="SCJ_CODE_1", min_length=1, description="Column holding the product code."
    )
    name_column: str = Field(
        default="Product_Decription", min_length=1, description="Column holding the product name."
    )
    brand_column: str = Field(
        default="Actual_Brands_1", min_length=1, description="Column holding the brand."
    )
    category_column: str = Field(
        default="Internal_Category", min_length=1, description="Column holding the category."
    )


class RecoverySettings(_Section):
    """Recovery engine (spec 03 section 3.1)."""

    window_months: StrictInt = Field(
        default=3,
        ge=1,
        le=12,
        description="Months ending at the as-of date compared with a year earlier.",
    )
    min_decline_pct: float = Field(
        default=20, ge=0, le=100, description="Smallest decline, in percent of the prior period."
    )
    min_prior_sales: float = Field(
        default=25000,
        ge=0,
        description="Smallest net sales in the prior period (provisional; story #105 profiled it).",
    )
    min_prior_orders: StrictInt = Field(
        default=3, ge=1, description="Fewest orders in the prior period for a customer to count."
    )


class DormancySettings(_Section):
    """Dormancy engine (spec 03 section 3.2)."""

    min_orders: StrictInt = Field(
        default=4, ge=2, description="Fewest orders a customer needs before its interval is used."
    )
    interval_multiple: float = Field(
        default=2.0, ge=1, description="Dormant past this many times the customer's own interval."
    )
    min_days: StrictInt = Field(
        default=45, ge=0, description="Dormant only when also quiet for more than this many days."
    )
    lookback_months: StrictInt = Field(
        default=12, ge=1, description="Months before going quiet in which the customer had sales."
    )


class WhitespaceSettings(_Section):
    """Whitespace engine (spec 03 section 3.3). The peer group and its minimum size are
    peer_groups.*; there is no whitespace.min_peer_size."""

    min_peer_penetration: float = Field(
        default=0.5, gt=0, le=1, description="Smallest share of peers that buy the category."
    )
    lookback_months: StrictInt = Field(
        default=12, ge=1, description="Months in which the customer bought none of the category."
    )


class CrosssellSettings(_Section):
    """Cross-sell engine (spec 03 section 3.4)."""

    min_support: StrictInt = Field(
        default=30, ge=1, description="Fewest customers who bought both categories of a pair."
    )
    min_confidence: float = Field(
        default=0.3, ge=0, le=1, description="Smallest share of A buyers who also bought B."
    )
    min_lift: float = Field(
        default=1.2, ge=0, description="Smallest lift of a pair (confidence over B's base rate)."
    )
    lookback_months: StrictInt = Field(
        default=12, ge=1, description="Months in which the customer bought category A."
    )


class ScoringSettings(_Section):
    """Opportunity score, priority and confidence (spec 03 section 4). The four weights sum to
    1; the components are defined in story #113."""

    weight_value: float = Field(default=0.40, ge=0, le=1, description="Weight of the value rank.")
    weight_evidence: float = Field(
        default=0.30, ge=0, le=1, description="Weight of the evidence strength."
    )
    weight_urgency: float = Field(default=0.20, ge=0, le=1, description="Weight of urgency.")
    weight_data_quality: float = Field(
        default=0.10, ge=0, le=1, description="Weight of the share of unflagged lines."
    )
    priority_high: float = Field(default=70, ge=0, le=100, description="Score for priority High.")
    priority_medium: float = Field(
        default=40, ge=0, le=100, description="Score for priority Medium."
    )
    confidence_high: float = Field(
        default=0.7, ge=0, le=1, description="Evidence and data quality for confidence High."
    )
    confidence_medium: float = Field(
        default=0.4, ge=0, le=1, description="Evidence and data quality for confidence Medium."
    )
    urgency_horizon_days: StrictInt = Field(
        default=365,
        ge=1,
        description="Dormancy urgency falls from 1 to 0 over these days quiet (provisional, #113).",
    )
    urgency_neutral: float = Field(
        default=0.5,
        ge=0,
        le=1,
        description="Urgency of whitespace and cross-sell, which have no change event (#113).",
    )

    @model_validator(mode="after")
    def _consistent(self) -> ScoringSettings:
        total = (
            self.weight_value
            + self.weight_evidence
            + self.weight_urgency
            + self.weight_data_quality
        )
        if abs(total - 1) > 1e-9:
            raise ValueError(f"scoring weights must sum to 1, not {total:g}")
        if self.priority_high <= self.priority_medium:
            raise ValueError("scoring.priority_high must be above scoring.priority_medium")
        if self.confidence_high <= self.confidence_medium:
            raise ValueError("scoring.confidence_high must be above scoring.confidence_medium")
        return self


class ValueSettings(_Section):
    """Opportunity value range (spec 03 section 5): low and high are factors of the gap."""

    low_factor: float = Field(default=0.25, ge=0, description="Low end of the range, x the gap.")
    high_factor: float = Field(default=0.75, ge=0, description="High end of the range, x the gap.")

    @model_validator(mode="after")
    def _low_below_high(self) -> ValueSettings:
        if self.low_factor >= self.high_factor:
            raise ValueError("value.low_factor must be below value.high_factor")
        return self


class OpportunitiesSettings(_Section):
    """Settings that apply to every engine (spec 03 section 6)."""

    top_n_per_type: StrictInt | None = Field(
        default=250,
        ge=1,
        description="Most opportunities kept per engine; null keeps all (provisional, #105).",
    )


class ApiSettings(_Section):
    """The API (spec 06, story #134). Not a SQL parameter: no SQL file reads it."""

    host: str = Field(default="127.0.0.1", description="Address the API binds to (localhost).")
    port: StrictInt = Field(default=8000, ge=1, le=65535, description="Port of the API.")
    page_size_default: StrictInt = Field(
        default=25, ge=1, description="Rows per page when a request gives no page_size."
    )
    page_size_max: StrictInt = Field(default=200, ge=1, description="Most rows per page.")
    top_n_overview: StrictInt = Field(
        default=10, ge=1, description="Opportunities listed on the overview."
    )
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173"],
        description="Origins the browser may call the API from (the Vite dev server).",
    )

    @model_validator(mode="after")
    def _page_sizes(self) -> ApiSettings:
        if self.page_size_default > self.page_size_max:
            raise ValueError("api.page_size_default must not be above api.page_size_max")
        return self


class AiSettings(_Section):
    """The AI briefs (spec 05, story #137). Not a SQL parameter: no SQL file reads it."""

    enabled: bool = Field(default=True, description="False turns every Gemini call off.")
    model: str = Field(
        default="gemini-2.5-flash",
        min_length=1,
        description="The Gemini model (provisional: confirm it is available to the key).",
    )
    temperature: float = Field(default=0.2, ge=0, le=2, description="Sampling temperature.")
    max_facts: StrictInt = Field(default=15, ge=1, description="Most facts in one package.")
    max_retries: StrictInt = Field(
        default=2, ge=0, le=5, description="Retries after an invalid answer, then failed."
    )
    mask_identifiers: bool = Field(
        default=True, description="Send a masked customer label, never a code or name."
    )
    precompute_top_n: StrictInt = Field(
        default=20, ge=0, description="Briefs `revint ai generate` makes by default (by rank)."
    )
    daily_call_limit: StrictInt = Field(
        default=200, ge=0, description="Most Gemini calls in one UTC day."
    )
    timeout_s: StrictInt = Field(default=60, ge=1, description="Timeout of one Gemini call.")


RULE_IDS = [f"S{i}" for i in range(1, 13)]

Severity = Literal["info", "warning", "high"]
Action = Literal["flagged", "excluded", "transformed", "recorded"]

_DEFAULT_SEVERITY: dict[str, Severity] = {
    "S1": "info",
    "S2": "warning",
    "S3": "warning",
    "S4": "warning",
    "S5": "high",
    "S6": "high",
    "S7": "warning",
    "S8": "info",
    "S9": "high",
    "S10": "high",
    "S11": "warning",
    "S12": "info",
}
_DEFAULT_ACTION: dict[str, Action] = {
    "S1": "transformed",
    "S2": "flagged",
    "S3": "transformed",
    "S4": "recorded",
    "S5": "excluded",
    "S6": "flagged",
    "S7": "flagged",
    "S8": "flagged",
    "S9": "excluded",
    "S10": "excluded",
    "S11": "flagged",
    "S12": "recorded",
}


class QualitySettings(_Section):
    """Severity and action of each silver rule S1 to S12 in the quality results (spec 01
    section 5; maintainer's decision on issue #41).

    Both are a fixed value per rule, not computed from a percentage, because where to draw a
    threshold is a business judgement. `high` marks the rules that rest on an unconfirmed
    client assumption or change which rows count (S5, S6, S9, S10).
    """

    severity: dict[str, Severity] = Field(
        default=_DEFAULT_SEVERITY, description="Severity level of each rule S1 to S12."
    )
    action: dict[str, Action] = Field(
        default=_DEFAULT_ACTION, description="What each rule S1 to S12 does to the rows."
    )

    @field_validator("severity", "action")
    @classmethod
    def _every_rule_exactly_once(cls, value: dict[str, str]) -> dict[str, str]:
        missing = [r for r in RULE_IDS if r not in value]
        unknown = sorted(set(value) - set(RULE_IDS))
        if missing:
            raise ValueError(f"missing rules: {', '.join(missing)}")
        if unknown:
            raise ValueError(f"unknown rules: {', '.join(unknown)}")
        return value


class ReconSettings(_Section):
    """Reconciliation checks (spec 01 section 6).

    The product and date columns are the ones R4 counts and ranges over; names are final
    column names (spec 01 B3), cross-checked against `ingest.expected_columns` in `Settings`.
    The customer column is `customers.code_column`.
    """

    tolerance_amount: float = Field(
        default=0.01, ge=0, description="Allowed difference in amount reconciliation checks."
    )
    product_column: str = Field(
        default="SCJ_CODE_1",
        min_length=1,
        description="Column whose distinct values R4 counts as products.",
    )
    date_column: str = Field(
        default="Date",
        min_length=1,
        description="Typed date column whose minimum and maximum R4 reports.",
    )
    docs_duplicate_count: int = Field(
        default=556,
        ge=0,
        description="The exact-duplicate count the project docs state (D4); the data quality "
        "report shows the actual count next to it. A reference figure, not a rule.",
    )


class DisplaySettings(_Section):
    """How values are labelled on the screens (story #160); never used in SQL."""

    currency: str = Field(
        default="",
        pattern=r"^([A-Z]{3})?$",
        description="ISO 4217 code shown as the unit of money values (for example MMK); empty "
        "keeps the generic 'net sales' label. No conversion is done.",
    )


class AuthSettings(_Section):
    """Sign-in (story #191). Not a SQL parameter. Users live in paths.users."""

    session_hours: StrictInt = Field(default=8, ge=1, description="Hours a session lasts.")
    max_attempts: StrictInt = Field(
        default=5, ge=1, description="Failed sign-ins in a row before a user name is locked."
    )
    lockout_minutes: StrictInt = Field(
        default=15, ge=1, description="Minutes a user name stays locked after max_attempts."
    )
    min_password_length: StrictInt = Field(
        default=12, ge=8, description="Shortest password `revint user add` accepts."
    )
    cookie_secure: StrictBool = Field(
        default=False,
        description="Send the session cookie over https only; true when hosted (https).",
    )
    cookie_samesite: Literal["lax", "strict", "none"] = Field(
        default="lax",
        description="lax when the app and API share a site (local); none when they are hosted "
        "on different domains (then cookie_secure must be true).",
    )

    @model_validator(mode="after")
    def _none_needs_secure(self) -> AuthSettings:
        if self.cookie_samesite == "none" and not self.cookie_secure:
            raise ValueError("auth.cookie_samesite none requires auth.cookie_secure true")
        return self


class Settings(_Section):
    """Top-level settings. Each field is a section and needs a test module
    tests/unit/test_settings_<section>.py."""

    paths: PathsSettings
    ingest: IngestSettings = Field(default_factory=IngestSettings)
    void: VoidSettings = Field(default_factory=VoidSettings)
    duplicates: DuplicatesSettings = Field(default_factory=DuplicatesSettings)
    labels: LabelsSettings = Field(default_factory=LabelsSettings)
    net_sales: NetSalesSettings = Field(default_factory=NetSalesSettings)
    customers: CustomersSettings = Field(default_factory=CustomersSettings)
    quality: QualitySettings = Field(default_factory=QualitySettings)
    recon: ReconSettings = Field(default_factory=ReconSettings)
    marts: MartsSettings = Field(default_factory=MartsSettings)
    calendar: CalendarSettings = Field(default_factory=CalendarSettings)
    regions: RegionsSettings = Field(default_factory=RegionsSettings)
    peer_groups: PeerGroupsSettings = Field(default_factory=PeerGroupsSettings)
    product: ProductSettings = Field(default_factory=ProductSettings)
    recovery: RecoverySettings = Field(default_factory=RecoverySettings)
    dormancy: DormancySettings = Field(default_factory=DormancySettings)
    whitespace: WhitespaceSettings = Field(default_factory=WhitespaceSettings)
    crosssell: CrosssellSettings = Field(default_factory=CrosssellSettings)
    scoring: ScoringSettings = Field(default_factory=ScoringSettings)
    value: ValueSettings = Field(default_factory=ValueSettings)
    opportunities: OpportunitiesSettings = Field(default_factory=OpportunitiesSettings)
    api: ApiSettings = Field(default_factory=ApiSettings)
    ai: AiSettings = Field(default_factory=AiSettings)
    display: DisplaySettings = Field(default_factory=DisplaySettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    asof: AsofSettings

    @model_validator(mode="after")
    def _net_sales_columns_exist(self) -> Settings:
        """Every net sales, customer and label column must be a column the sheet has.

        Skipped while `ingest.expected_columns` is empty, that is before profiling has filled it.
        """
        known = set(self.ingest.expected_columns)
        if not known:
            return self
        problems = []
        if self.net_sales.field not in known:
            problems.append(
                f"net_sales.field '{self.net_sales.field}' is not in ingest.expected_columns"
            )
        missing = [c for c in self.net_sales.candidate_columns if c not in known]
        if missing:
            problems.append(
                "net_sales.candidate_columns has names not in ingest.expected_columns: "
                + ", ".join(missing)
            )
        if self.net_sales.quantity_field not in known:
            problems.append(
                f"net_sales.quantity_field '{self.net_sales.quantity_field}' "
                "is not in ingest.expected_columns"
            )
        customers = self.customers
        for role in ("code_column", "name_column", "branch_column"):
            column = getattr(customers, role)
            if column not in known:
                problems.append(f"customers.{role} '{column}' is not in ingest.expected_columns")
        for role in ("product_column", "date_column"):
            column = getattr(self.recon, role)
            if column not in known:
                problems.append(f"recon.{role} '{column}' is not in ingest.expected_columns")
        for role in ("code_column", "name_column", "brand_column", "category_column"):
            column = getattr(self.product, role)
            if column not in known:
                problems.append(f"product.{role} '{column}' is not in ingest.expected_columns")
        if self.calendar.date_column not in known:
            problems.append(
                f"calendar.date_column '{self.calendar.date_column}' "
                "is not in ingest.expected_columns"
            )
        if self.regions.source_column not in known:
            problems.append(
                f"regions.source_column '{self.regions.source_column}' "
                "is not in ingest.expected_columns"
            )
        absent_peer = [c for c in self.peer_groups.columns if c not in known]
        if absent_peer:
            problems.append(
                "peer_groups.columns has names not in ingest.expected_columns: "
                + ", ".join(absent_peer)
            )
        for role in ("channel_columns", "branch_columns"):
            absent = [c for c in getattr(self.labels, role) if c not in known]
            if absent:
                problems.append(
                    f"labels.{role} has names not in ingest.expected_columns: {', '.join(absent)}"
                )
        if problems:
            raise ValueError("; ".join(problems))
        return self

    @property
    def duplicate_key_columns(self) -> list[str]:
        """Columns that define an exact duplicate: `duplicates.key_columns`, or when
        unset every expected column except the lineage key `_source_row` (S5)."""
        if self.duplicates.key_columns is not None:
            return list(self.duplicates.key_columns)
        return [c for c in self.ingest.expected_columns if c != "_source_row"]


def _format_errors(error: ValidationError) -> str:
    lines = []
    for item in error.errors():
        key = ".".join(str(part) for part in item["loc"]) or "<root>"
        if item["type"] == "missing":
            lines.append(f"missing required key: {key}")
        elif item["type"] == "extra_forbidden":
            lines.append(f"unknown key: {key}")
        elif item["type"] == "value_error":
            # A rule written in the model, for example a cross-check between two keys.
            message = item["msg"].removeprefix("Value error, ")
            named = key == "<root>" or message.startswith(key)
            lines.append(message if named else f"invalid value for {key}: {message}")
        else:
            lines.append(f"invalid value for {key}: {item['msg']}")
    return "; ".join(lines)


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConfigError(f"settings file not found: {path}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"settings file is not valid YAML ({path}): {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"settings file must be a mapping at the top level: {path}")
    # A section with no keys parses as null; treat it as empty so the error
    # names the missing keys (for example asof.date) rather than the section.
    return {key: {} if value is None else value for key, value in data.items()}


def _apply_path_overrides(data: dict[str, Any], env: Mapping[str, str]) -> None:
    """Apply REVINT_PATHS_<KEY> overrides. Nothing else is read from env."""
    paths = data.get("paths")
    if not isinstance(paths, dict):
        return
    for key in list(paths):
        override = env.get(f"{ENV_PREFIX}{str(key).upper()}", "")
        if override.strip():
            paths[key] = override


def _resolve_paths(data: dict[str, Any], root: Path) -> None:
    paths = data.get("paths")
    if not isinstance(paths, dict):
        return
    for key, value in paths.items():
        if isinstance(value, str):
            paths[key] = Path(root, value)


def load_settings(
    path: Path = DEFAULT_SETTINGS_FILE, env: Mapping[str, str] | None = None
) -> Settings:
    """Load and validate settings. Relative paths resolve against the project
    root (the parent of the config folder), not the working directory."""
    environ = os.environ if env is None else env
    root = path.resolve().parent.parent
    data = _read_yaml(path)
    if isinstance(data.get("paths"), dict):
        data["paths"].setdefault("reports", "reports")
    _apply_path_overrides(data, environ)
    _resolve_paths(data, root)
    try:
        return Settings.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"invalid settings in {path}: {_format_errors(exc)}") from exc


def config_hash(settings: Settings) -> str:
    """SHA-256 of the canonical (sorted-key) JSON of the business settings."""
    payload = settings.model_dump(mode="json", exclude=HASH_EXCLUDED_SECTIONS)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
