"""Story #109: the recovery engine (spec 03 section 3.1, FR-O1).

Synthetic data only; customer codes carry a SECRET- marker. Silver and gold are built once per
module; each test copies the warehouse and runs the opportunity stage on its own copy. As of
2020-02-29 with window_months 3, the current window is 2019-12-01 to 2020-02-29 and the prior
window 2018-12-01 to 2019-02-28. Tests set min_prior_sales 100 so small synthetic amounts
count; the other limits are the defaults (decline 20 percent, 3 prior orders).
"""

from __future__ import annotations

import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from gold_helpers import variant
from silver_helpers import bronze_row, build, query

from revint.config import Settings, load_settings
from revint.gold import run_gold
from revint.opportunities import opp_id, run_opportunities, with_asof

S = "SECRET-"
ASOF = date(2020, 2, 29)
PRIOR = ("2018-12-10", "2019-01-10", "2019-02-10")
CURRENT = ("2019-12-10", "2020-01-10", "2020-02-10")


class Rows:
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.n = 8

    def orders(self, customer: str | None, days: tuple[str, ...] | list[str], net: str) -> None:
        for day in days:
            self.rows.append(
                bronze_row(
                    self.n,
                    OrderReference=f"O{self.n}",
                    CustomerCode=f"{S}{customer}" if customer else None,
                    Customer=f"{S}name" if customer else None,
                    SCJ_CODE_1="PA",
                    Internal_Category=f"{S}A",
                    Branch_Name="Magway",
                    Channel_Category="GT",
                    Date=day,
                    Net_Amount_2=net,
                    **{"Quantity(PCS)": "1"},
                )
            )
            self.n += 1


DATA = Rows()
# DECLINE: prior 3 x 100 = 300, current 3 x 50 = 150: decline 50 percent, gap 150
DATA.orders("DECLINE", PRIOR, "100")
DATA.orders("DECLINE", CURRENT, "50")
# STEADY: same both years
DATA.orders("STEADY", PRIOR, "100")
DATA.orders("STEADY", CURRENT, "100")
# EDGE: prior 300, current 240.03: decline 19.99 percent, just under 20
DATA.orders("EDGE", PRIOR, "100")
DATA.orders("EDGE", CURRENT, "80.01")
# AT20: prior 300, current 240: decline exactly 20 percent triggers (at least)
DATA.orders("AT20", PRIOR, "100")
DATA.orders("AT20", CURRENT, "80")
# TWO_ORDERS: big decline, but only 2 prior orders
DATA.orders("TWO_ORDERS", PRIOR[:2], "100")
DATA.orders("TWO_ORDERS", CURRENT[:1], "1")
# SMALL: prior 3 x 33.33 = 99.99, below min_prior_sales 100 in the tests
DATA.orders("SMALL", PRIOR, "33.33")
DATA.orders("SMALL", CURRENT, "1")  # active: not dormant
# NEW: no prior-period sales
DATA.orders("NEW", CURRENT, "100")
# RETURNS: prior 300, current 3 x -10 (returns exceed sales), active: not dormant
DATA.orders("RETURNS", PRIOR, "100")
DATA.orders("RETURNS", CURRENT, "-10")
# SEASON: sells only in winter, the same months both years: no decline although autumn is empty
DATA.orders("SEASON", PRIOR, "100")
DATA.orders("SEASON", CURRENT, "100")
# DORMANT: monthly in the prior window and up to May 2019, nothing since: dormancy owns it
DATA.orders(
    "DORMANT",
    ("2018-12-15", "2019-01-15", "2019-02-15", "2019-03-15", "2019-04-15", "2019-05-15"),
    "100",
)
DATA.orders(None, PRIOR, "100")  # the unknown customer (-1)
# LATER: declines as of 2020-02-29; a big order on 2020-03-05 is after the as-of date
DATA.orders("LATER", PRIOR, "100")
DATA.orders("LATER", CURRENT, "10")
DATA.orders("LATER", ["2020-03-05"], "5000")


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    root = tmp_path_factory.mktemp("recovery")
    settings = load_settings(
        env={
            "REVINT_PATHS_WAREHOUSE": str(root / "warehouse.duckdb"),
            "REVINT_PATHS_BRONZE": str(root / "bronze"),
        }
    )
    build(settings, DATA.rows)
    run_gold(settings)
    return settings


def run(built: Settings, tmp_path: Path, as_of: date = ASOF, **sections: dict) -> Settings:
    tmp_path.mkdir(parents=True, exist_ok=True)
    shutil.copy(built.paths.warehouse, tmp_path / "warehouse.duckdb")
    source = load_settings(env={"REVINT_PATHS_WAREHOUSE": str(tmp_path / "warehouse.duckdb")})
    recovery = {"min_prior_sales": 100, **sections.pop("recovery", {})}
    settings = with_asof(variant(tmp_path, source, recovery=recovery, **sections), as_of)
    run_opportunities(settings)
    return settings


def key(settings: Settings, code: str) -> int:
    return query(
        settings, "select customer_key from dim_customer where customer_code = ?", f"{S}{code}"
    )[0][0]


def outcome(settings: Settings, code: str) -> str:
    return query(
        settings,
        "select outcome from opp_evaluations where type = 'recovery' and customer_key = ?",
        key(settings, code),
    )[0][0]


def row(settings: Settings, code: str) -> tuple:
    return query(
        settings,
        "select gap, current_sales, prior_sales, prior_orders, decline_pct, reason_codes "
        "from opp_recovery where customer_key = ?",
        key(settings, code),
    )[0]


def triggered(settings: Settings) -> set[str]:
    return {
        code.removeprefix(S)
        for (code,) in query(
            settings,
            "select customer_code from opp_recovery join dim_customer using (customer_key)",
        )
    }


@pytest.fixture
def result(built: Settings, tmp_path: Path) -> Settings:
    return run(built, tmp_path)


# AC1: the same months a year earlier, and the three limits ------


def test_ac1_the_customers_that_trigger(result: Settings) -> None:
    assert triggered(result) == {"DECLINE", "AT20", "RETURNS", "LATER"}


def test_ac1_the_windows_compare_the_same_months_a_year_earlier(result: Settings) -> None:
    gap, current, prior, orders, decline, _ = row(result, "DECLINE")
    assert (current, prior, orders) == (Decimal("150.0000"), Decimal("300.0000"), 3)
    assert decline == Decimal("50.0000")


def test_ac1_a_seasonal_customer_is_not_a_decline(result: Settings) -> None:
    assert outcome(result, "SEASON") == "below_min_decline"
    assert outcome(result, "STEADY") == "below_min_decline"


def test_ac1_min_prior_orders_is_applied(result: Settings) -> None:
    assert outcome(result, "TWO_ORDERS") == "below_min_prior_orders"


def test_ac1_min_prior_sales_is_applied(result: Settings) -> None:
    assert outcome(result, "SMALL") == "below_min_prior_sales"


def test_ac1_the_committed_min_prior_sales_drops_small_customers(
    built: Settings, tmp_path: Path
) -> None:
    got = run(built, tmp_path, recovery={"min_prior_sales": 25000})
    assert triggered(got) == set()
    assert outcome(got, "DECLINE") == "below_min_prior_sales"


def test_ac1_min_decline_pct_is_applied(built: Settings, tmp_path: Path) -> None:
    got = run(built, tmp_path, recovery={"min_decline_pct": 60})
    assert outcome(got, "DECLINE") == "below_min_decline"


def test_ac1_window_months_is_applied(built: Settings, tmp_path: Path) -> None:
    # one month: February 2020 against February 2019 only
    got = run(built, tmp_path, recovery={"window_months": 1, "min_prior_orders": 1})
    assert row(got, "DECLINE")[1:4] == (Decimal("50.0000"), Decimal("100.0000"), 1)


# AC2: the gap, and a negative period ------


def test_ac2_the_gap_is_prior_minus_current(result: Settings) -> None:
    assert row(result, "DECLINE")[0] == Decimal("150.0000")


def test_ac2_a_negative_current_period_is_in_the_reason_codes(result: Settings) -> None:
    gap, current, *_, reasons = row(result, "RETURNS")
    assert current == Decimal("-30.0000")
    assert gap == Decimal("330.0000")
    assert "negative_current_period" in reasons


def test_ac2_a_normal_row_has_the_three_tests_only(result: Settings) -> None:
    assert row(result, "DECLINE")[5] == [
        "decline_at_least_min",
        "prior_sales_at_least_min",
        "prior_orders_at_least_min",
    ]


# AC3: dormancy owns a dormant customer ------


def test_ac3_a_dormant_customer_is_left_to_dormancy(result: Settings) -> None:
    assert outcome(result, "DORMANT") == "dormant"
    assert "DORMANT" not in triggered(result)
    dormant = query(result, "select customer_key from opp_dormancy")
    assert (key(result, "DORMANT"),) in dormant


def test_ac3_no_customer_is_in_both_engines(result: Settings) -> None:
    both = query(
        result,
        "select count(*) from opp_recovery join opp_dormancy using (customer_key, as_of_date)",
    )
    assert both == [(0,)]


# AC4: near the thresholds ------


def test_ac4_just_under_the_decline_does_not_trigger(result: Settings) -> None:
    assert outcome(result, "EDGE") == "below_min_decline"  # 19.99 percent


def test_ac4_exactly_at_the_decline_triggers(result: Settings) -> None:
    assert row(result, "AT20")[4] == Decimal("20.0000")


def test_ac4_just_under_min_prior_sales_does_not_trigger(result: Settings) -> None:
    assert row_prior(result, "SMALL") == Decimal("99.9900")


def row_prior(settings: Settings, code: str) -> Decimal:
    """Prior sales of a customer that did not trigger, from the evaluated set (via the inputs)."""
    return query(
        settings,
        "select sum(net_sales) from asof_orders where customer_key = ? "
        "and order_date between '2018-12-01' and '2019-02-28'",
        key(settings, code),
    )[0][0]


# AC5: no prior sales ------


def test_ac5_no_prior_sales_is_not_an_opportunity(result: Settings) -> None:
    assert outcome(result, "NEW") == "no_prior_sales"


def test_ac5_the_run_summary_counts_every_reason(result: Settings) -> None:
    rows = query(
        result,
        "select n_evaluated, n_triggered, n_suppressed, suppressed_by_reason "
        "from opp_run_summary where type = 'recovery'",
    )
    assert rows == [
        (
            11,  # every known customer; the unknown customer is not evaluated
            4,
            7,
            {
                "below_min_decline": 3,  # STEADY, SEASON, EDGE
                "below_min_prior_orders": 1,
                "below_min_prior_sales": 1,
                "dormant": 1,
                "no_prior_sales": 1,
            },
        )
    ]


def test_ac5_the_unknown_customer_is_not_evaluated(result: Settings) -> None:
    for table in ("opp_recovery", "opp_evaluations"):
        assert query(result, f"select count(*) from {table} where customer_key = -1") == [(0,)]


# AC6: only data on or before the as-of date ------


def test_ac6_a_later_order_is_not_seen(result: Settings) -> None:
    assert row(result, "LATER")[1] == Decimal("30.0000")  # the 2020-03-05 order is not counted


def test_ac6_after_that_order_the_customer_has_no_decline(built: Settings, tmp_path: Path) -> None:
    got = run(built, tmp_path, as_of=date(2020, 3, 31), recovery={"min_prior_orders": 1})
    # current window Jan - Mar 2020 holds the 5000 order (prior Jan - Mar 2019 has 2 orders)
    assert outcome(got, "LATER") == "below_min_decline"


def test_ac6_an_earlier_as_of_date(built: Settings, tmp_path: Path) -> None:
    got = run(built, tmp_path, as_of=date(2019, 2, 28))
    # no data a year before Dec 2018 - Feb 2019
    assert triggered(got) == set()


# Identity, rerun and AC7 ------


def test_rows_carry_the_identity_columns(result: Settings) -> None:
    k = key(result, "DECLINE")
    rows = query(
        result,
        "select opp_id, type, category, as_of_date, algo_version from opp_recovery "
        "where customer_key = ?",
        k,
    )
    assert rows == [(opp_id("recovery", k, None, ASOF), "recovery", None, ASOF, "recovery-1")]


def test_a_rerun_gives_identical_rows(built: Settings, tmp_path: Path) -> None:
    first = run(built, tmp_path)
    sql = "select * from opp_recovery order by opp_id"
    rows = query(first, sql)
    run_opportunities(first)
    assert query(first, sql) == rows


def test_ac7_every_ac_has_a_test_in_this_module() -> None:
    text = Path(__file__).read_text(encoding="utf-8")
    for ac in range(1, 7):
        assert f"def test_ac{ac}_" in text


@pytest.mark.realdata
def test_ac1_ac3_real_file_recovery(tmp_path: Path) -> None:
    """Counts only, on a copy of the built warehouse."""
    real = load_settings()
    if not real.paths.warehouse.is_file():
        pytest.skip("warehouse not built: run `uv run revint build all` first")
    shutil.copy(real.paths.warehouse, tmp_path / "w.duckdb")
    copy = load_settings(env={"REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb")})
    run_opportunities(copy)
    ((triggered_n,),) = query(
        copy, "select n_triggered from opp_run_summary where type = 'recovery'"
    )
    assert 0 < triggered_n == query(copy, "select count(*) from opp_recovery")[0][0]
    both = "select count(*) from opp_recovery join opp_dormancy using (customer_key)"
    assert query(copy, both) == [(0,)]
