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
    ValidationError,
    field_validator,
    model_validator,
)

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
        """A key matches after trimming both ends, so two keys that trim to the same text
        would be ambiguous, and a blank key or value maps nothing useful."""
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

    @field_validator("candidate_columns")
    @classmethod
    def _no_repeated_candidates(cls, value: list[str]) -> list[str]:
        repeated = sorted({name for name in value if value.count(name) > 1})
        if repeated:
            raise ValueError(f"names repeat: {', '.join(repeated)}")
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
    tolerance_amount: float = Field(
        default=0.01, ge=0, description="Allowed difference in amount reconciliation checks."
    )


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
