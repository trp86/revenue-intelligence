"""Runner for the numbered SQL files of one stage (spec 10 section 5).

A stage is a folder of `.sql` files. They run in filename order inside one DuckDB
transaction: if any statement fails, the whole stage rolls back and the failing file
is named. SQL may use named parameters (`$asof_date`); values come from `Settings`.

Error text and logs never carry SQL text or row values: only file names, statement
numbers and counts, with quoted values in DuckDB messages masked.
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
from pydantic import BaseModel

from revint.config import Settings

logger = logging.getLogger(__name__)

EXIT_STAGE_FAILED = 4
EXIT_WAREHOUSE_LOCKED = 5

# Sections and fields that are not SQL parameters: file locations, and maps
# (they are looked up in Python, not in SQL).
_EXCLUDED_SECTIONS = frozenset({"paths", "api", "ai"})

# Substrings DuckDB uses when another process holds the database file.
_LOCK_MARKERS = (
    "being used by another process",
    "could not set lock",
    "conflicting lock",
    "already open",
)


class PipelineError(Exception):
    """A stage could not be run."""


class StageError(PipelineError):
    """A stage failed; `file` is the SQL file that caused it, when known."""

    def __init__(self, message: str, file: str | None = None) -> None:
        super().__init__(message)
        self.file = file


class WarehouseLockedError(PipelineError):
    """The warehouse file is open in another process."""


@dataclass(frozen=True)
class StageResult:
    stage: str
    files: tuple[str, ...]
    statements: int


@dataclass(frozen=True)
class _Statement:
    query: str
    parameters: tuple[str, ...]


@dataclass(frozen=True)
class _SqlFile:
    name: str
    statements: tuple[_Statement, ...]


def flatten_parameters(
    model: BaseModel, prefix: str = "", skip: frozenset[str] = frozenset()
) -> dict[str, Any]:
    """Flatten a settings model to `{section_key: value}` SQL parameters.

    `skip` names top-level fields to leave out. A mapping is not itself a parameter: it is
    given as two lists in the same order, `<name>_keys` and `<name>_values`, which SQL joins
    with `unnest`. Two fields that would get the same name are refused.
    """
    found: dict[str, Any] = {}

    def put(name: str, value: Any) -> None:
        if name in found:
            raise ValueError(f"parameter name collision: {name}")
        found[name] = value

    def add(current: BaseModel, path: str, omit: frozenset[str]) -> None:
        for field_name in type(current).model_fields:
            if field_name in omit:
                continue
            value = getattr(current, field_name)
            name = f"{path}_{field_name}" if path else field_name
            if isinstance(value, BaseModel):
                add(value, name, frozenset())
            elif isinstance(value, dict):
                put(f"{name}_keys", list(value.keys()))
                put(f"{name}_values", list(value.values()))
            else:
                put(name, list(value) if isinstance(value, list) else value)

    add(model, prefix, skip)
    return found


def settings_parameters(settings: Settings) -> dict[str, Any]:
    """The named SQL parameters available to every stage, from `Settings`."""
    params = flatten_parameters(settings, skip=_EXCLUDED_SECTIONS)
    params["duplicates_key_columns"] = settings.duplicate_key_columns
    return params


def _describe(exc: Exception) -> str:
    """First line of a DuckDB message with quoted values masked."""
    lines = (line.strip() for line in str(exc).splitlines())
    first = next((line for line in lines if line), type(exc).__name__)
    return re.sub(r"'[^']*'", "'<masked>'", first)


def _sql_files(stage_dir: Path) -> list[Path]:
    found = [p for p in stage_dir.iterdir() if p.is_file() and p.suffix.lower() == ".sql"]
    return sorted(found, key=lambda p: p.name)


def _plan(stage_dir: Path, params: dict[str, Any]) -> list[_SqlFile]:
    """Read and check every file before anything runs: syntax and parameters."""
    parser = duckdb.connect(":memory:")
    plan: list[_SqlFile] = []
    try:
        for path in _sql_files(stage_dir):
            try:
                text = path.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeDecodeError) as exc:
                raise StageError(
                    f"{path.name} cannot be read: {type(exc).__name__}", path.name
                ) from exc
            try:
                parsed = parser.extract_statements(text)
            except duckdb.Error as exc:
                raise StageError(f"{path.name} cannot parse: {_describe(exc)}", path.name) from exc
            statements = tuple(
                _Statement(s.query, tuple(sorted(s.named_parameters))) for s in parsed
            )
            _check_parameters(path.name, statements, params)
            plan.append(_SqlFile(path.name, statements))
    finally:
        parser.close()
    return plan


def _check_parameters(
    file: str, statements: tuple[_Statement, ...], params: dict[str, Any]
) -> None:
    for number, statement in enumerate(statements, start=1):
        missing = [f"${name}" for name in statement.parameters if name not in params]
        if missing:
            raise StageError(
                f"{file} statement {number} of {len(statements)}: "
                f"missing parameters {', '.join(missing)}",
                file,
            )


def _connect(warehouse: Path) -> duckdb.DuckDBPyConnection:
    try:
        warehouse.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise StageError(
            f"cannot create the warehouse folder for {warehouse}: {exc.strerror or 'error'}"
        ) from exc
    try:
        return duckdb.connect(str(warehouse))
    except duckdb.IOException as exc:
        if any(marker in str(exc).lower() for marker in _LOCK_MARKERS):
            raise WarehouseLockedError(
                f"the warehouse {warehouse} is in use by another process "
                "(for example the API); stop it and run the stage again"
            ) from exc
        raise StageError(f"cannot open the warehouse {warehouse}: {_describe(exc)}") from exc


def _rollback(con: duckdb.DuckDBPyConnection) -> None:
    try:
        con.execute("rollback")
    except duckdb.Error:
        pass  # no open transaction left to roll back


def _run_plan(con: duckdb.DuckDBPyConnection, plan: list[_SqlFile], params: dict[str, Any]) -> None:
    con.execute("begin transaction")
    try:
        for sql_file in plan:
            total = len(sql_file.statements)
            for number, statement in enumerate(sql_file.statements, start=1):
                values = {name: params[name] for name in statement.parameters}
                try:
                    if values:
                        con.execute(statement.query, values)
                    else:
                        con.execute(statement.query)
                except duckdb.Error as exc:
                    raise StageError(
                        f"{sql_file.name} statement {number} of {total} failed: {_describe(exc)}",
                        sql_file.name,
                    ) from exc
        con.execute("commit")
    except BaseException:
        _rollback(con)
        raise


def run_stage(
    stage_dir: Path,
    settings: Settings,
    warehouse: Path | None = None,
    extra_parameters: Mapping[str, Any] | None = None,
) -> StageResult:
    """Run every `.sql` file in `stage_dir` in filename order, in one transaction.

    `extra_parameters` adds named parameters the caller knows and `Settings` does not, such
    as the bronze file for silver; a name that a settings parameter already uses is refused.
    Raises `StageError` (naming the failing file; the stage is rolled back) or
    `WarehouseLockedError`. `warehouse` defaults to `paths.warehouse`.
    """
    stage_dir = Path(stage_dir)
    stage = stage_dir.name
    if not stage_dir.is_dir():
        raise StageError(f"stage folder not found: {stage_dir}")
    params = settings_parameters(settings)
    clashing = sorted(set(extra_parameters or {}) & set(params))
    if clashing:
        raise StageError(f"extra parameters clash with settings parameters: {', '.join(clashing)}")
    params.update(extra_parameters or {})
    try:
        plan = _plan(stage_dir, params)
        con = _connect(warehouse if warehouse is not None else settings.paths.warehouse)
        try:
            _run_plan(con, plan, params)
        finally:
            con.close()
    except StageError as exc:
        logger.warning("stage %s failed in file %s", stage, exc.file or "(none)")
        raise
    result = StageResult(
        stage=stage,
        files=tuple(f.name for f in plan),
        statements=sum(len(f.statements) for f in plan),
    )
    logger.info("stage %s: %d files, %d statements", stage, len(result.files), result.statements)
    return result


def execute_stage(
    stage_dir: Path,
    settings: Settings,
    warehouse: Path | None = None,
    extra_parameters: Mapping[str, Any] | None = None,
) -> int:
    """Run a stage for the command line: print a one-line outcome, return an exit code."""
    name = Path(stage_dir).name
    try:
        result = run_stage(stage_dir, settings, warehouse, extra_parameters)
    except WarehouseLockedError as exc:
        print(f"stage {name}: {exc}", file=sys.stderr)
        return EXIT_WAREHOUSE_LOCKED
    except StageError as exc:
        print(f"stage {name} failed: {exc}; no changes were made to the warehouse", file=sys.stderr)
        return EXIT_STAGE_FAILED
    print(f"stage {name}: {len(result.files)} files, {result.statements} statements")
    return 0
