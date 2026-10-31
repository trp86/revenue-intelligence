"""The build log: one row per stage run (spec 10 section 5).

Every row says which stage ran, whether it succeeded, when it started, how long it took, how
many files, statements and rows were involved, the failing SQL file when it failed, and the
hash of the business settings it ran with. The table `build_log` lives in the warehouse file
but is written by this module, never by stage SQL, so a stage rebuild keeps earlier rows.

Only counts, names of stages and SQL files, and the hash are stored. A failure's message is
never stored or logged here, because it could carry a value.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import duckdb

from revint.config import Settings, config_hash

logger = logging.getLogger(__name__)

BUILD_LOG_TABLE = "build_log"
STATUSES = ("succeeded", "failed")
_STAGE_NAME = re.compile(r"[a-z][a-z0-9_]*")

_CREATE = f"""
create table if not exists {BUILD_LOG_TABLE} (
    run_id varchar not null,
    stage varchar not null,
    status varchar not null,
    started_at timestamp not null,
    duration_seconds double not null,
    files bigint,
    statements bigint,
    rows_out bigint,
    failed_file varchar,
    config_hash varchar not null
)
"""
_COLUMNS = (
    "run_id",
    "stage",
    "status",
    "started_at",
    "duration_seconds",
    "files",
    "statements",
    "rows_out",
    "failed_file",
    "config_hash",
)


class BuildLogError(Exception):
    """The build log could not be written or read."""


@dataclass(frozen=True)
class StageCounts:
    """The aggregate counts of a finished stage; any of them may be unknown."""

    files: int | None = None
    statements: int | None = None
    rows_out: int | None = None


def _connect(settings: Settings, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    warehouse = settings.paths.warehouse
    try:
        if not read_only:
            warehouse.parent.mkdir(parents=True, exist_ok=True)
        return duckdb.connect(str(warehouse), read_only=read_only)
    except (duckdb.Error, OSError) as exc:
        raise BuildLogError(
            f"cannot open the warehouse for {BUILD_LOG_TABLE}: {type(exc).__name__}"
        ) from exc


def record_stage(
    settings: Settings,
    stage: str,
    status: str,
    started_at: datetime,
    duration_seconds: float,
    counts: StageCounts | None = None,
    failed_file: str | None = None,
) -> str:
    """Add one row to `build_log` and return its run id.

    `started_at` is a time with a zone; it is stored in UTC. The table is created on first use
    and rows are only ever added.
    """
    if status not in STATUSES:
        raise BuildLogError(f"status must be one of {', '.join(STATUSES)}")
    if not _STAGE_NAME.fullmatch(stage):
        raise BuildLogError("stage must be a lower-case name such as 'silver'")
    counts = counts or StageCounts()
    run_id = uuid.uuid4().hex
    started = started_at.astimezone(UTC).replace(tzinfo=None)
    con = _connect(settings)
    try:
        con.execute(_CREATE)
        con.execute(
            f"insert into {BUILD_LOG_TABLE} values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                run_id,
                stage,
                status,
                started,
                duration_seconds,
                counts.files,
                counts.statements,
                counts.rows_out,
                failed_file,
                config_hash(settings),
            ],
        )
    except duckdb.Error as exc:
        raise BuildLogError(f"cannot write {BUILD_LOG_TABLE}: {type(exc).__name__}") from exc
    finally:
        con.close()
    logger.info("%s: %s %s in %.1fs", BUILD_LOG_TABLE, stage, status, duration_seconds)
    return run_id


def read_build_log(settings: Settings) -> list[dict[str, Any]]:
    """Every row of `build_log` in the order the stages were recorded (oldest first).

    No warehouse, or no table yet, gives no rows. `started_at` comes back with a UTC zone.
    """
    if not settings.paths.warehouse.is_file():
        return []
    con = _connect(settings, read_only=True)
    try:
        exists = con.execute(
            "select count(*) from information_schema.tables where table_name = ?",
            [BUILD_LOG_TABLE],
        ).fetchone()[0]
        if not exists:
            return []
        data = con.execute(
            f"select {', '.join(_COLUMNS)} from {BUILD_LOG_TABLE} order by started_at, rowid"
        ).fetchall()
    except duckdb.Error as exc:
        raise BuildLogError(f"cannot read {BUILD_LOG_TABLE}: {type(exc).__name__}") from exc
    finally:
        con.close()
    rows = [dict(zip(_COLUMNS, row, strict=True)) for row in data]
    for row in rows:
        row["started_at"] = row["started_at"].replace(tzinfo=UTC)
    return rows


def _failed_file(exc: BaseException) -> str | None:
    """The SQL file named by the error or by an error it was raised from, if any."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        file = getattr(current, "file", None)
        if isinstance(file, str) and file:
            return file
        current = current.__cause__ or current.__context__
    return None


def run_logged[T](
    settings: Settings,
    stage: str,
    run: Callable[[], T],
    to_counts: Callable[[T], StageCounts],
) -> T:
    """Run a stage and record it in `build_log`, whether it succeeds or fails.

    `run` does the work and returns its result; `to_counts` turns that result into the counts
    to store. A failure is recorded with the failing SQL file (when the error names one) and
    then raised unchanged. If the row itself cannot be written after a success,
    `BuildLogError` is raised; after a failure the original error wins and the problem is
    logged as a warning.
    """
    started = datetime.now(UTC)
    clock = time.perf_counter()
    try:
        result = run()
    except BaseException as exc:
        try:
            record_stage(
                settings,
                stage,
                "failed",
                started,
                time.perf_counter() - clock,
                failed_file=_failed_file(exc),
            )
        except BuildLogError:
            logger.warning("%s: could not record the failed %s stage", BUILD_LOG_TABLE, stage)
        raise
    record_stage(
        settings, stage, "succeeded", started, time.perf_counter() - clock, to_counts(result)
    )
    return result
