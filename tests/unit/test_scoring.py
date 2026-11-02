"""Story #113: scoring, priority, confidence and rank (spec 03 section 4, FR-O5).

Synthetic data only. Two fixtures are reused: the whitespace data (one engine, with a peer group
still below the minimum size) and the dormancy data (known intervals and days quiet). Component
values are checked against the SQL by recomputing the score from them.
"""

from __future__ import annotations

import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import test_dormancy
import test_whitespace
from gold_helpers import variant
from silver_helpers import bronze_row, build, query

from revint.config import Settings, load_settings
from revint.gold import run_gold
from revint.opportunities import OPPORTUNITY_COLUMNS, run_opportunities, with_asof

ASOF = date(2020, 2, 29)


def built_from(rows: list[dict], root: Path) -> Settings:
    settings = load_settings(
        env={
            "REVINT_PATHS_WAREHOUSE": str(root / "warehouse.duckdb"),
            "REVINT_PATHS_BRONZE": str(root / "bronze"),
        }
    )
    build(settings, rows)
    run_gold(settings)
    return settings


@pytest.fixture(scope="module")
def whitespace_built(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    return built_from(test_whitespace.DATA.rows, tmp_path_factory.mktemp("score_ws"))


@pytest.fixture(scope="module")
def dormancy_built(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    return built_from(test_dormancy.DATA.rows, tmp_path_factory.mktemp("score_dorm"))


def run(built: Settings, tmp_path: Path, **sections: dict) -> Settings:
    tmp_path.mkdir(parents=True, exist_ok=True)
    shutil.copy(built.paths.warehouse, tmp_path / "warehouse.duckdb")
    source = load_settings(env={"REVINT_PATHS_WAREHOUSE": str(tmp_path / "warehouse.duckdb")})
    peer = {"min_size": 3, **sections.pop("peer_groups", {})}
    settings = with_asof(variant(tmp_path, source, peer_groups=peer, **sections), ASOF)
    run_opportunities(settings)
    return settings


def opportunities(settings: Settings) -> list[tuple]:
    return query(
        settings,
        "select opp_id, type, customer_key, category, score, priority, confidence, rank, "
        "value_high, reason_codes from opp_opportunities order by rank",
    )


@pytest.fixture
def ws(whitespace_built: Settings, tmp_path: Path) -> Settings:
    return run(whitespace_built, tmp_path)


@pytest.fixture
def dorm(dormancy_built: Settings, tmp_path: Path) -> Settings:
    return run(dormancy_built, tmp_path)


# AC1: the weighted sum of four components ------


def test_ac1_opp_opportunities_holds_every_engine_row(ws: Settings) -> None:
    assert query(ws, "select count(*) from opp_opportunities") == query(
        ws, "select count(*) from opp_whitespace"
    )
    columns = [
        c
        for (c,) in query(
            ws,
            "select column_name from information_schema.columns "
            "where table_name = 'opp_opportunities' order by ordinal_position",
        )
    ]
    assert columns == list(OPPORTUNITY_COLUMNS)


def test_ac1_the_whitespace_score(ws: Settings) -> None:
    # M5 for B: penetration 1.0 (evidence), urgency 0.5, data quality 1.0 (no flagged line).
    # Value: M5/B's gap 25 ranked among the six whitespace gaps (percent_rank r).
    gaps = sorted(g for (g,) in query(ws, "select gap from opp_value"))
    k = query(ws, "select customer_key from dim_customer where customer_code = 'SECRET-M5'")
    ((score, gap),) = query(
        ws,
        "select o.score, v.gap from opp_opportunities o join opp_value v using (opp_id) "
        "where o.customer_key = ? and o.category = 'SECRET-B'",
        k[0][0],
    )
    below = sum(1 for g in gaps if g < gap)
    r = below / (len(gaps) - 1)
    expected = round(100 * (0.4 * r + 0.3 * 1.0 + 0.2 * 0.5 + 0.1 * 1.0), 2)
    assert score == Decimal(str(expected)).quantize(Decimal("0.0001"))


def test_ac1_the_dormancy_evidence_and_urgency(dorm: Settings) -> None:
    # DORMANT: 100 days quiet, interval 30: evidence min(1, 100/30) = 1; urgency 1 - 100/365.
    rows = query(
        dorm,
        "select o.score, v.gap, d.days_since_last_order, d.median_interval_days "
        "from opp_opportunities o join opp_value v using (opp_id) "
        "join opp_dormancy d using (opp_id) join dim_customer c on o.customer_key = c.customer_key "
        "where c.customer_code = 'SECRET-DORMANT'",
    )
    ((score, gap, days, interval),) = rows
    gaps = sorted(g for (g,) in query(dorm, "select gap from opp_value"))
    r = sum(1 for g in gaps if g < gap) / (len(gaps) - 1)
    evidence = min(1.0, days / float(interval))
    urgency = 1 - min(1.0, days / 365)
    expected = round(100 * (0.4 * r + 0.3 * evidence + 0.2 * urgency + 0.1 * 1.0), 2)
    assert score == Decimal(str(expected)).quantize(Decimal("0.0001"))


def test_ac1_data_quality_counts_flagged_lines(tmp_path: Path) -> None:
    # Q1 has 4 lines, one with a negative value: data quality 0.75 lowers its score
    rows = []
    n = 8
    for customer, nets in (("Q1", ["10", "10", "10", "-1"]), ("Q2", ["10", "10", "10", "10"])):
        for i, net in enumerate(nets):
            rows.append(
                bronze_row(
                    n,
                    OrderReference=f"O{n}",
                    CustomerCode=f"SECRET-{customer}",
                    Customer="SECRET-name",
                    SCJ_CODE_1="PA",
                    Internal_Category="SECRET-A",
                    Branch_Name="Magway",
                    Channel_Category="GT",
                    Date=f"2019-0{i + 1}-10",
                    Net_Amount_2=net,
                    **{"Quantity(PCS)": "1"},
                )
            )
            n += 1
    built = built_from(rows, tmp_path / "b")
    got = run(
        built,
        tmp_path / "r",
        scoring={
            "weight_value": 0,
            "weight_evidence": 0,
            "weight_urgency": 0,
            "weight_data_quality": 1,
        },
    )
    scores = dict(
        query(
            got,
            "select c.customer_code, o.score from opp_opportunities o "
            "join dim_customer c using (customer_key) where o.type = 'dormancy'",
        )
    )
    assert scores == {"SECRET-Q1": Decimal("75"), "SECRET-Q2": Decimal("100")}


def test_ac1_the_weights_are_applied(whitespace_built: Settings, tmp_path: Path) -> None:
    got = run(
        whitespace_built,
        tmp_path,
        scoring={
            "weight_value": 0,
            "weight_evidence": 0,
            "weight_urgency": 1,
            "weight_data_quality": 0,
        },
    )
    # urgency only: every whitespace row scores 100 x 0.5
    assert {s for (s,) in query(got, "select score from opp_opportunities")} == {Decimal("50")}


# AC2: priority and confidence from the config cut-offs ------


def test_ac2_priority_follows_the_cut_offs(ws: Settings) -> None:
    for _opp, _t, _c, _cat, score, priority, *_ in opportunities(ws):
        want = "High" if score >= 70 else "Medium" if score >= 40 else "Low"
        assert priority == want, score


def test_ac2_confidence_is_the_lower_of_evidence_and_data_quality(ws: Settings) -> None:
    rows = query(
        ws,
        "select o.confidence, w.peer_penetration, w.f_below_min_size from opp_opportunities o "
        "join opp_whitespace w using (opp_id)",
    )
    for confidence, penetration, small in rows:
        lower = min(float(penetration), 1.0)  # data quality is 1 in this fixture
        want = "High" if lower >= 0.7 else "Medium" if lower >= 0.4 else "Low"
        if small and want == "High":
            want = "Medium"
        assert confidence == want, (penetration, small)


def test_ac2_changed_cut_offs_change_priority(whitespace_built: Settings, tmp_path: Path) -> None:
    got = run(whitespace_built, tmp_path, scoring={"priority_high": 99, "priority_medium": 98})
    assert {p for (p,) in query(got, "select priority from opp_opportunities")} == {"Low"}


# AC3: the confidence cap ------


def test_ac3_a_small_fallback_group_caps_confidence(ws: Settings) -> None:
    # P2 for B: penetration 1.0, data quality 1.0, but its group is below the minimum size
    ((confidence, reasons),) = query(
        ws,
        "select o.confidence, o.reason_codes from opp_opportunities o "
        "join dim_customer c using (customer_key) where c.customer_code = 'SECRET-P2'",
    )
    assert confidence == "Medium"
    assert "confidence_capped" in reasons


def test_ac3_a_full_group_with_strong_evidence_is_high(ws: Settings) -> None:
    ((confidence,),) = query(
        ws,
        "select o.confidence from opp_opportunities o join dim_customer c using (customer_key) "
        "where c.customer_code = 'SECRET-M5' and o.category = 'SECRET-B'",
    )
    assert confidence == "High"


def test_ac3_a_multi_identity_customer_is_capped(ws: Settings) -> None:
    # mark M5 as multi-identity in dim_customer and score again on the same warehouse
    import duckdb

    con = duckdb.connect(str(ws.paths.warehouse))
    con.execute("update dim_customer set f_multi_identity = true where customer_code = 'SECRET-M5'")
    con.close()
    run_opportunities(ws)
    rows = query(
        ws,
        "select o.confidence from opp_opportunities o join dim_customer c using (customer_key) "
        "where c.customer_code = 'SECRET-M5'",
    )
    assert {c for (c,) in rows} <= {"Medium", "Low"}
    assert ("Medium",) in rows


# AC4: rank is deterministic ------


def test_ac4_rank_orders_by_score_then_value_high_then_customer(ws: Settings) -> None:
    rows = opportunities(ws)
    assert [r[7] for r in rows] == list(range(1, len(rows) + 1))
    keys = [(-r[4], -(r[8] or 0), r[2]) for r in rows]
    assert keys == sorted(keys)


def test_ac4_two_runs_give_the_same_order(whitespace_built: Settings, tmp_path: Path) -> None:
    first = opportunities(run(whitespace_built, tmp_path / "a"))
    second = opportunities(run(whitespace_built, tmp_path / "b"))
    assert first == second


# AC5: never null ------


def test_ac5_score_priority_and_confidence_are_never_null(ws: Settings, dorm: Settings) -> None:
    for settings in (ws, dorm):
        assert query(
            settings,
            "select count(*) from opp_opportunities where score is null or priority is null "
            "or confidence is null or rank is null",
        ) == [(0,)]


def test_ac5_scores_are_between_0_and_100(ws: Settings, dorm: Settings) -> None:
    for settings in (ws, dorm):
        ((low, high),) = query(settings, "select min(score), max(score) from opp_opportunities")
        assert 0 <= low <= high <= 100


# AC6: config changes the scores ------


def test_ac6_a_changed_weight_changes_the_scores(
    whitespace_built: Settings, tmp_path: Path
) -> None:
    base = {r[0]: r[4] for r in opportunities(run(whitespace_built, tmp_path / "a"))}
    changed = {
        r[0]: r[4]
        for r in opportunities(
            run(
                whitespace_built,
                tmp_path / "b",
                scoring={
                    "weight_value": 0.1,
                    "weight_evidence": 0.6,
                    "weight_urgency": 0.2,
                    "weight_data_quality": 0.1,
                },
            )
        )
    }
    assert base.keys() == changed.keys()
    assert base != changed


def test_ac6_the_neutral_urgency_is_config(whitespace_built: Settings, tmp_path: Path) -> None:
    got = run(
        whitespace_built,
        tmp_path,
        scoring={
            "weight_value": 0,
            "weight_evidence": 0,
            "weight_urgency": 1,
            "weight_data_quality": 0,
            "urgency_neutral": 0.8,
        },
    )
    assert {s for (s,) in query(got, "select score from opp_opportunities")} == {Decimal("80")}


def test_ac6_the_urgency_horizon_is_config(dormancy_built: Settings, tmp_path: Path) -> None:
    weights = {
        "weight_value": 0,
        "weight_evidence": 0,
        "weight_urgency": 1,
        "weight_data_quality": 0,
    }
    short = run(dormancy_built, tmp_path / "a", scoring={**weights, "urgency_horizon_days": 100})
    # 100 days quiet with a 100-day horizon: urgency 0
    assert query(
        short,
        "select o.score from opp_opportunities o join dim_customer c using (customer_key) "
        "where c.customer_code = 'SECRET-DORMANT'",
    ) == [(Decimal("0"),)]


# AC7 and the real file ------


def test_ac7_every_ac_has_a_test_in_this_module() -> None:
    text = Path(__file__).read_text(encoding="utf-8")
    for ac in range(1, 7):
        assert f"def test_ac{ac}_" in text


@pytest.mark.realdata
def test_ac1_ac5_real_file_scoring(tmp_path: Path) -> None:
    """Counts only, on a copy of the built warehouse."""
    real = load_settings()
    if not real.paths.warehouse.is_file():
        pytest.skip("warehouse not built: run `uv run revint build all` first")
    shutil.copy(real.paths.warehouse, tmp_path / "w.duckdb")
    copy = load_settings(env={"REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb")})
    run_opportunities(copy)
    engines = query(
        copy,
        "select (select count(*) from opp_dormancy) + (select count(*) from opp_recovery) + "
        "(select count(*) from opp_whitespace) + (select count(*) from opp_crosssell)",
    )
    assert query(copy, "select count(*) from opp_opportunities") == engines
    assert query(
        copy,
        "select count(*) from opp_opportunities where score is null or priority is null "
        "or confidence is null",
    ) == [(0,)]
    assert query(copy, "select count(distinct rank) = count(*) from opp_opportunities") == [(True,)]
