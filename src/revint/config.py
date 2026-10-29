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
from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError

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
    """Label normalisation (spec 01 S3); filled from profiling."""

    channel_map: dict[str, str] = Field(default={}, description="Source channel -> canonical.")
    branch_map: dict[str, str] = Field(default={}, description="Source branch -> canonical.")


class NetSalesSettings(_Section):
    field: str = Field(
        default="Net AMOUNT",
        min_length=1,
        description="Source amount column treated as net sales (provisional, decisions.md §3).",
    )


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
    recon: ReconSettings = Field(default_factory=ReconSettings)
    asof: AsofSettings

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
