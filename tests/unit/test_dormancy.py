"""Story #108: the dormancy engine (spec 03 section 3.2, FR-O2).

Synthetic data only; customer codes carry a SECRET- marker. Silver and gold are built once per
module; each test copies the warehouse and runs the opportunity stage on its own copy. Defaults
from config: min_orders 4, interval_multiple 2.0, min_days 45, lookback_months 12. As of
2020-02-29 unless a test says otherwise.
"""

from __future__ import annotations

import shutil
from datetime import date, timedelta
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


class Rows:
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.n = 8

    def orders(self, customer: str | None, days: list[date], net: str = "10") -> None:
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
                    Date=day.isoformat(),
                    Net_Amount_2=net,
                    **{"Quantity(PCS)": "1"},
                )
            )
            self.n += 1


def every(start: date, step: int, count: int) -> list[date]:
    return [start + timedelta(days=step * i) for i in range(count)]


def last_at(last: date, step: int, count: int) -> list[date]:
    """`count` orders `step` days apart, the last on `last`."""
    return every(last - timedelta(days=step * (count - 1)), step, count)


# Days since the last order are counted to ASOF (2020-02-29).
QUIET_100 = ASOF - timedelta(days=100)  # 2019-11-21
DATA = Rows()
DATA.orders("DORMANT", last_at(QUIET_100, 30, 5))  # 100 > 2 x 30 and > 45: dormant
DATA.orders("REGULAR", last_at(QUIET_100, 60, 5))  # same quiet days, 100 < 2 x 60: not dormant
DATA.orders("FEW", last_at(QUIET_100, 10, 3))  # 3 orders < 4: insufficient history
DATA.orders("ACTIVE", last_at(ASOF - timedelta(days=5), 20, 6))  # ordered 5 days ago
# EDGE_INTERVAL: interval 30, quiet exactly 60 (= 2 x 30): not beyond the own interval
DATA.orders("EDGE_INTERVAL", last_at(ASOF - timedelta(days=60), 30, 5))
# EDGE_DAYS: interval 10, quiet exactly 45 (= min_days): not beyond min_days
DATA.orders("EDGE_DAYS", last_at(ASOF - timedelta(days=45), 10, 5))
# ZERO: dormant by interval and days, but the lookback months net to zero
DATA.orders("ZERO", last_at(QUIET_100, 30, 4), net="5")
DATA.orders("ZERO", [QUIET_100 - timedelta(days=1)], net="-20")
DATA.orders(None, last_at(QUIET_100, 30, 5))  # the unknown customer (-1)
# FUTURE: dormant as of 2020-02-29, but it orders again on 2020-03-10 (after the as-of date)
DATA.orders("FUTURE", last_at(QUIET_100, 30, 5) + [date(2020, 3, 10)])
# OLD: dormant, with sales two years before the last order outside the lookback
DATA.orders("OLD", [date(2017, 1, 5)], net="999")
DATA.orders("OLD", last_at(QUIET_100, 30, 5), net="7")


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    root = tmp_path_factory.mktemp("dormancy")
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
    settings = with_asof(variant(tmp_path, source, **sections), as_of)
    run_opportunities(settings)
    return settings


def key(settings: Settings, code: str) -> int:
    return query(
        settings, "select customer_key from dim_customer where customer_code = ?", f"{S}{code}"
    )[0][0]


def outcome(settings: Settings, code: str) -> str:
    return query(
        settings,
        "select outcome from opp_evaluations where type = 'dormancy' and customer_key = ?",
        key(settings, code),
    )[0][0]


def dormant_codes(settings: Settings) -> set[str]:
    return {
        code.removeprefix(S)
        for (code,) in query(
            settings,
            "select customer_code from opp_dormancy join dim_customer using (customer_key)",
        )
    }


@pytest.fixture
def result(built: Settings, tmp_path: Path) -> Settings:
    return run(built, tmp_path)


# AC1: dormant when all three tests hold ------


def test_ac1_the_dormant_customers(result: Settings) -> None:
    assert dormant_codes(result) == {"DORMANT", "FUTURE", "OLD"}


def test_ac1_a_dormant_row_records_the_tests_it_met(result: Settings) -> None:
    rows = query(
        result,
        "select reason_codes, days_since_last_order, median_interval_days, n_orders, "
        "last_order_date from opp_dormancy where customer_key = ?",
        key(result, "DORMANT"),
    )
    assert rows == [
        (
            ["beyond_own_interval", "beyond_min_days", "sales_in_lookback"],
            100,
            Decimal("30.0000"),
            5,
            QUIET_100,
        )
    ]


def test_ac1_an_active_customer_is_within_its_interval(result: Settings) -> None:
    assert outcome(result, "ACTIVE") == "within_own_interval"


def test_ac1_min_days_is_applied(built: Settings, tmp_path: Path) -> None:
    got = run(built, tmp_path, dormancy={"min_days": 100})
    assert outcome(got, "DORMANT") == "within_min_days"  # 100 is not > 100


def test_ac1_interval_multiple_is_applied(built: Settings, tmp_path: Path) -> None:
    got = run(built, tmp_path, dormancy={"interval_multiple": 1.5})
    assert "REGULAR" in dormant_codes(got)  # 100 > 1.5 x 60


def test_ac1_no_sales_in_the_lookback_does_not_trigger(result: Settings) -> None:
    assert outcome(result, "ZERO") == "no_sales_in_lookback"


def test_ac1_the_lookback_is_applied(built: Settings, tmp_path: Path) -> None:
    # with a 1-month lookback DORMANT has only its last order (10) in it
    got = run(built, tmp_path, dormancy={"lookback_months": 1})
    gap = query(got, "select gap from opp_dormancy where customer_key = ?", key(got, "DORMANT"))
    assert gap == [(Decimal("10.0000"),)]


# AC2: below min_orders: not scored, counted as insufficient_history ------


def test_ac2_too_few_orders_is_insufficient_history(result: Settings) -> None:
    assert outcome(result, "FEW") == "insufficient_history"
    assert "FEW" not in dormant_codes(result)


def test_ac2_the_run_summary_counts_insufficient_history(result: Settings) -> None:
    rows = query(
        result,
        "select n_evaluated, n_triggered, n_suppressed, suppressed_by_reason "
        "from opp_run_summary where type = 'dormancy'",
    )
    assert rows == [
        (
            9,  # every known customer; the unknown customer is not evaluated
            3,
            6,
            {
                "insufficient_history": 1,
                "no_sales_in_lookback": 1,
                "within_min_days": 1,
                "within_own_interval": 3,  # REGULAR, ACTIVE, EDGE_INTERVAL
            },
        )
    ]


def test_ac2_min_orders_is_applied(built: Settings, tmp_path: Path) -> None:
    got = run(built, tmp_path, dormancy={"min_orders": 6})
    assert outcome(got, "DORMANT") == "insufficient_history"  # 5 orders


# AC3: equal days since the last order, different intervals: different outcomes ------


def test_ac3_the_customers_own_interval_decides(result: Settings) -> None:
    days = query(
        result,
        "select customer_key, date_diff('day', last_order_date, ?::date) "
        "from asof_customer_profile where customer_key in (?, ?) order by 1",
        ASOF,
        key(result, "DORMANT"),
        key(result, "REGULAR"),
    )
    assert {d for _, d in days} == {100}
    assert outcome(result, "DORMANT") == "triggered"
    assert outcome(result, "REGULAR") == "within_own_interval"


# AC4: the gap, and the unknown customer ------


def test_ac4_the_gap_is_the_lookback_net_sales_before_the_last_order(result: Settings) -> None:
    gaps = dict(
        query(
            result,
            "select customer_code, gap from opp_dormancy join dim_customer using (customer_key)",
        )
    )
    assert gaps[f"{S}DORMANT"] == Decimal("50.0000")  # 5 orders of 10, all in the 12 months
    # OLD: the 2017 sale is outside the 12 months before the last order
    assert gaps[f"{S}OLD"] == Decimal("35.0000")


def test_ac4_the_unknown_customer_is_never_flagged_or_evaluated(result: Settings) -> None:
    for table in ("opp_dormancy", "opp_evaluations"):
        assert query(result, f"select count(*) from {table} where customer_key = -1") == [(0,)]


def test_ac4_rows_carry_the_identity_columns(result: Settings) -> None:
    k = key(result, "DORMANT")
    rows = query(
        result,
        "select opp_id, type, category, as_of_date, algo_version from opp_dormancy "
        "where customer_key = ?",
        k,
    )
    assert rows == [(opp_id("dormancy", k, None, ASOF), "dormancy", None, ASOF, "dormancy-1")]


# AC5: just inside every limit does not trigger ------


def test_ac5_exactly_at_the_interval_limit_does_not_trigger(result: Settings) -> None:
    assert outcome(result, "EDGE_INTERVAL") == "within_own_interval"


def test_ac5_exactly_at_min_days_does_not_trigger(result: Settings) -> None:
    assert outcome(result, "EDGE_DAYS") == "within_min_days"


def test_ac5_exactly_at_min_orders_is_scored(built: Settings, tmp_path: Path) -> None:
    # min_orders is a floor: 5 orders with min_orders 5 is enough history
    got = run(built, tmp_path, dormancy={"min_orders": 5})
    assert outcome(got, "DORMANT") == "triggered"


# AC6: only data on or before the as-of date ------


def test_ac6_a_later_order_is_not_seen(result: Settings) -> None:
    assert outcome(result, "FUTURE") == "triggered"  # the 2020-03-10 order is after the as-of


def test_ac6_after_that_order_the_customer_is_active(built: Settings, tmp_path: Path) -> None:
    got = run(built, tmp_path, as_of=date(2020, 3, 15))
    assert outcome(got, "FUTURE") == "within_own_interval"


def test_ac6_an_earlier_as_of_date_sees_earlier_data(built: Settings, tmp_path: Path) -> None:
    got = run(built, tmp_path, as_of=QUIET_100 + timedelta(days=10))
    assert outcome(got, "DORMANT") == "within_own_interval"
    assert query(got, "select count(*) from opp_dormancy") == [(0,)]


# Rerun and AC7 ------


def test_a_rerun_gives_identical_rows(built: Settings, tmp_path: Path) -> None:
    first = run(built, tmp_path / "a")
    sql = "select * from opp_dormancy order by opp_id"
    rows = query(first, sql)
    run_opportunities(first)
    assert query(first, sql) == rows


def test_ac7_every_ac_has_a_test_in_this_module() -> None:
    text = Path(__file__).read_text(encoding="utf-8")
    for ac in range(1, 7):
        assert f"def test_ac{ac}_" in text


@pytest.mark.realdata
def test_ac1_ac2_real_file_dormancy(tmp_path: Path) -> None:
    """Counts only, on a copy of the built warehouse."""
    real = load_settings()
    if not real.paths.warehouse.is_file():
        pytest.skip("warehouse not built: run `uv run revint build all` first")
    shutil.copy(real.paths.warehouse, tmp_path / "w.duckdb")
    copy = load_settings(env={"REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb")})
    run_opportunities(copy)
    ((evaluated, triggered, reasons),) = query(
        copy,
        "select n_evaluated, n_triggered, suppressed_by_reason from opp_run_summary "
        "where type = 'dormancy'",
    )
    assert triggered == query(copy, "select count(*) from opp_dormancy")[0][0]
    assert 0 < triggered < evaluated
    assert reasons["insufficient_history"] > 0
    assert query(copy, "select count(*) from opp_dormancy where gap <= 0") == [(0,)]
