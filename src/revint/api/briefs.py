"""The AI brief endpoints' service (spec 06, story #138). Routers call these functions; they
never call Gemini or open DuckDB themselves. Generation is `revint.ai.briefs`, which sends
Gemini only the evidence package.
"""

from __future__ import annotations

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


def _body(output: store.Output, cached: bool) -> dict[str, Any]:
    return {
        "kind": "ai",
        "opp_id": output.opp_id,
        "brief": output.response,
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
    return _body(output, cached=True)


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
    return _body(result.output, result.cached)


__all__ = [
    "AiDisabledError",
    "AiFailedError",
    "AiUnavailableError",
    "generate_brief",
    "latest_brief",
]
