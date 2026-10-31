"""Story #82: mart_customer_profile (spec 02 section 6).

Synthetic data only; customer codes carry a SECRET- marker to prove none reaches logs. Silver is
built once per module, each test copies the warehouse and runs gold on its own copy. The
real-file test is marked `realdata` and asserts counts only.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import pytest
from gold_helpers import gold
from silver_helpers import bronze_row, build, query

from revint.config import Settings, load_settings
from revint.gold import GOLD_DIR, GoldError, run_gold

S = "SECRET-"


def sale(
    row: int,
    customer: str | None,
    day: str | None,
    net: str = "1",
    branch: str | None = "Magway",
    channel: str | None = "GT",
    order: str | None = None,
) -> dict[str, str | None]:
    return bronze_row(
        row,
        OrderReference=order or f"O{row}",
        CustomerCode=customer,
        Customer=f"{S}name" if customer else None,
        Branch_Name=branch,
        Channel_Category=channel,
        Date=day,
        Net_Amount_2=net,
        **{"Quantity(PCS)": "1"},
    )


# C1: four orders (dates 10 Jan, 20 Jan, 20 Feb, 20 Mar): intervals 10, 31, 28 -> median 28.
#     Two lines on 20 Jan with different order references: still one order (customer x date).
# C2: a single order (no interval). C3: two orders one day apart.
# C4: later orders have another branch and channel (the latest order decides the keys).
# C5: an order dated after the as-of date 2020-02-29. C6: no date at all. Row 30: no customer.
ROWS = [
    sale(8, f"{S}C1", "2019-01-10"),
    sale(9, f"{S}C1", "2019-01-20", order="OA"),
    sale(10, f"{S}C1", "2019-01-20", order="OB"),
    sale(11, f"{S}C1", "2019-02-20"),
    sale(12, f"{S}C1", "2019-03-20"),
    sale(13, f"{S}C2", "2019-05-05"),
    sale(14, f"{S}C3", "2019-06-01"),
    sale(15, f"{S}C3", "2019-06-02"),
    sale(16, f"{S}C4", "2019-01-01", branch="Magway", channel="GT"),
    sale(17, f"{S}C4", "2019-02-01", branch="PYAY", channel="MT"),
    sale(18, f"{S}C5", "2019-12-01"),
    sale(19, f"{S}C5", "2020-03-01"),
    sale(20, f"{S}C6", None),
    sale(21, None, "2019-07-07"),
    bronze_row(22, Change_to_Ctn="1"),
]
COLUMNS = (
    "customer_key, last_order_date, n_orders, median_interval_days, mean_interval_days, "
    "peer_keys, f_last_order_after_asof"
)


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    root = tmp_path_factory.mktemp("martprofile")
    settings = load_settings(
        env={
            "REVINT_PATHS_WAREHOUSE": str(root / "warehouse.duckdb"),
            "REVINT_PATHS_BRONZE": str(root / "bronze"),
        }
    )
    build(settings, ROWS)
    return settings


def profile(settings: Settings) -> dict[str | None, dict]:
    names = [c.strip() for c in COLUMNS.split(",")]
    rows = query(
        settings,
        f"select c.customer_code, {', '.join('p.' + n for n in names)} "
        "from mart_customer_profile as p inner join dim_customer as c "
        "on c.customer_key = p.customer_key",
    )
    return {r[0]: dict(zip(names, r[1:], strict=True)) for r in rows}


# AC1: one row per customer with last order, order count, intervals and peer keys ------


def test_ac1_the_table_has_the_documented_columns(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    columns = [
        c
        for (c,) in query(
            settings,
            "select column_name from information_schema.columns "
            "where table_name = 'mart_customer_profile' order by ordinal_position",
        )
    ]
    assert columns == [c.strip() for c in COLUMNS.split(",")]


def test_ac1_one_row_per_customer(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    assert query(
        settings, "select count(*), count(distinct customer_key) from mart_customer_profile"
    ) == [(7, 7)]  # C1 to C6 and the unknown customer


def test_ac1_last_order_date_and_number_of_orders(built: Settings, tmp_path: Path) -> None:
    got = profile(gold(built, tmp_path))
    assert (got[f"{S}C1"]["last_order_date"], got[f"{S}C1"]["n_orders"]) == (date(2019, 3, 20), 4)
    assert (got[f"{S}C3"]["last_order_date"], got[f"{S}C3"]["n_orders"]) == (date(2019, 6, 2), 2)


def test_ac1_an_order_is_a_distinct_customer_and_date(built: Settings, tmp_path: Path) -> None:
    # two lines on 20 January with different order references are one order
    assert profile(gold(built, tmp_path))[f"{S}C1"]["n_orders"] == 4


def test_ac1_median_and_mean_interval_in_days(built: Settings, tmp_path: Path) -> None:
    got = profile(gold(built, tmp_path))[f"{S}C1"]
    # order dates 10 Jan, 20 Jan, 20 Feb, 20 Mar: gaps 10, 31, 28
    assert float(got["median_interval_days"]) == 28.0
    assert float(got["mean_interval_days"]) == 23.0  # (10 + 31 + 28) / 3


def test_ac1_two_orders_give_one_interval(built: Settings, tmp_path: Path) -> None:
    got = profile(gold(built, tmp_path))[f"{S}C3"]
    assert (float(got["median_interval_days"]), float(got["mean_interval_days"])) == (1.0, 1.0)


def test_ac1_the_median_of_an_even_number_of_gaps_is_their_midpoint(tmp_path: Path) -> None:
    settings = load_settings(
        env={
            "REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb"),
            "REVINT_PATHS_BRONZE": str(tmp_path / "b"),
        }
    )
    build(
        settings,
        [sale(8 + i, "X", day) for i, day in enumerate(["2019-01-01", "2019-01-11", "2019-02-20"])],
    )
    run_gold(settings)
    # gaps 10 and 40: median 25, mean 25
    got = profile(settings)["X"]
    assert (float(got["median_interval_days"]), float(got["mean_interval_days"])) == (25.0, 25.0)


def test_ac1_peer_group_keys_come_from_the_latest_order(built: Settings, tmp_path: Path) -> None:
    got = profile(gold(built, tmp_path))
    assert got[f"{S}C4"]["peer_keys"] == ["Modern Trade", "Pyay"]  # the label maps apply
    assert got[f"{S}C1"]["peer_keys"] == ["GT", "Magway"]


def test_ac1_peer_keys_follow_the_peer_groups_columns_in_order(
    built: Settings, tmp_path: Path
) -> None:
    settings = gold(
        built,
        tmp_path,
        peer_groups={"columns": ["Branch_Name", "Channel_Category"], "fallback_columns": []},
    )
    assert profile(settings)[f"{S}C1"]["peer_keys"] == ["Magway", "GT"]


def test_ac1_a_single_peer_column_gives_a_single_key(built: Settings, tmp_path: Path) -> None:
    settings = gold(
        built, tmp_path, peer_groups={"columns": ["Branch_Name"], "fallback_columns": []}
    )
    assert profile(settings)[f"{S}C1"]["peer_keys"] == ["Magway"]


def test_ac1_a_blank_peer_value_shows_unknown(tmp_path: Path) -> None:
    settings = load_settings(
        env={
            "REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb"),
            "REVINT_PATHS_BRONZE": str(tmp_path / "b"),
        }
    )
    build(settings, [sale(8, "X", "2019-01-05", branch=None, channel="GT")])
    run_gold(settings)
    assert profile(settings)["X"]["peer_keys"] == ["GT", "Unknown"]


def test_ac1_the_latest_order_with_a_value_decides_each_key(tmp_path: Path) -> None:
    settings = load_settings(
        env={
            "REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb"),
            "REVINT_PATHS_BRONZE": str(tmp_path / "b"),
        }
    )
    build(
        settings,
        [
            sale(8, "X", "2019-01-05", branch="Magway"),
            sale(9, "X", "2019-02-05", branch=None),
        ],
    )
    run_gold(settings)
    assert profile(settings)["X"]["peer_keys"] == ["GT", "Magway"]


def test_ac1_the_peer_keys_agree_with_dim_customer_channel_and_branch(
    built: Settings, tmp_path: Path
) -> None:
    settings = gold(built, tmp_path)
    got = query(
        settings,
        "select count(*) from mart_customer_profile as p inner join dim_customer as c "
        "on c.customer_key = p.customer_key "
        "where c.customer_key <> -1 and p.n_orders > 0 "
        "and (p.peer_keys[1] <> c.channel or p.peer_keys[2] <> c.branch)",
    )
    assert got == [(0,)]


def test_ac1_the_unknown_customer_has_a_row(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    got = query(
        settings,
        "select n_orders, last_order_date from mart_customer_profile where customer_key = -1",
    )
    assert got == [(1, date(2019, 7, 7))]


def test_ac1_a_customer_with_no_dated_line_has_a_row_with_no_dates(
    built: Settings, tmp_path: Path
) -> None:
    got = profile(gold(built, tmp_path))[f"{S}C6"]
    assert (got["last_order_date"], got["n_orders"], got["median_interval_days"]) == (None, 0, None)


def test_ac1_the_sql_reads_net_sales_only_through_the_fact_and_the_view() -> None:
    raw = (GOLD_DIR / "09_mart_customer_profile.sql").read_text(encoding="utf-8")
    text = " ".join(line.split("--")[0] for line in raw.splitlines())
    # The profile uses no amount at all. It reads the silver label columns for the peer keys
    # (the fact does not carry them), and nothing else from silver_sales.
    assert "v_net_sales" in text and "fact_sales" in text
    assert "amount_" not in text and "Net_Amount" not in text
    assert text.count("silver_sales") == 1
    for name in ("Channel_Category", "Branch_Name", "OrderReference"):
        assert name not in text


def test_ac1_the_header_comment_states_the_grain_the_order_rule_and_the_definitions() -> None:
    raw = (GOLD_DIR / "09_mart_customer_profile.sql").read_text(encoding="utf-8")
    header = raw.split("create or replace table")[0].lower()
    for word in ("grain", "customer", "order", "distinct", "interval", "median", "peer"):
        assert word in header


# AC2: a customer with one order has NULL intervals and no error ------


def test_ac2_a_single_order_gives_null_intervals(built: Settings, tmp_path: Path) -> None:
    got = profile(gold(built, tmp_path))[f"{S}C2"]
    assert got["n_orders"] == 1
    assert got["median_interval_days"] is None
    assert got["mean_interval_days"] is None


def test_ac2_many_lines_on_one_day_are_still_one_order_with_null_intervals(
    tmp_path: Path,
) -> None:
    settings = load_settings(
        env={
            "REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb"),
            "REVINT_PATHS_BRONZE": str(tmp_path / "b"),
        }
    )
    build(settings, [sale(8, "X", "2019-01-05"), sale(9, "X", "2019-01-05", order="OTHER")])
    run_gold(settings)
    got = profile(settings)["X"]
    assert (got["n_orders"], got["median_interval_days"], got["mean_interval_days"]) == (
        1,
        None,
        None,
    )


def test_ac2_the_gold_stage_runs_without_error_when_every_customer_has_one_order(
    tmp_path: Path,
) -> None:
    settings = load_settings(
        env={
            "REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb"),
            "REVINT_PATHS_BRONZE": str(tmp_path / "b"),
        }
    )
    build(settings, [sale(8, "A", "2019-01-05"), sale(9, "B", "2019-02-05")])
    run_gold(settings)
    assert query(
        settings, "select count(*) from mart_customer_profile where median_interval_days is null"
    ) == [(2,)]  # A and B (each has one order); the unknown customer has none


def test_ac2_an_interval_is_null_only_below_two_orders(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    assert query(
        settings,
        "select count(*) from mart_customer_profile "
        "where (n_orders < 2) <> (median_interval_days is null)",
    ) == [(0,)]


# AC3: a last order date after the as-of date is flagged ------


def test_ac3_a_last_order_after_the_as_of_date_is_flagged(built: Settings, tmp_path: Path) -> None:
    got = profile(gold(built, tmp_path))
    assert got[f"{S}C5"]["last_order_date"] == date(2020, 3, 1)
    assert got[f"{S}C5"]["f_last_order_after_asof"] is True


def test_ac3_other_customers_are_not_flagged(built: Settings, tmp_path: Path) -> None:
    got = profile(gold(built, tmp_path))
    assert sorted(code for code, row in got.items() if row["f_last_order_after_asof"]) == [f"{S}C5"]


def test_ac3_the_flag_follows_the_as_of_setting(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path, asof={"date": date(2019, 6, 1)})
    got = profile(settings)
    flagged = {code for code, row in got.items() if row["f_last_order_after_asof"]}
    # C3's last order is 2 June, C5's is in 2020, and the unknown customer (code None) ordered
    # on 7 July; C1, C2 and C4 ordered before 1 June.
    assert flagged == {f"{S}C3", f"{S}C5", None}


def test_ac3_the_last_order_date_is_kept_not_clipped(built: Settings, tmp_path: Path) -> None:
    assert profile(gold(built, tmp_path))[f"{S}C5"]["n_orders"] == 2


def test_ac3_a_customer_with_no_dated_line_is_not_flagged(built: Settings, tmp_path: Path) -> None:
    assert profile(gold(built, tmp_path))[f"{S}C6"]["f_last_order_after_asof"] is False


# AC4: the customer count equals mart_customer_month ------


def test_ac4_the_customer_count_equals_mart_customer_month(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    assert query(settings, "select count(*) from mart_customer_profile") == query(
        settings, "select count(distinct customer_key) from mart_customer_month"
    )


def test_ac4_the_customers_are_the_same_set(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    assert query(
        settings,
        "select count(*) from (select customer_key from mart_customer_profile "
        "except select customer_key from mart_customer_month)",
    ) == [(0,)]
    assert query(
        settings,
        "select count(*) from (select customer_key from mart_customer_month "
        "except select customer_key from mart_customer_profile)",
    ) == [(0,)]


@pytest.mark.parametrize("zero_fill", [True, False])
@pytest.mark.parametrize("exclude", [True, False])
def test_ac4_the_customer_set_holds_under_every_setting(
    built: Settings, tmp_path: Path, zero_fill: bool, exclude: bool
) -> None:
    settings = gold(
        built,
        tmp_path,
        marts={"zero_fill": zero_fill},
        duplicates={"exclude_from_net_sales": exclude},
    )
    assert query(settings, "select count(*) from mart_customer_profile") == query(
        settings, "select count(distinct customer_key) from mart_customer_month"
    )


def test_ac4_the_orders_agree_with_mart_customer_month_months(
    built: Settings, tmp_path: Path
) -> None:
    settings = gold(built, tmp_path)
    assert query(
        settings,
        "select count(*) from mart_customer_profile as p "
        "inner join (select customer_key, count(*) filter (where not f_zero_filled) as months "
        "from mart_customer_month where month_start is not null group by 1) as m "
        "on m.customer_key = p.customer_key "
        "where p.n_orders < m.months",
    ) == [(0,)]  # a customer has at least one order in every month it has sales


# Settings, files and safety ------


def test_gold_needs_peer_columns_that_silver_labels_or_types_as_text(
    built: Settings, tmp_path: Path
) -> None:
    with pytest.raises(GoldError, match="peer_groups.columns"):
        gold(built, tmp_path, peer_groups={"columns": ["Date"], "fallback_columns": []})


def test_the_file_runs_after_the_other_marts() -> None:
    names = sorted(p.name for p in GOLD_DIR.glob("*.sql"))
    assert names.index("08_mart_customer_category_month.sql") < names.index(
        "09_mart_customer_profile.sql"
    )


def test_the_earlier_gold_objects_are_still_built(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    for table in ("fact_sales", "mart_customer_month", "mart_customer_category_month"):
        assert query(settings, f"select count(*) from {table}")[0][0] > 0


def test_a_gold_rerun_gives_identical_rows(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    sql = "select * from mart_customer_profile order by customer_key"
    first = query(settings, sql)
    run_gold(settings)
    assert query(settings, sql) == first


def test_the_gold_stage_logs_and_the_mart_holds_no_customer_codes(
    built: Settings, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        settings = gold(built, tmp_path)
    assert S not in caplog.text
    assert S not in repr(query(settings, "select * from mart_customer_profile"))


# AC5 ------


def test_ac5_every_ac_has_a_test_in_this_module() -> None:
    text = Path(__file__).read_text(encoding="utf-8")
    for ac in range(1, 5):
        assert f"def test_ac{ac}_" in text


@pytest.mark.realdata
def test_ac1_ac2_ac3_ac4_real_file_profile(tmp_path: Path) -> None:
    """Counts only. Gold runs on a temporary warehouse built from the real bronze files."""
    real = load_settings(env={"REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb")})
    if not list(real.paths.bronze.glob("*__RAW_SCJ_SALES.parquet")):
        pytest.skip("bronze not built: run `uv run revint build bronze` first")
    from revint.silver import run_silver

    run_silver(real)
    run_gold(real)
    assert query(
        real, "select count(*), count(distinct customer_key) from mart_customer_profile"
    ) == [(12_240, 12_240)]
    assert query(real, "select count(*) from mart_customer_profile") == query(
        real, "select count(distinct customer_key) from mart_customer_month"
    )
    assert query(
        real,
        "select count(*) from mart_customer_profile "
        "where (n_orders < 2) <> (median_interval_days is null)",
    ) == [(0,)]
    assert query(real, "select count(*) from mart_customer_profile where n_orders = 1") == [
        (2_416,)
    ]
    assert query(
        real, "select count(*) from mart_customer_profile where f_last_order_after_asof"
    ) == [(0,)]
    assert query(real, "select max(last_order_date) from mart_customer_profile") == [
        (date(2020, 2, 29),)
    ]
