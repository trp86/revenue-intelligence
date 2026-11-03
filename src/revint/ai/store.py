"""App state for the AI briefs, in data/app.duckdb (spec 05 section 7, story #137).

Never the warehouse. Two tables:
- `app_ai_outputs`: one row per generation attempt, with the evidence sent, its hash, the model,
  the prompt version, the time, the answer, the validation status and the token counts. A new
  attempt adds a row; nothing is overwritten.
- `app_entity_masks`: the masking map, customer key to masked label. It stays here and is never
  sent to Gemini.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import duckdb

from revint.config import Settings

_SCHEMA = (
    """
    create table if not exists app_ai_outputs (
        output_id varchar primary key,
        opp_id varchar not null,
        evidence_json varchar not null,
        evidence_hash varchar not null,
        model varchar not null,
        prompt_version varchar not null,
        generated_at timestamp not null,
        response_json varchar,
        validation_status varchar not null,
        validation_message varchar,
        review_status varchar not null,
        token_in bigint,
        token_out bigint
    )
    """,
    """
    create table if not exists app_entity_masks (
        customer_key bigint primary key,
        label varchar not null unique
    )
    """,
)


class StoreError(Exception):
    """app.duckdb cannot be opened or written."""


@dataclass(frozen=True)
class Output:
    output_id: str
    opp_id: str
    evidence_hash: str
    model: str
    prompt_version: str
    generated_at: datetime
    response: dict[str, Any] | None
    validation_status: str
    validation_message: str | None
    review_status: str
    token_in: int | None
    token_out: int | None


@contextmanager
def connect(settings: Settings, read_only: bool = False) -> Iterator[duckdb.DuckDBPyConnection]:
    path = settings.paths.app_db
    try:
        if not read_only:
            path.parent.mkdir(parents=True, exist_ok=True)
        con = duckdb.connect(str(path), read_only=read_only)
    except (duckdb.Error, OSError) as exc:
        raise StoreError(f"cannot open {path.name} ({type(exc).__name__})") from exc
    try:
        yield con
    finally:
        con.close()


def init(settings: Settings) -> None:
    """Create the tables if they are missing; existing rows are kept."""
    with connect(settings) as con:
        for statement in _SCHEMA:
            con.execute(statement)


def mask_label(settings: Settings, customer_key: int) -> str:
    """The masked label of a customer, created on first use (Customer C-0001, C-0002, ...)."""
    init(settings)
    with connect(settings) as con:
        found = con.execute(
            "select label from app_entity_masks where customer_key = ?", [customer_key]
        ).fetchall()
        if found:
            return found[0][0]
        ((n,),) = con.execute("select count(*) from app_entity_masks").fetchall()
        label = f"Customer C-{n + 1:04d}"
        con.execute("insert into app_entity_masks values (?, ?)", [customer_key, label])
        return label


def cached(
    settings: Settings, evidence_hash: str, prompt_version: str, model: str
) -> Output | None:
    """The latest valid output for this cache key, if any."""
    if not settings.paths.app_db.is_file():
        return None
    init(settings)
    with connect(settings) as con:
        rows = con.execute(
            "select * from app_ai_outputs where evidence_hash = ? and prompt_version = ? "
            "and model = ? and validation_status = 'valid' order by generated_at desc limit 1",
            [evidence_hash, prompt_version, model],
        ).fetchall()
        names = [d[0] for d in con.description] if rows else []
    return _output(dict(zip(names, rows[0], strict=True))) if rows else None


def latest(settings: Settings, opp_id: str) -> Output | None:
    """The latest output of an opportunity (valid or failed), if any."""
    if not settings.paths.app_db.is_file():
        return None
    init(settings)
    with connect(settings) as con:
        rows = con.execute(
            "select * from app_ai_outputs where opp_id = ? order by generated_at desc limit 1",
            [opp_id],
        ).fetchall()
        names = [d[0] for d in con.description] if rows else []
    return _output(dict(zip(names, rows[0], strict=True))) if rows else None


def calls_today(settings: Settings) -> int:
    """Gemini calls recorded today (UTC); a cache hit is not a call."""
    if not settings.paths.app_db.is_file():
        return 0
    init(settings)
    start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    with connect(settings) as con:
        ((n,),) = con.execute(
            "select count(*) from app_ai_outputs where generated_at >= ?", [start]
        ).fetchall()
    return int(n)


def record(
    settings: Settings,
    *,
    opp_id: str,
    evidence_json: str,
    evidence_hash: str,
    model: str,
    prompt_version: str,
    response: dict[str, Any] | None,
    validation_status: str,
    validation_message: str | None,
    token_in: int | None,
    token_out: int | None,
) -> Output:
    init(settings)
    row = Output(
        output_id=uuid.uuid4().hex,
        opp_id=opp_id,
        evidence_hash=evidence_hash,
        model=model,
        prompt_version=prompt_version,
        generated_at=datetime.now(UTC).replace(tzinfo=None),
        response=response,
        validation_status=validation_status,
        validation_message=validation_message,
        review_status="Draft",
        token_in=token_in,
        token_out=token_out,
    )
    with connect(settings) as con:
        con.execute(
            "insert into app_ai_outputs values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                row.output_id,
                opp_id,
                evidence_json,
                evidence_hash,
                model,
                prompt_version,
                row.generated_at,
                None if response is None else json.dumps(response, sort_keys=True),
                validation_status,
                validation_message,
                row.review_status,
                token_in,
                token_out,
            ],
        )
    return row


def _output(row: dict[str, Any]) -> Output:
    return Output(
        output_id=row["output_id"],
        opp_id=row["opp_id"],
        evidence_hash=row["evidence_hash"],
        model=row["model"],
        prompt_version=row["prompt_version"],
        generated_at=row["generated_at"],
        response=None if row["response_json"] is None else json.loads(row["response_json"]),
        validation_status=row["validation_status"],
        validation_message=row["validation_message"],
        review_status=row["review_status"],
        token_in=row["token_in"],
        token_out=row["token_out"],
    )
