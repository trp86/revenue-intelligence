"""Check the API on the DuckDB version MotherDuck supports (story #195).

Runs with the project code and DuckDB 1.5.6 layered over it, started by
deploy/upload_warehouse.py:

    uv run --with duckdb==1.5.6 python deploy/check_api.py <warehouse file> <app db file>

It calls every endpoint the screens use, plus generating a suggestion with a stand-in Gemini
(no network, no key), and exits 1 if any answer is not what the app expects. A stand-in
signed-in user replaces the login check, as in the unit tests. Output: status codes only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb
from fastapi.testclient import TestClient

from revint.ai import briefs
from revint.ai.client import Reply
from revint.api import auth as api_auth
from revint.api.app import create_app
from revint.config import load_settings

# the same valid stand-in answer as the browser tests (frontend/e2e/serve_fake_ai.py)
ANSWER = {
    "headline": "Win back this customer",
    "explanation": "The measured facts show the customer has gone quiet.",
    "recommendation": "Call the customer this week.",
    "actions": [
        {"text": "Call the buyer", "suggested_owner_role": "Sales rep", "evidence_ids": []}
    ],
    "risks": [],
    "confidence_label": "Low",
    "evidence_ids_used": [],
}


class _FakeGemini:
    def generate(self, **_kwargs: object) -> Reply:
        return Reply(text=json.dumps(ANSWER), token_in=1, token_out=1)


def check(warehouse: Path, app_db: Path) -> list[str]:
    """The problems found; empty when every endpoint answers as expected."""
    base = load_settings(env={})
    paths = base.paths.model_copy(update={"warehouse": warehouse, "app_db": app_db})
    settings = base.model_copy(update={"paths": paths})
    api_auth.require_user = lambda _request, _store: "check"  # type: ignore[assignment]
    briefs.default_client = _FakeGemini  # type: ignore[assignment]
    client = TestClient(create_app(settings))
    first = client.get("/api/v1/opportunities", params={"page_size": 1}).json()["items"][0]
    opp = first["opp_id"]
    expected = [
        ("get", "/api/v1/health", 200),
        ("get", "/api/v1/definitions", 200),
        ("get", "/api/v1/overview", 200),
        ("get", "/api/v1/opportunities?type=dormancy&sort=score&page=2", 200),
        ("get", f"/api/v1/opportunities/{opp}", 200),
        ("post", f"/api/v1/opportunities/{opp}/brief", 200),
        ("get", f"/api/v1/opportunities/{opp}/brief", 200),
        ("post", f"/api/v1/opportunities/{opp}/brief?regenerate=true", 200),
    ]
    problems = []
    for method, path, status in expected:
        response = getattr(client, method)(path)
        got = response.status_code
        label = path.split("?")[0].replace(opp, "<id>")
        print(f"   {got} {method.upper()} {label}")
        if got != status:
            error = response.json().get("error", {}) if response.content else {}
            problems.append(
                f"{method.upper()} {label}: {got}, expected {status} "
                f"({error.get('code', '?')}: {error.get('message', '')[:200]})"
            )
    return problems


if __name__ == "__main__":
    print(f"   API check on duckdb {duckdb.__version__}")
    found = check(Path(sys.argv[1]), Path(sys.argv[2]))
    if found:
        print("   problems: " + "; ".join(found))
        sys.exit(1)
    print("   every endpoint answered as expected")
