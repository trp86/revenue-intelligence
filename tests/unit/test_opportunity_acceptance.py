"""Story #115: the cross-engine acceptance checks of spec 03 section 8.

One synthetic warehouse with a customer for each case, run through `run_opportunities`, the
module `revint opportunities build` wires (E3-13). As of 2020-02-29. Every customer buys
category A, so no pair with A has a lift above 1 and cross-sell fires only on its own case. The
peer groups are the branches (channel GT for all):
- Magway (dormancy): DORM is quiet 100 days on a 30-day interval and triggers; D_EDGE is quiet
  exactly 60 days on a 30-day interval (at the limit) and does not; D_ACT1 and D_ACT2 are active.
- PYAY (recovery): REC fell 50 percent on last year; REC_EDGE fell 19.99 percent (just under 20)
  and does not trigger; R_STEADY is flat. BOTH stopped buying in May 2019: it meets the
  recovery and the dormancy rule, and dormancy owns it (so dormancy has two customers).
- BW (whitespace): W1, W2 and W3 buy A and B; WS buys only A, so B is whitespace for it.
- BX (cross-sell): X1..X4 buy A, D and E; XS (alone in branch BX2, so it has no peers for
  whitespace) buys A and D, so D -> E is a cross-sell for it.
Settings for the case sizes: recovery.min_prior_sales 100, peer_groups.min_size 3,
crosssell.min_support 3 (the other limits are the defaults). Synthetic data only.
"""

from __future__ import annotations

import shutil
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pytest
from gold_helpers import variant
from silver_helpers import bronze_row, build, query

from revint.config import Settings, load_settings
from revint.gold import run_gold
from revint.opportunities import ENGINES, run_opportunities, with_asof

S = "SECRET-"
ASOF = date(2020, 2, 29)
SECTIONS = {
    "recovery": {"min_prior_sales": 100},
    "peer_groups": {"min_size": 3},
    "crosssell": {"min_support": 3},
}
EXPECTED = {
    "dormancy": ["BOTH", "DORM"],
    "recovery": ["REC"],
    "whitespace": ["WS"],
    "crosssell": ["XS"],
}
NEAR = ("D_EDGE", "REC_EDGE")
OUTPUTS = ("opp_opportunities", "opp_evidence", "opp_run_summary", *(f"opp_{e}" for e in ENGINES))


class Rows:
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.n = 8

    def sale(
        self,
        customer: str,
        day: date,
        category: str = "A",
        net: str = "100",
        branch: str = "Magway",
    ) -> None:
        self.rows.append(
            bronze_row(
                self.n,
                OrderReference=f"O{self.n}",
                CustomerCode=f"{S}{customer}",
                Customer=f"{S}name",
                SCJ_CODE_1=f"P{category}",
                Internal_Category=f"{S}{category}",
                Branch_Name=branch,
                Channel_Category="GT",
                Date=day.isoformat(),
                Net_Amount_2=net,
                **{"Quantity(PCS)": "1"},
            )
        )
        self.n += 1


def last_at(last: date, step: int, count: int) -> list[date]:
    return [last - timedelta(days=step * (count - 1 - i)) for i in range(count)]


def rows() -> list[dict]:
    r = Rows()
    for day in last_at(ASOF - timedelta(days=100), 30, 5):
        r.sale("DORM", day)
    for day in last_at(ASOF - timedelta(days=60), 30, 5):
        r.sale("D_EDGE", day)
    for name in ("D_ACT1", "D_ACT2"):
        for day in last_at(ASOF - timedelta(days=5), 20, 6):
            r.sale(name, day)
    prior = [date(2018, 12, 10), date(2019, 1, 10), date(2019, 2, 10)]
    current = [date(2019, 12, 10), date(2020, 1, 10), date(2020, 2, 10)]
    for name, now in (("REC", "50"), ("REC_EDGE", "80.01"), ("R_STEADY", "100")):
        for day in prior:
            r.sale(name, day, branch="PYAY")
        for day in current:
            r.sale(name, day, net=now, branch="PYAY")
    # BOTH: monthly Dec 2018 to May 2019, then quiet (meets the dormancy and recovery rules)
    for month in (date(2018, 12, 15), *(date(2019, m, 15) for m in range(1, 6))):
        r.sale("BOTH", month, branch="PYAY")
    recent = [date(2020, 1, 10), date(2020, 2, 10)]
    for name in ("W1", "W2", "W3", "WS"):
        for day in recent:
            r.sale(name, day, branch="BW")
            if name != "WS":
                r.sale(name, day, category="B", branch="BW")
    for name, branch in (("X1", "BX"), ("X2", "BX"), ("X3", "BX"), ("X4", "BX"), ("XS", "BX2")):
        for day in recent:
            r.sale(name, day, branch=branch)
            r.sale(name, day, category="D", branch=branch)
            if name != "XS":
                r.sale(name, day, category="E", branch=branch)
    return r.rows


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    root = tmp_path_factory.mktemp("acceptance")
    settings = load_settings(
        env={
            "REVINT_PATHS_WAREHOUSE": str(root / "warehouse.duckdb"),
            "REVINT_PATHS_BRONZE": str(root / "bronze"),
        }
    )
    build(settings, rows())
    run_gold(settings)
    return settings


def copied(built: Settings, tmp_path: Path, **overrides: dict) -> Settings:
    tmp_path.mkdir(parents=True, exist_ok=True)
    shutil.copy(built.paths.warehouse, tmp_path / "warehouse.duckdb")
    source = load_settings(env={"REVINT_PATHS_WAREHOUSE": str(tmp_path / "warehouse.duckdb")})
    sections = {k: {**v} for k, v in SECTIONS.items()}
    for name, keys in overrides.items():
        sections[name] = {**sections.get(name, {}), **keys}
    return with_asof(variant(tmp_path, source, **sections), ASOF)


def run(built: Settings, tmp_path: Path, **overrides: dict) -> Settings:
    settings = copied(built, tmp_path, **overrides)
    run_opportunities(settings)
    return settings


def snapshot(settings: Settings) -> dict[str, list]:
    return {t: query(settings, f"select * from {t} order by all") for t in OUTPUTS}


def triggered(settings: Settings) -> dict[str, list[str]]:
    rows = query(
        settings,
        "select o.type, c.customer_code from opp_opportunities o "
        "join dim_customer c using (customer_key) order by 1, 2",
    )
    out: dict[str, list[str]] = {e: [] for e in ENGINES}
    for engine, code in rows:
        out[engine].append(code.removeprefix(S))
    return out


@pytest.fixture
def result(built: Settings, tmp_path: Path) -> Settings:
    return run(built, tmp_path)


# AC1: deterministic ------


def test_ac1_two_runs_are_identical(built: Settings, tmp_path: Path) -> None:
    first = snapshot(run(built, tmp_path / "a"))
    second = snapshot(run(built, tmp_path / "b"))
    assert first == second
    assert first["opp_opportunities"]  # the run is not empty


def test_ac1_a_rerun_on_the_same_warehouse_is_identical(result: Settings) -> None:
    before = snapshot(result)
    run_opportunities(result)
    assert snapshot(result) == before


def test_ac1_ids_and_ranks_are_stable(built: Settings, tmp_path: Path) -> None:
    sql = "select opp_id, rank from opp_opportunities order by rank"
    assert query(run(built, tmp_path / "a"), sql) == query(run(built, tmp_path / "b"), sql)


# AC2: data after the as-of date changes nothing ------


def poison(settings: Settings, offset: int = 100_000) -> None:
    """Copy every sales line to 15 June 2020, after the as-of date, with net sales 1000 times
    larger: a day for it in dim_date, the lines in the view's table and in the fact. The copies
    get sales_line_id + `offset`, which must be above every real id."""
    con = duckdb.connect(str(settings.paths.warehouse))
    try:
        ((top,),) = con.execute("select max(sales_line_id) from fact_sales").fetchall()
        assert top < offset, "the poison offset must be above every sales line id"
        con.execute(
            "insert into dim_date select * replace (20200615 as date_key, "
            "date '2020-06-15' as date, date '2020-06-01' as month_start, 6 as month, "
            "2 as quarter) from dim_date where date_key = 20200110"
        )
        con.execute(
            "insert into gold_net_sales_lines by name "
            "select sales_line_id + $offset as sales_line_id, net_sales * 1000 as net_sales, "
            "net_sales_field_used, included, quantity, "
            "columns('^amount_') from gold_net_sales_lines",
            {"offset": offset},
        )
        con.execute(
            "insert into fact_sales by name select * replace ("
            "sales_line_id + $offset as sales_line_id, net_sales * 1000 as net_sales, "
            "20200615 as date_key) from fact_sales",
            {"offset": offset},
        )
    finally:
        con.close()


def test_ac2_poison_rows_after_the_as_of_date_change_no_output(
    built: Settings, tmp_path: Path
) -> None:
    clean = snapshot(run(built, tmp_path / "clean"))
    poisoned = copied(built, tmp_path / "poisoned")
    poison(poisoned)
    lines = query(poisoned, "select count(*) from fact_sales where date_key = 20200615")
    assert lines[0][0] > 0
    run_opportunities(poisoned)
    assert snapshot(poisoned) == clean


def test_ac2_the_poison_is_seen_with_a_later_as_of_date(built: Settings, tmp_path: Path) -> None:
    # the check above would pass trivially if the poison were never read: here it is
    poisoned = copied(built, tmp_path)
    poison(poisoned)
    later = with_asof(poisoned, date(2020, 6, 30))
    run_opportunities(later)
    # the poison's June 2020 orders make the dormant customer active again
    assert "DORM" in triggered(run(built, tmp_path / "clean"))["dormancy"]
    assert "DORM" not in triggered(later)["dormancy"]


# AC3: config changes results ------


@pytest.mark.parametrize(
    ("section", "keys", "engine"),
    [
        ("dormancy", {"min_days": 150}, "dormancy"),
        ("recovery", {"min_decline_pct": 60}, "recovery"),
        # BW (4 customers) falls back to channel GT, where few peers buy B
        ("peer_groups", {"min_size": 5}, "whitespace"),
        ("crosssell", {"min_lift": 10.0}, "crosssell"),
    ],
)
def test_ac3_a_changed_threshold_changes_the_results(
    built: Settings, tmp_path: Path, section: str, keys: dict, engine: str
) -> None:
    base = triggered(run(built, tmp_path / "base"))
    changed = triggered(run(built, tmp_path / "changed", **{section: keys}))
    assert base[engine] == EXPECTED[engine]
    assert changed[engine] != base[engine]


def test_ac3_whitespace_at_penetration_1_still_triggers(built: Settings, tmp_path: Path) -> None:
    # WS's peers all buy B (3 of 3): at the limit 1.0 it is still whitespace
    got = triggered(run(built, tmp_path, whitespace={"min_peer_penetration": 1.0}))
    assert got["whitespace"] == ["WS"]


# AC4: one customer per engine; the near-threshold customers trigger none ------


def test_ac4_each_engine_triggers_exactly_its_customer(result: Settings) -> None:
    assert triggered(result) == EXPECTED


def test_ac4_the_near_threshold_customers_trigger_nothing(result: Settings) -> None:
    flagged = {code for codes in triggered(result).values() for code in codes}
    assert not flagged & set(NEAR)


def test_ac4_the_run_summary_agrees(result: Settings) -> None:
    rows = dict(query(result, "select type, n_triggered from opp_run_summary"))
    assert rows == {engine: len(codes) for engine, codes in EXPECTED.items()}


# AC5: complete rows ------


def test_ac5_every_row_is_complete(result: Settings) -> None:
    assert query(
        result,
        "select count(*) from opp_opportunities o where o.score is null or o.priority is null "
        "or o.confidence is null or (o.value_level is null and "
        "(o.value_low is null or o.value_high is null)) "
        "or not exists (select 1 from opp_evidence e where e.opp_id = o.opp_id)",
    ) == [(0,)]
    total = sum(len(codes) for codes in EXPECTED.values())
    assert query(result, "select count(*) from opp_opportunities") == [(total,)]


# AC6: recovery and dormancy never share a customer ------


def test_ac6_no_customer_is_in_both_recovery_and_dormancy(result: Settings) -> None:
    assert query(
        result,
        "select count(*) from opp_recovery r join opp_dormancy d "
        "on r.customer_key = d.customer_key and r.as_of_date = d.as_of_date",
    ) == [(0,)]


def test_ac6_a_customer_that_meets_both_rules_is_left_to_dormancy(result: Settings) -> None:
    # BOTH ordered monthly from Dec 2018 to May 2019 and then stopped: its sales fell 100
    # percent on last year (recovery) and it is quiet far past its interval (dormancy)
    outcomes = dict(
        query(
            result,
            "select e.type, e.outcome from opp_evaluations e join dim_customer c "
            "using (customer_key) where c.customer_code = ?",
            f"{S}BOTH",
        )
    )
    assert outcomes["dormancy"] == "triggered"
    assert outcomes["recovery"] == "dormant"


# AC7 ------


def test_ac7_every_ac_has_a_test_in_this_module() -> None:
    text = Path(__file__).read_text(encoding="utf-8")
    for ac in range(1, 7):
        assert f"def test_ac{ac}_" in text
