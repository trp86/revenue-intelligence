"""Generate the AI brief of an opportunity (spec 05, story #137).

The flow: build the evidence package, look up the cache (evidence hash + prompt version +
model), call Gemini with the package only, validate the JSON against `AiBrief`, run the
guardrails, and store the result in app.duckdb. An invalid answer is retried up to
`ai.max_retries` times and then stored as `failed`, never as partial text. The daily call
limit and a missing key or an unreachable Gemini end the call with `AiUnavailableError`, so
the screens can show the measured evidence without the brief.
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass

import duckdb
from pydantic import ValidationError

from revint import db
from revint.ai import store
from revint.ai.client import AiUnavailableError, BriefClient, default_client
from revint.ai.evidence import EvidencePackage, PackageError, build_package
from revint.ai.guardrails import GuardrailError, check
from revint.ai.prompts import prompt_for
from revint.ai.schema import AiBrief
from revint.config import Settings

logger = logging.getLogger(__name__)

EXIT_AI_FAILED = 8


class AiDisabledError(Exception):
    """ai.enabled is false."""


@dataclass(frozen=True)
class Result:
    output: store.Output
    cached: bool


def _customer_key(settings: Settings, opp_id: str) -> int:
    try:
        con = db.open_warehouse(settings)
    except duckdb.Error as exc:
        raise PackageError(f"cannot open the warehouse ({type(exc).__name__})") from exc
    try:
        rows = con.execute(
            "select customer_key from opp_opportunities where opp_id = ?", [opp_id]
        ).fetchall()
    except duckdb.Error as exc:
        raise PackageError("the opportunity tables are not built") from exc
    finally:
        con.close()
    if not rows:
        raise PackageError("no opportunity with that id")
    return int(rows[0][0])


def package_for(settings: Settings, opp_id: str) -> EvidencePackage:
    """The package of an opportunity, with the customer masked when ai.mask_identifiers."""
    key = _customer_key(settings, opp_id)
    entity = store.mask_label(settings, key) if settings.ai.mask_identifiers else f"Customer {key}"
    return build_package(settings, opp_id, entity)


def _prompt_text(task: str, package: EvidencePackage) -> str:
    return f"{task}\nEvidence package (JSON):\n{package.to_json()}\n"


def generate(
    settings: Settings, opp_id: str, client: BriefClient | None = None, force: bool = False
) -> Result:
    """The brief of one opportunity: from the cache, or generated, checked and stored."""
    if not settings.ai.enabled:
        raise AiDisabledError("AI briefs are turned off (ai.enabled is false)")
    package = package_for(settings, opp_id)
    prompt = prompt_for(package.type)
    evidence_hash = package.evidence_hash()
    model = settings.ai.model
    if not force:
        hit = store.cached(settings, evidence_hash, prompt.version, model)
        if hit is not None:
            return Result(hit, cached=True)
    if store.calls_today(settings) >= settings.ai.daily_call_limit:
        raise AiUnavailableError("the daily call limit (ai.daily_call_limit) is reached")
    client = client or default_client()
    message = None
    reply = None
    for _attempt in range(settings.ai.max_retries + 1):
        reply = client.generate(
            model=model,
            system=prompt.system,
            prompt=_prompt_text(prompt.task, package),
            temperature=settings.ai.temperature,
            timeout_s=settings.ai.timeout_s,
        )
        try:
            brief = AiBrief.model_validate(json.loads(reply.text))
            check(brief, package)
        except (json.JSONDecodeError, ValidationError) as exc:
            message = f"invalid JSON or schema ({type(exc).__name__})"
            continue
        except GuardrailError as exc:
            message = str(exc)
            continue
        output = store.record(
            settings,
            opp_id=opp_id,
            evidence_json=package.to_json(),
            evidence_hash=evidence_hash,
            model=model,
            prompt_version=prompt.version,
            response=brief.model_dump(),
            validation_status="valid",
            validation_message=None,
            token_in=reply.token_in,
            token_out=reply.token_out,
        )
        return Result(output, cached=False)
    output = store.record(
        settings,
        opp_id=opp_id,
        evidence_json=package.to_json(),
        evidence_hash=evidence_hash,
        model=model,
        prompt_version=prompt.version,
        response=None,
        validation_status="failed",
        validation_message=message,
        token_in=reply.token_in if reply else None,
        token_out=reply.token_out if reply else None,
    )
    return Result(output, cached=False)


def top_ids(settings: Settings, n: int) -> list[str]:
    """The ids of the n best-ranked opportunities."""
    con = db.open_warehouse(settings)
    try:
        rows = con.execute(
            "select opp_id from opp_opportunities order by rank limit ?", [n]
        ).fetchall()
    finally:
        con.close()
    return [r[0] for r in rows]


def execute_generate(
    settings: Settings,
    opp_id: str | None,
    top: int | None,
    client: BriefClient | None = None,
) -> int:
    """`revint ai generate`: print counts only (no brief text); return an exit code."""
    try:
        ids = [opp_id] if opp_id else top_ids(settings, top or settings.ai.precompute_top_n)
    except duckdb.Error:
        print(
            "ai generate failed: the opportunity tables are not built; run "
            "`uv run revint opportunities build` first",
            file=sys.stderr,
        )
        return EXIT_AI_FAILED
    counts = {"valid": 0, "failed": 0, "cached": 0}
    for one in ids:
        try:
            result = generate(settings, one, client)
        except (AiDisabledError, AiUnavailableError, PackageError, store.StoreError) as exc:
            print(f"ai generate stopped: {exc}", file=sys.stderr)
            print(
                f"ai generate: {counts['valid']} valid, {counts['failed']} failed, "
                f"{counts['cached']} cached of {len(ids)}"
            )
            return EXIT_AI_FAILED
        if result.cached:
            counts["cached"] += 1
        else:
            counts[result.output.validation_status] += 1
    print(
        f"ai generate: {counts['valid']} valid, {counts['failed']} failed, "
        f"{counts['cached']} cached of {len(ids)}"
    )
    logger.info("ai generate: %s", counts)
    return 0 if counts["failed"] == 0 else EXIT_AI_FAILED
