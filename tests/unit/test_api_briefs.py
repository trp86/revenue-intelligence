"""Story #138: the AI brief endpoints (spec 06, spec 05 section 9). A fake Gemini client only.

The warehouse is the acceptance warehouse of story #115, built once per module; each test has
its own app.duckdb.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient
from silver_helpers import query
from test_opportunity_acceptance import built, copied  # noqa: F401

from revint.ai import briefs as ai_briefs
from revint.ai.client import AiUnavailableError, Reply
from revint.api.app import create_app
from revint.api.openapi import OPENAPI_FILE, schema_text
from revint.config import Settings
from revint.opportunities import run_opportunities

API = "/api/v1"
ANSWER = {
    "headline": "Follow up with the customer",
    "explanation": "See the measured facts.",
    "recommendation": "Call the customer this week.",
    "actions": [{"text": "Call", "suggested_owner_role": "Sales rep", "evidence_ids": []}],
    "risks": [],
    "confidence_label": "Low",
    "evidence_ids_used": [],
}


@dataclass
class FakeClient:
    answer: str = json.dumps(ANSWER)
    error: Exception | None = None
    calls: list[dict] = field(default_factory=list)

    def generate(self, **kwargs: object) -> Reply:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return Reply(text=self.answer, token_in=10, token_out=5)


@pytest.fixture(scope="module")
def ready(built: Settings, tmp_path_factory: pytest.TempPathFactory) -> Settings:  # noqa: F811
    settings = copied(built, tmp_path_factory.mktemp("api_briefs"))
    run_opportunities(settings)
    return settings


@pytest.fixture
def work(ready: Settings, tmp_path: Path) -> Settings:
    return ready.model_copy(
        update={"paths": ready.paths.model_copy(update={"app_db": tmp_path / "app.duckdb"})}
    )


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeClient:
    client = FakeClient()
    monkeypatch.setattr(ai_briefs, "default_client", lambda: client)
    return client


def first(settings: Settings) -> str:
    return query(settings, "select opp_id from opp_opportunities order by rank")[0][0]


# AC1: GET the latest brief ------


def test_ac1_no_brief_yet_is_404_no_brief(work: Settings) -> None:
    response = TestClient(create_app(work)).get(f"{API}/opportunities/{first(work)}/brief")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "no_brief"


def test_ac1_an_unknown_opportunity_is_404_not_found(work: Settings) -> None:
    response = TestClient(create_app(work)).get(f"{API}/opportunities/nope/brief")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_ac1_the_latest_brief_with_its_provenance(work: Settings, fake: FakeClient) -> None:
    client = TestClient(create_app(work))
    opp = first(work)
    client.post(f"{API}/opportunities/{opp}/brief")
    body = client.get(f"{API}/opportunities/{opp}/brief").json()
    assert body["kind"] == "ai" and body["brief"]["headline"] == ANSWER["headline"]
    provenance = body["provenance"]
    assert provenance["model"] == work.ai.model
    assert provenance["prompt_version"].startswith("system.v")  # the newest system prompt
    assert provenance["validation_status"] == "valid" and provenance["review_status"] == "Draft"
    assert provenance["generated_at"]


# AC2: POST generates, or returns the cached one ------


def test_ac2_post_generates_then_returns_the_cached_brief(work: Settings, fake: FakeClient) -> None:
    client = TestClient(create_app(work))
    opp = first(work)
    one = client.post(f"{API}/opportunities/{opp}/brief")
    two = client.post(f"{API}/opportunities/{opp}/brief")
    assert (one.status_code, two.status_code) == (200, 200)
    assert (one.json()["provenance"]["cached"], two.json()["provenance"]["cached"]) == (False, True)
    assert len(fake.calls) == 1


def test_ac2_post_for_an_unknown_opportunity_is_404(work: Settings, fake: FakeClient) -> None:
    response = TestClient(create_app(work)).post(f"{API}/opportunities/nope/brief")
    assert response.status_code == 404
    assert fake.calls == []


# AC3: AI disabled or failing ------


def test_ac3_ai_disabled_is_503_and_makes_no_call(work: Settings, fake: FakeClient) -> None:
    off = work.model_copy(update={"ai": work.ai.model_copy(update={"enabled": False})})
    response = TestClient(create_app(off)).post(f"{API}/opportunities/{first(work)}/brief")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ai_disabled"
    assert fake.calls == []


def test_ac3_gemini_unreachable_is_503_ai_unavailable(work: Settings, fake: FakeClient) -> None:
    fake.error = AiUnavailableError("Gemini error 503")
    response = TestClient(create_app(work)).post(f"{API}/opportunities/{first(work)}/brief")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ai_unavailable"


def test_ac3_an_answer_that_fails_the_checks_is_503(work: Settings, fake: FakeClient) -> None:
    fake.answer = json.dumps({**ANSWER, "recommendation": "Offer a discount."})
    client = TestClient(create_app(work))
    response = client.post(f"{API}/opportunities/{first(work)}/brief")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ai_unavailable"
    # a failed answer is never served as the brief
    assert client.get(f"{API}/opportunities/{first(work)}/brief").status_code == 404


def test_ac3_the_evidence_still_works_when_ai_is_off(work: Settings) -> None:
    off = work.model_copy(update={"ai": work.ai.model_copy(update={"enabled": False})})
    response = TestClient(create_app(off)).get(f"{API}/opportunities/{first(work)}")
    assert response.status_code == 200 and response.json()["measured"]


# AC5: the contract ------


def test_ac5_the_openapi_file_has_the_brief_endpoints() -> None:
    assert OPENAPI_FILE.read_text(encoding="utf-8") == schema_text()
    paths = json.loads(schema_text())["paths"]
    assert set(paths[f"{API}/opportunities/{{opp_id}}/brief"]) == {"get", "post"}


def test_ac5_the_router_never_calls_gemini_directly() -> None:
    root = Path(__file__).resolve().parents[2]
    source = (root / "src" / "revint" / "api" / "app.py").read_text(encoding="utf-8")
    assert "genai" not in source and "revint.ai.client" not in source


# AC6 ------


def test_ac6_every_ac_has_a_test_in_this_module() -> None:
    text = Path(__file__).read_text(encoding="utf-8")
    for ac in (1, 2, 3, 5):
        assert f"def test_ac{ac}_" in text


# Story #170: the brief names the real customer, only after Gemini and on the way out ------


def _real_name(settings: Settings, opp: str) -> str:
    name, code = query(
        settings,
        "select c.customer_name, c.customer_code from opp_opportunities o "
        "join dim_customer c on o.customer_key = c.customer_key where o.opp_id = ?",
        opp,
    )[0]
    return " · ".join(part for part in (name, code) if part)


@pytest.fixture
def labelled(monkeypatch: pytest.MonkeyPatch) -> FakeClient:
    """A fake Gemini that names the customer by its masked label, as the prompt asks."""
    answer = {
        **ANSWER,
        "headline": "Win back Customer C-0001",
        "actions": [
            {
                "text": "Call C-0001 this week",
                "suggested_owner_role": "Sales rep",
                "evidence_ids": [],
            }
        ],
    }
    client = FakeClient(answer=json.dumps(answer))
    monkeypatch.setattr(ai_briefs, "default_client", lambda: client)
    return client


def test_170_ac2_the_brief_shows_the_real_customer(work: Settings, labelled: FakeClient) -> None:
    client = TestClient(create_app(work))
    opp = first(work)
    real = _real_name(work, opp)
    for body in (
        client.post(f"{API}/opportunities/{opp}/brief").json(),
        client.get(f"{API}/opportunities/{opp}/brief").json(),
    ):
        assert body["brief"]["headline"] == f"Win back {real}"
        assert body["brief"]["actions"][0]["text"] == f"Call {real} this week"


def test_170_ac2_gemini_never_receives_the_name_or_code(
    work: Settings, labelled: FakeClient
) -> None:
    opp = first(work)
    TestClient(create_app(work)).post(f"{API}/opportunities/{opp}/brief")
    name, code = _real_name(work, opp).split(" · ")
    sent = json.dumps(labelled.calls, default=str)
    assert name not in sent and code not in sent
    assert "C-0001" in sent


def test_170_ac2_the_stored_brief_stays_masked(work: Settings, labelled: FakeClient) -> None:
    opp = first(work)
    TestClient(create_app(work)).post(f"{API}/opportunities/{opp}/brief")
    con = duckdb.connect(str(work.paths.app_db), read_only=True)
    try:
        stored = con.execute("select response_json from app_ai_outputs").fetchall()
    finally:
        con.close()
    assert stored and all("C-0001" in row[0] for row in stored)
    name = _real_name(work, opp).split(" · ")[0]
    assert all(name not in row[0] for row in stored)


# Story #181: regenerate skips the cache and keeps the old brief ------


def test_181_ac3_regenerate_skips_the_cache_and_keeps_the_old_row(
    work: Settings, fake: FakeClient
) -> None:
    client = TestClient(create_app(work))
    opp = first(work)
    first_body = client.post(f"{API}/opportunities/{opp}/brief").json()
    cached = client.post(f"{API}/opportunities/{opp}/brief").json()
    assert cached["provenance"]["cached"] is True and len(fake.calls) == 1
    fresh = client.post(f"{API}/opportunities/{opp}/brief", params={"regenerate": "true"})
    assert fresh.status_code == 200
    assert fresh.json()["provenance"]["cached"] is False
    assert len(fake.calls) == 2  # a new Gemini call although nothing changed
    assert fresh.json()["provenance"]["generated_at"] >= first_body["provenance"]["generated_at"]
    con = duckdb.connect(str(work.paths.app_db), read_only=True)
    try:
        ((rows,),) = con.execute(
            "select count(*) from app_ai_outputs where opp_id = ? and validation_status = 'valid'",
            [opp],
        ).fetchall()
    finally:
        con.close()
    assert rows == 2  # the old brief is kept, never overwritten


def test_181_ac4_a_failed_regenerate_keeps_the_previous_brief(
    work: Settings, fake: FakeClient
) -> None:
    client = TestClient(create_app(work))
    opp = first(work)
    client.post(f"{API}/opportunities/{opp}/brief")
    fake.error = AiUnavailableError("Gemini error 503")
    failed = client.post(f"{API}/opportunities/{opp}/brief", params={"regenerate": "true"})
    assert failed.status_code == 503
    assert (
        client.get(f"{API}/opportunities/{opp}/brief").json()["brief"]["headline"]
        == ANSWER["headline"]
    )
