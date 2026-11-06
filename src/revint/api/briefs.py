"""The AI brief endpoints' service (spec 06, story #138). Routers call these functions; they
never call Gemini or open DuckDB themselves. Generation is `revint.ai.briefs`, which sends
Gemini only the evidence package.
"""

from __future__ import annotations

import re
from typing import Any

from revint.ai import briefs, store
from revint.ai.client import AiUnavailableError, BriefClient
from revint.ai.evidence import PackageError
from revint.api.service import NoBriefError, NotFoundError, NotReadyError, connect
from revint.config import Settings


class AiDisabledError(Exception):
    """ai.enabled is false."""


class AiFailedError(Exception):
    """Gemini answered, but no answer passed the checks."""


def _exists(settings: Settings, opp_id: str) -> None:
    with connect(settings) as con:
        found = con.execute("select 1 from opp_opportunities where opp_id = ?", [opp_id]).fetchall()
    if not found:
        raise NotFoundError(opp_id)


def _real_customer(settings: Settings, opp_id: str) -> tuple[str, str] | None:
    """The masked label of the opportunity's customer and its real "name · code", if known."""
    with connect(settings) as con:
        rows = con.execute(
            "select o.customer_key, c.customer_name, c.customer_code from opp_opportunities o "
            "left join dim_customer c on o.customer_key = c.customer_key where o.opp_id = ?",
            [opp_id],
        ).fetchall()
    if not rows:
        return None
    key, name, code = rows[0]
    real = " · ".join(part for part in (name, code) if part)
    return (store.mask_label(settings, key), real) if real else None


def _unmasked(value: Any, label: str, real: str) -> Any:
    """Every string of the brief with the masked label (with or without "Customer") replaced."""
    code = store.ENTITY_LABEL.search(label)
    if code is None:
        return value
    pattern = re.compile(rf"\b(?:customer\s+)?{re.escape(code.group())}\b", re.IGNORECASE)
    if isinstance(value, str):
        return pattern.sub(real, value)
    if isinstance(value, list):
        return [_unmasked(item, label, real) for item in value]
    if isinstance(value, dict):
        return {key: _unmasked(item, label, real) for key, item in value.items()}
    return value


def _body(settings: Settings, output: store.Output, cached: bool) -> dict[str, Any]:
    # Story #170: Gemini only ever saw the masked label, and the stored brief keeps it; the real
    # customer is put back here, locally, on the way to the screen.
    brief = output.response
    customer = _real_customer(settings, output.opp_id)
    if customer is not None:
        brief = _unmasked(brief, *customer)
    return {
        "kind": "ai",
        "opp_id": output.opp_id,
        "brief": brief,
        "provenance": {
            "model": output.model,
            "prompt_version": output.prompt_version,
            "generated_at": output.generated_at,
            "validation_status": output.validation_status,
            "review_status": output.review_status,
            "cached": cached,
        },
    }


def latest_brief(settings: Settings, opp_id: str) -> dict[str, Any]:
    """The latest valid brief, or NotFoundError when there is none."""
    _exists(settings, opp_id)
    try:
        output = store.latest(settings, opp_id)
    except store.StoreError as exc:
        raise NotReadyError(str(exc)) from exc
    if output is None or output.validation_status != "valid":
        raise NoBriefError(opp_id)
    return _body(settings, output, cached=True)


def generate_brief(
    settings: Settings, opp_id: str, client: BriefClient | None = None
) -> dict[str, Any]:
    """Generate the brief, or return the cached one."""
    _exists(settings, opp_id)
    if not settings.ai.enabled:
        raise AiDisabledError("AI briefs are turned off")
    try:
        result = briefs.generate(settings, opp_id, client)
    except briefs.AiDisabledError as exc:
        raise AiDisabledError(str(exc)) from exc
    except (PackageError, store.StoreError) as exc:
        raise NotReadyError(str(exc)) from exc
    if result.output.validation_status != "valid":
        raise AiFailedError("the AI brief did not pass the checks; try again later")
    return _body(settings, result.output, result.cached)


__all__ = [
    "AiDisabledError",
    "AiFailedError",
    "AiUnavailableError",
    "generate_brief",
    "latest_brief",
]
