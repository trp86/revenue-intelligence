"""Story #114: evidence rows of the opportunities (spec 03 section 2).

Synthetic data only; customer codes and categories carry a SECRET- marker to prove none reaches
opp_evidence. The dormancy, recovery, whitespace and cross-sell fixtures are reused, so every
engine has opportunities.
"""

from __future__ import annotations

import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import test_crosssell
import test_dormancy
import test_recovery
import test_whitespace
from gold_helpers import variant
from silver_helpers import build, query

from revint.config import Settings, load_settings
from revint.data_dictionary import load_definitions, load_evidence_definitions
from revint.gold import run_gold
from revint.opportunities import run_opportunities, with_asof

ASOF = date(2020, 2, 29)
FACTS = {
    "dormancy": {
        "days_since_last_order",
        "median_interval_days",
        "n_orders",
        "last_order_date",
        "lookback_net_sales",
    },
    "recovery": {"prior_net_sales", "current_net_sales", "prior_orders", "decline_pct"},
    "whitespace": {"n_peers", "n_buying_peers", "peer_penetration", "peer_median_net_sales"},
    "crosssell": {"support", "confidence", "lift", "median_b_net_sales"},
}
ESTIMATES = {"value_low", "value_high"}
FIXTURES = {
    "dormancy": (test_dormancy.DATA.rows, {}),
    "recovery": (test_recovery.DATA.rows, {"recovery": {"min_prior_sales": 100}}),
    "whitespace": (test_whitespace.DATA.rows, {"peer_groups": {"min_size": 3}}),
    "crosssell": (
        test_crosssell.DATA.rows,
        {"crosssell": {"min_support": 3, "min_confidence": 0.3, "min_lift": 1.0}},
    ),
}


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Settings]:
    out = {}
    for engine, (rows, _sections) in FIXTURES.items():
        root = tmp_path_factory.mktemp(f"evidence_{engine}")
        settings = load_settings(
            env={
                "REVINT_PATHS_WAREHOUSE": str(root / "warehouse.duckdb"),
                "REVINT_PATHS_BRONZE": str(root / "bronze"),
            }
        )
        build(settings, rows)
        run_gold(settings)
        out[engine] = settings
    return out


@pytest.fixture(scope="module")
def runs(built: dict[str, Settings], tmp_path_factory: pytest.TempPathFactory) -> dict:
    out = {}
    for engine, source in built.items():
        root = tmp_path_factory.mktemp(f"evidence_run_{engine}")
        shutil.copy(source.paths.warehouse, root / "warehouse.duckdb")
        base = load_settings(env={"REVINT_PATHS_WAREHOUSE": str(root / "warehouse.duckdb")})
        settings = with_asof(variant(root, base, **FIXTURES[engine][1]), ASOF)
        run_opportunities(settings)
        out[engine] = settings
    return out


def evidence(settings: Settings, engine: str) -> list[tuple]:
    return query(
        settings,
        "select e.opp_id, e.fact, e.value_number, e.value_date, e.unit, e.kind, e.definition_id "
        "from opp_evidence e join opp_opportunities o using (opp_id) where o.type = ? "
        "order by 1, 2",
        engine,
    )


# AC1: long-form rows ------


def test_ac1_the_table_is_long_form(runs: dict) -> None:
    columns = [
        c
        for (c,) in query(
            runs["dormancy"],
            "select column_name from information_schema.columns "
            "where table_name = 'opp_evidence' order by ordinal_position",
        )
    ]
    assert columns == [
        "opp_id",
        "fact",
        "value_number",
        "value_date",
        "unit",
        "kind",
        "definition_id",
    ]


def test_ac1_each_row_has_one_value_and_a_unit(runs: dict) -> None:
    for engine, settings in runs.items():
        for _opp, fact, number, day, unit, kind, definition in evidence(settings, engine):
            assert (number is None) != (day is None), (engine, fact)
            assert unit and kind in {"Measured", "Estimate"} and definition == f"ev_{fact}"


def test_ac1_a_known_dormancy_row(runs: dict) -> None:
    settings = runs["dormancy"]
    ((opp,),) = query(
        settings,
        "select o.opp_id from opp_opportunities o join dim_customer c using (customer_key) "
        "where c.customer_code = 'SECRET-DORMANT'",
    )
    got = {
        fact: (number, day, unit)
        for o, fact, number, day, unit, _k, _d in evidence(settings, "dormancy")
        if o == opp
    }
    assert got["days_since_last_order"] == (Decimal("100.0000"), None, "days")
    assert got["median_interval_days"] == (Decimal("30.0000"), None, "days")
    assert got["last_order_date"] == (None, test_dormancy.QUIET_100, "date")
    assert got["value_low"] == (Decimal("12.5000"), None, "net sales")  # 0.25 x 50


# AC2: every opportunity has evidence; every definition id exists ------


def test_ac2_every_opportunity_has_evidence(runs: dict) -> None:
    for engine, settings in runs.items():
        missing = query(
            settings,
            "select count(*) from opp_opportunities o "
            "where not exists (select 1 from opp_evidence e where e.opp_id = o.opp_id)",
        )
        assert missing == [(0,)], engine
        assert query(settings, "select count(*) from opp_opportunities")[0][0] > 0, engine


def test_ac2_every_definition_id_is_in_the_definitions_file(runs: dict) -> None:
    known = {d.id for d in load_evidence_definitions()}
    for engine, settings in runs.items():
        used = {d for (d,) in query(settings, "select distinct definition_id from opp_evidence")}
        assert used <= known, (engine, sorted(used - known))


def test_ac2_every_listed_fact_has_a_definition(runs: dict) -> None:
    known = {d.id for d in load_evidence_definitions()}
    listed = {d for (d,) in query(runs["dormancy"], "select definition_id from opp_evidence_facts")}
    assert listed == known


def test_ac2_the_evidence_ids_do_not_change_the_gold_definitions() -> None:
    gold = {d.id for d in load_definitions()}
    assert not any(i.startswith("ev_") for i in gold)


# AC3: the facts each rule used ------


@pytest.mark.parametrize("engine", list(FACTS))
def test_ac3_each_engine_has_its_measured_facts(runs: dict, engine: str) -> None:
    rows = evidence(runs[engine], engine)
    per_opp: dict[str, set[str]] = {}
    for opp, fact, *_ in rows:
        per_opp.setdefault(opp, set()).add(fact)
    assert per_opp
    for facts in per_opp.values():
        assert facts == FACTS[engine] | ESTIMATES


def test_ac3_the_value_range_is_an_estimate_and_the_rest_measured(runs: dict) -> None:
    for engine, settings in runs.items():
        for _opp, fact, _n, _d, _u, kind, _def in evidence(settings, engine):
            assert kind == ("Estimate" if fact in ESTIMATES else "Measured"), (engine, fact)


def test_ac3_the_evidence_matches_the_engine_table(runs: dict) -> None:
    settings = runs["crosssell"]
    rows = query(
        settings,
        "select c.support, c.confidence, c.lift, "
        "max(e.value_number) filter (where e.fact = 'support'), "
        "max(e.value_number) filter (where e.fact = 'confidence'), "
        "max(e.value_number) filter (where e.fact = 'lift') "
        "from opp_crosssell c join opp_evidence e using (opp_id) group by all",
    )
    for support, confidence, lift, e_support, e_confidence, e_lift in rows:
        assert (Decimal(support), confidence, lift) == (e_support, e_confidence, e_lift)


# AC4: counts, amounts and dates only ------


def test_ac4_no_customer_name_code_or_free_text(runs: dict) -> None:
    for engine, settings in runs.items():
        text = repr(query(settings, "select * from opp_evidence"))
        assert "SECRET-" not in text, engine


def test_ac4_the_text_columns_are_from_a_fixed_list(runs: dict) -> None:
    for engine, settings in runs.items():
        bad = query(
            settings,
            "select count(*) from opp_evidence e left join opp_evidence_facts f "
            "on e.fact = f.fact and e.unit = f.unit and e.kind = f.kind "
            "and e.definition_id = f.definition_id where f.fact is null",
        )
        assert bad == [(0,)], engine


def test_ac4_the_value_columns_are_a_number_and_a_date(runs: dict) -> None:
    types = dict(
        query(
            runs["dormancy"],
            "select column_name, data_type from information_schema.columns "
            "where table_name = 'opp_evidence'",
        )
    )
    assert types["value_number"].startswith("DECIMAL")
    assert types["value_date"] == "DATE"


# AC5 and the real file ------


def test_ac5_every_ac_has_a_test_in_this_module() -> None:
    text = Path(__file__).read_text(encoding="utf-8")
    for ac in range(1, 5):
        assert f"def test_ac{ac}_" in text


@pytest.mark.realdata
def test_ac2_ac3_real_file_evidence(tmp_path: Path) -> None:
    """Counts only, on a copy of the built warehouse."""
    real = load_settings()
    if not real.paths.warehouse.is_file():
        pytest.skip("warehouse not built: run `uv run revint build all` first")
    shutil.copy(real.paths.warehouse, tmp_path / "w.duckdb")
    copy = load_settings(env={"REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb")})
    run_opportunities(copy)
    assert query(
        copy,
        "select count(*) from opp_opportunities o "
        "where not exists (select 1 from opp_evidence e where e.opp_id = o.opp_id)",
    ) == [(0,)]
    known = {d.id for d in load_evidence_definitions()}
    used = {d for (d,) in query(copy, "select distinct definition_id from opp_evidence")}
    assert used <= known


def test_ac2_an_evidence_id_that_clashes_with_a_gold_id_fails(tmp_path: Path) -> None:
    from revint.data_dictionary import DictionaryError

    path = tmp_path / "definitions.yaml"
    entry = "  - id: net_sales\n    kind: metric\n    text: x\n    applies_to: [a.b]\n"
    path.write_text(f"definitions:\n{entry}evidence:\n{entry}", encoding="utf-8")
    with pytest.raises(DictionaryError, match="net_sales"):
        load_evidence_definitions(path)
