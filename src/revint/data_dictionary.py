"""The data dictionary: every gold column, defined (spec 02 section 7, story #86).

`docs/data_dictionary.md` is generated from two things: the metadata of the gold tables in the
warehouse (names, order and types) and the hand-written definitions in
`config/definitions.yaml`, which the UI will show later ("every number can show its
definition"). A gold column with no definition fails the build and is named.

The file holds no data: no row, no customer, no product, no date and no count, so it is the same
for any warehouse built from the same code and settings. It is committed, so a reviewer sees a
change to the gold layer as a change to this file. Run `uv run revint report dictionary` to
regenerate it.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

import duckdb
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from revint.config import Settings

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
DEFINITIONS_FILE = ROOT / "config" / "definitions.yaml"
DICTIONARY_FILE = ROOT / "docs" / "data_dictionary.md"

# The gold tables, in the order the dictionary lists them, with their grain.
GOLD_TABLES: dict[str, str] = {
    "v_net_sales": "one row per sales line gold loads; the only place net sales is defined",
    "dim_date": "one row per calendar day, plus the unknown member -1",
    "dim_customer": "one row per customer code, plus the unknown member -1",
    "dim_product": "one row per product code, plus the unknown member -1",
    "dim_branch": "one row per normalised branch, plus the unknown member -1",
    "fact_sales": "one row per sales line gold loads (a row of v_net_sales)",
    "mart_customer_month": "one row per customer and month",
    "mart_customer_category_month": "one row per customer, product category and month",
    "mart_customer_profile": "one row per customer",
    "mart_peer_category_share": "one row per peer group and product category",
    "mart_branch_month": "one row per branch and month",
}
EXIT_DICTIONARY_FAILED = 4


class DictionaryError(Exception):
    """The dictionary could not be built."""


class Definition(BaseModel):
    """One hand-written definition. `applies_to` lists `table.column` names; `*` matches any
    run of characters and `{column}` stands for the source column of a templated name."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    kind: str
    text: str = Field(min_length=1)
    applies_to: list[str] = Field(min_length=1)
    source: str | None = None
    rule: str | None = None
    flags: list[str] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _id_is_a_slug(cls, value: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", value):
            raise ValueError("an id is lower-case letters, digits and underscores")
        return value

    @field_validator("kind")
    @classmethod
    def _kind_is_known(cls, value: str) -> str:
        if value not in {"metric", "dimension", "flag", "key"}:
            raise ValueError("kind is metric, dimension, flag or key")
        return value


@dataclass(frozen=True)
class Column:
    name: str
    type: str


def load_definitions(path: Path = DEFINITIONS_FILE) -> list[Definition]:
    """Read and check the gold definitions of `config/definitions.yaml`; ids must be unique."""
    return _load(path, "definitions")


def load_evidence_definitions(path: Path = DEFINITIONS_FILE) -> list[Definition]:
    """Read and check the opportunity evidence facts (story #114), the `evidence` list."""
    evidence = _load(path, "evidence")
    gold = {item.id for item in load_definitions(path)}
    clash = sorted(item.id for item in evidence if item.id in gold)
    if clash:
        raise DictionaryError(f"evidence ids also used by a gold definition: {', '.join(clash)}")
    return evidence


def _load(path: Path, key: str) -> list[Definition]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DictionaryError(f"definitions file not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise DictionaryError(f"definitions file is not valid YAML ({path}): {exc}") from exc
    entries = (data or {}).get(key) if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise DictionaryError(f"{path.name} must hold a '{key}' list")
    parsed: list[Definition] = []
    for number, entry in enumerate(entries, start=1):
        try:
            parsed.append(Definition.model_validate(entry))
        except ValidationError as exc:
            name = entry.get("id", f"#{number}") if isinstance(entry, dict) else f"#{number}"
            first = exc.errors()[0]
            where = ".".join(str(p) for p in first["loc"]) or "entry"
            raise DictionaryError(f"definition {name}: {where}: {first['msg']}") from exc
    seen: set[str] = set()
    for item in parsed:
        if item.id in seen:
            raise DictionaryError(f"definition id repeated: {item.id}")
        seen.add(item.id)
    return parsed


def gold_columns(settings: Settings, table: str) -> list[Column]:
    """The columns of a gold table in order, with their warehouse types."""
    warehouse = settings.paths.warehouse
    if not warehouse.is_file():
        raise DictionaryError(f"warehouse not found: {warehouse}; build gold first")
    try:
        con = duckdb.connect(str(warehouse), read_only=True)
    except duckdb.Error as exc:
        raise DictionaryError(f"cannot open the warehouse: {type(exc).__name__}") from exc
    try:
        rows = con.execute(
            "select column_name, data_type from information_schema.columns "
            "where table_name = ? order by ordinal_position",
            [table],
        ).fetchall()
    finally:
        con.close()
    if not rows:
        raise DictionaryError(f"the warehouse has no table {table}; build gold first")
    return [Column(name, kind) for name, kind in rows]


def _pattern(target: str) -> re.Pattern[str]:
    """`table.column`, `*` for any run, `{column}` for a templated source column name."""
    escaped = re.escape(target).replace(r"\*", ".*").replace(r"\{column\}", "(?P<column>.+)")
    return re.compile(escaped)


def _match(
    definitions: list[Definition], table: str, column: str
) -> tuple[Definition, str | None] | None:
    full = f"{table}.{column}"
    for item in definitions:
        for target in item.applies_to:
            found = _pattern(target).fullmatch(full)
            if found:
                groups = found.groupdict()
                return item, groups.get("column")
    return None


def missing_definitions(settings: Settings, path: Path = DEFINITIONS_FILE) -> list[str]:
    """Every `table.column` of the gold layer that no definition covers, in table order."""
    definitions = load_definitions(path)
    missing = []
    for table in GOLD_TABLES:
        for column in gold_columns(settings, table):
            if _match(definitions, table, column.name) is None:
                missing.append(f"{table}.{column.name}")
    return missing


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def build_dictionary(settings: Settings, path: Path = DEFINITIONS_FILE) -> str:
    """The dictionary as markdown. Raises `DictionaryError` naming any column with no entry."""
    missing = missing_definitions(settings, path)
    if missing:
        raise DictionaryError("gold columns with no definition: " + ", ".join(missing))
    definitions = load_definitions(path)
    lines = [
        "# Data dictionary (gold layer)",
        "",
        "Generated by `uv run revint report dictionary` from the gold tables and "
        "`config/definitions.yaml`; do not edit by hand. It holds no data. Net sales is "
        f"`{settings.net_sales.field}` (provisional, to be confirmed by the client) and is "
        "defined only in `v_net_sales`.",
        "",
    ]
    for table, grain in GOLD_TABLES.items():
        lines += [
            f"## {table}",
            "",
            f"Grain: {grain}.",
            "",
            "| Column | Type | Definition | Source | Rule | Flags that affect it |",
            "|---|---|---|---|---|---|",
        ]
        for column in gold_columns(settings, table):
            match = _match(definitions, table, column.name)
            assert match is not None  # checked above
            item, source_column = match
            text = item.text.replace("{column}", source_column or "")
            source = (item.source or "").replace("{column}", source_column or "")
            flags = ", ".join(
                f"`{flag.replace('{column}', source_column or '')}`" for flag in item.flags
            )
            lines.append(
                f"| `{column.name}` | {column.type} | {_cell(text)} | {_cell(source)} "
                f"| {item.rule or ''} | {flags} |"
            )
        lines.append("")
    return "\n".join(lines)


def write_dictionary(settings: Settings, target: Path = DICTIONARY_FILE) -> Path:
    """Write the dictionary through a temporary file, so a failure keeps the old one."""
    text = build_dictionary(settings)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    try:
        temporary.write_bytes(text.encode("utf-8"))
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    logger.info("data dictionary: %d tables, %d characters", len(GOLD_TABLES), len(text))
    return target


__all__ = [
    "DEFINITIONS_FILE",
    "DICTIONARY_FILE",
    "EXIT_DICTIONARY_FAILED",
    "GOLD_TABLES",
    "Column",
    "Definition",
    "DictionaryError",
    "build_dictionary",
    "execute_dictionary",
    "gold_columns",
    "load_definitions",
    "missing_definitions",
    "write_dictionary",
]


def execute_dictionary(settings: Settings, output: Path | None = None) -> int:
    """Write the dictionary for the command line: print the outcome, return an exit code."""
    import sys

    target = output if output is not None else DICTIONARY_FILE
    try:
        path = write_dictionary(settings, target)
        columns = sum(len(gold_columns(settings, table)) for table in GOLD_TABLES)
    except (DictionaryError, OSError) as exc:
        print(f"report dictionary failed: {exc}", file=sys.stderr)
        return EXIT_DICTIONARY_FAILED
    print(f"report dictionary: {columns} columns in {len(GOLD_TABLES)} tables -> {path}")
    return 0
