"""Story #134: the read-only API (spec 06). Contract tests on a synthetic warehouse.

The warehouse is the acceptance warehouse of story #115 (one customer per engine), with the
opportunity stage run once per module; each test reads it through FastAPI's test client.
Synthetic data only.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_opportunity_acceptance import EXPECTED, built, copied  # noqa: F401

from revint.api.app import create_app
from revint.api.openapi import OPENAPI_FILE, schema_text
from revint.config import Settings, load_settings
from revint.opportunities import run_opportunities

API = "/api/v1"
TOTAL = sum(len(v) for v in EXPECTED.values())
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def ready(built: Settings, tmp_path_factory: pytest.TempPathFactory) -> Settings:  # noqa: F811
    settings = copied(built, tmp_path_factory.mktemp("api"))
    run_opportunities(settings)
    return settings


@pytest.fixture(scope="module")
def client(ready: Settings) -> TestClient:
    return TestClient(create_app(ready))


def metrics(node: object) -> list[dict]:
    """Every {value, unit, definition_id} object anywhere in a response."""
    found = []
    if isinstance(node, dict):
        if set(node) == {"value", "unit", "definition_id"}:
            found.append(node)
        for value in node.values():
            found += metrics(value)
    elif isinstance(node, list):
        for value in node:
            found += metrics(value)
    return found


def first_id(client: TestClient) -> str:
    return client.get(f"{API}/opportunities", params={"page_size": 1}).json()["items"][0]["opp_id"]


# AC1: health ------


def test_ac1_health_is_ready_with_the_build_info(client: TestClient) -> None:
    body = client.get(f"{API}/health").json()
    assert body["status"] == "ready"
    assert body["as_of_date"] == "2020-02-29"
    assert body["net_sales_field"] == "Net_Amount_2"
    assert body["net_sales_provisional"] is True
    assert body["currency"] == "MMK"  # story #160, from display.currency


def test_ac1_health_is_not_ready_without_a_warehouse(tmp_path: Path) -> None:
    settings = load_settings(env={"REVINT_PATHS_WAREHOUSE": str(tmp_path / "none.duckdb")})
    response = TestClient(create_app(settings)).get(f"{API}/health")
    assert response.status_code == 200
    assert response.json()["status"] == "not_ready"
    assert "revint build all" in response.json()["message"]


# AC2: definitions ------


def test_ac2_definitions_hold_the_column_and_evidence_definitions(client: TestClient) -> None:
    items = client.get(f"{API}/definitions").json()["definitions"]
    groups = {d["group"] for d in items}
    ids = {d["id"] for d in items}
    assert groups == {"column", "evidence"}
    assert {"net_sales", "opp_score", "ev_days_since_last_order"} <= ids


# AC3: overview ------


def test_ac3_overview_has_kpis_counts_by_type_and_the_top(client: TestClient) -> None:
    body = client.get(f"{API}/overview").json()
    assert body["kpis"]["opportunities"]["value"] == TOTAL
    by_type = {t["type"]: t for t in body["by_type"]}
    assert {k: v["count"]["value"] for k, v in by_type.items()} == {
        k: len(v) for k, v in EXPECTED.items()
    }
    for item in by_type.values():
        assert sum(item["by_priority"].values()) == item["count"]["value"]
    assert [t["rank"] for t in body["top"]] == list(range(1, min(10, TOTAL) + 1))


# AC4: the list ------


def test_ac4_the_list_is_ranked_and_paged(client: TestClient) -> None:
    body = client.get(f"{API}/opportunities", params={"page_size": 2, "page": 2}).json()
    assert body["total"] == TOTAL
    assert (body["page"], body["page_size"]) == (2, 2)
    assert [i["rank"] for i in body["items"]] == [3, 4]


@pytest.mark.parametrize("engine", list(EXPECTED))
def test_ac4_filter_by_type(client: TestClient, engine: str) -> None:
    body = client.get(f"{API}/opportunities", params={"type": engine}).json()
    assert body["total"] == len(EXPECTED[engine])
    assert {i["type"] for i in body["items"]} == {engine}


def test_ac4_filter_by_branch_priority_and_confidence(client: TestClient) -> None:
    # the branch is the normalised label of dim_customer (PYAY in the source becomes Pyay)
    body = client.get(f"{API}/opportunities", params={"branch": "Pyay"}).json()
    assert body["total"] == 2  # REC (recovery) and BOTH (dormancy)
    for key in ("priority", "confidence"):
        for level in ("High", "Medium", "Low"):
            got = client.get(f"{API}/opportunities", params={key: level}).json()
            assert all(i[key] == level for i in got["items"])


def test_ac4_sort_by_score_and_value_high(client: TestClient) -> None:
    for sort, field in (("score", "score"), ("value_high", "value_high")):
        items = client.get(f"{API}/opportunities", params={"sort": sort}).json()["items"]
        values = [i[field]["value"] for i in items]
        assert values == sorted(values, reverse=True), sort


def test_ac4_the_page_size_defaults_to_25_and_is_capped(client: TestClient) -> None:
    assert client.get(f"{API}/opportunities").json()["page_size"] == 25
    response = client.get(f"{API}/opportunities", params={"page_size": 201})
    assert response.status_code == 400
    assert "200" in response.json()["error"]["message"]


# AC5: detail ------


def test_ac5_detail_has_measured_facts_and_the_estimate(client: TestClient) -> None:
    body = client.get(f"{API}/opportunities/{first_id(client)}").json()
    assert body["measured"] and all(f["kind"] == "measured" for f in body["measured"])
    assert body["estimate"]["kind"] == "estimate"
    assert body["estimate"]["method"].startswith("Estimate:")
    # story #171: the range factors from config, for the plain explanation on the screen
    assert (body["estimate"]["low_factor"], body["estimate"]["high_factor"]) == (0.25, 0.75)
    assert isinstance(body["data_quality_notes"], list)
    assert body["reason_codes"]


def test_ac5_an_unknown_id_is_404(client: TestClient) -> None:
    response = client.get(f"{API}/opportunities/no-such-id")
    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "not_found", "message": "no opportunity with that id"}
    }


# AC6: every metric is defined ------


def test_ac6_every_metric_has_a_known_definition(client: TestClient) -> None:
    ids = {d["id"] for d in client.get(f"{API}/definitions").json()["definitions"]}
    bodies = [
        client.get(f"{API}/overview").json(),
        client.get(f"{API}/opportunities").json(),
        client.get(f"{API}/opportunities/{first_id(client)}").json(),
    ]
    found = [m for body in bodies for m in metrics(body)]
    assert found
    assert {m["definition_id"] for m in found} <= ids
    detail = bodies[2]
    assert {f["definition_id"] for f in detail["measured"]} <= ids


# AC7: errors ------


def test_ac7_not_built_gives_503_with_a_hint(tmp_path: Path) -> None:
    settings = load_settings(env={"REVINT_PATHS_WAREHOUSE": str(tmp_path / "none.duckdb")})
    client = TestClient(create_app(settings))
    for path in ("/overview", "/opportunities", "/opportunities/x"):
        response = client.get(f"{API}{path}")
        assert response.status_code == 503, path
        assert response.json()["error"]["code"] == "not_ready"
        assert "revint" in response.json()["error"]["message"]


def test_ac7_gold_without_opportunities_gives_503(built: Settings, tmp_path: Path) -> None:  # noqa: F811
    response = TestClient(create_app(copied(built, tmp_path))).get(f"{API}/overview")
    assert response.status_code == 503
    assert "revint opportunities build" in response.json()["error"]["message"]


def test_ac7_a_bad_parameter_is_400_with_the_error_body(client: TestClient) -> None:
    response = client.get(f"{API}/opportunities", params={"type": "assortment"})
    assert response.status_code == 400
    assert set(response.json()["error"]) == {"code", "message"}


# AC8: thin routers, read-only, no injection ------


def test_ac8_the_routers_hold_no_sql_and_do_not_import_duckdb() -> None:
    source = (ROOT / "src" / "revint" / "api" / "app.py").read_text(encoding="utf-8")
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert "duckdb" not in imported
    for word in ("select ", "from opp_", "insert ", "update "):
        assert word not in source.lower(), word


def test_ac8_the_warehouse_is_opened_read_only() -> None:
    source = (ROOT / "src" / "revint" / "api" / "service.py").read_text(encoding="utf-8")
    assert "read_only=True" in source
    assert source.count("duckdb.connect(") == 1


@pytest.mark.parametrize(
    "params",
    [
        {"branch": "PYAY' or '1'='1"},
        {"channel": "GT; drop table opp_opportunities; --"},
        {"sort": "rank; drop table opp_opportunities"},
        {"priority": "High' or 1=1 --"},
    ],
)
def test_ac8_injection_attempts_are_bound_or_refused(
    client: TestClient, ready: Settings, params: dict
) -> None:
    response = client.get(f"{API}/opportunities", params=params)
    assert response.status_code in (200, 400)
    if response.status_code == 200:
        assert response.json()["total"] == 0  # the value is bound as text, so nothing matches
    after = client.get(f"{API}/opportunities").json()["total"]
    assert after == TOTAL


# AC9: serve settings and CORS ------


def test_ac9_cors_allows_only_the_configured_origin(client: TestClient) -> None:
    allowed = client.get(f"{API}/health", headers={"Origin": "http://localhost:5173"})
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"
    other = client.get(f"{API}/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in other.headers


def test_ac9_the_api_binds_to_localhost_by_default() -> None:
    api = load_settings(env={}).api
    assert (api.host, api.port) == ("127.0.0.1", 8000)


# AC10: the committed OpenAPI schema ------


def test_ac10_the_openapi_file_matches_the_app() -> None:
    assert OPENAPI_FILE.read_text(encoding="utf-8") == schema_text(), (
        "run `uv run python -m revint.api.openapi` and commit docs/openapi.json"
    )


def test_ac10_the_schema_lists_only_the_poc_endpoints() -> None:
    paths = set(json.loads(schema_text())["paths"])
    assert paths == {
        f"{API}/health",
        f"{API}/definitions",
        f"{API}/overview",
        f"{API}/opportunities",
        f"{API}/opportunities/{{opp_id}}",
        f"{API}/opportunities/{{opp_id}}/brief",  # story #138
        f"{API}/auth/login",  # story #191
        f"{API}/auth/logout",
        f"{API}/auth/me",
    }


# AC11 ------


def test_ac11_every_ac_has_a_test_in_this_module() -> None:
    text = Path(__file__).read_text(encoding="utf-8")
    for ac in range(1, 11):
        assert f"def test_ac{ac}_" in text
