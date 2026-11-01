"""Story #106: the as-of inputs of the opportunity engines (spec 03 section 1, spec 04 P1).

Synthetic data only; customer codes carry a SECRET- marker to prove none reaches logs. Silver and
gold are built once per module; each test copies the warehouse and builds the as-of inputs on its
own copy. The real-file test is marked `realdata` and asserts counts and sums only.

The inputs are what the engines read in place of the all-data marts. Every input holds only data
on or before the as-of date, so an engine cannot see the future.
"""

from __future__ import annotations

import logging
import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
import pytest
import yaml
from gold_helpers import gold
from silver_helpers import bronze_row, build, query

from revint.config import DEFAULT_SETTINGS_FILE, Settings, load_settings
from revint.gold import run_gold
from revint.opportunities import (
    ASOF_INPUT_TABLES,
    OPPORTUNITIES_DIR,
    OpportunitiesError,
    build_asof_inputs,
    with_asof,
)

S = "SECRET-"
CAT_A, CAT_B = f"{S}A", f"{S}B"


def sale(
    row: int,
    customer: str | None,
    day: str | None,
    net: str,
    product: str = "PA",
    branch: str | None = "Magway",
    channel: str | None = "GT",
    order: int | None = None,
) -> dict[str, str | None]:
    return bronze_row(
        row,
        OrderReference=f"O{order or row}",
        CustomerCode=customer,
        Customer=f"{S}name" if customer else None,
        SCJ_CODE_1=product,
        Internal_Category={"PA": CAT_A, "PB": CAT_B}.get(product),
        Branch_Name=branch,
        Channel_Category=channel,
        Date=day,
        Net_Amount_2=net,
        **{"Quantity(PCS)": "1"},
    )


# C1 buys A every month January to April 2019 and once in category B in February; C2 buys A in
# January and March. C3 buys only in May. Row 16 copies row 15 (silver excludes the copy), row 17
# has no customer, row 19 is the stray row. A line with no date is tested on its own build.
ROWS = [
    sale(8, f"{S}C1", "2019-01-10", "10"),
    sale(9, f"{S}C1", "2019-02-10", "10"),
    sale(10, f"{S}C1", "2019-02-20", "4", product="PB"),
    sale(11, f"{S}C1", "2019-03-10", "10"),
    sale(12, f"{S}C1", "2019-04-10", "-2"),
    sale(13, f"{S}C2", "2019-01-15", "6", branch="PYAY", channel="MT"),
    sale(14, f"{S}C2", "2019-03-15", "6", branch="PYAY", channel="MT"),
    sale(15, f"{S}C3", "2019-05-05", "8"),
    sale(16, f"{S}C3", "2019-05-05", "8", order=15),
    sale(17, None, "2019-02-01", "3"),
    bronze_row(19, Change_to_Ctn="1"),
]
LAST_DAY = date(2019, 5, 5)


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    root = tmp_path_factory.mktemp("asof")
    settings = load_settings(
        env={
            "REVINT_PATHS_WAREHOUSE": str(root / "warehouse.duckdb"),
            "REVINT_PATHS_BRONZE": str(root / "bronze"),
        }
    )
    build(settings, ROWS)
    run_gold(settings)
    return settings


def variant(root: Path, source: Settings, **sections: dict[str, Any]) -> Settings:
    data = yaml.safe_load(DEFAULT_SETTINGS_FILE.read_text(encoding="utf-8"))
    for name, keys in sections.items():
        data[name] = {**data.get(name, {}), **keys}
    config_file = root / "config" / "settings.yaml"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return load_settings(config_file, env={"REVINT_PATHS_WAREHOUSE": str(source.paths.warehouse)})


def copied(built: Settings, tmp_path: Path, **sections: dict[str, Any]) -> Settings:
    """A private copy of the gold warehouse, with settings changed as given."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    shutil.copy(built.paths.warehouse, tmp_path / "warehouse.duckdb")
    source = load_settings(env={"REVINT_PATHS_WAREHOUSE": str(tmp_path / "warehouse.duckdb")})
    return variant(tmp_path, source, **sections)


def inputs(built: Settings, tmp_path: Path, asof: date | None = None, **sections) -> Settings:
    settings = copied(built, tmp_path, **sections)
    build_asof_inputs(settings if asof is None else with_asof(settings, asof))
    return settings


def codes(settings: Settings) -> dict[int, str | None]:
    return dict(query(settings, "select customer_key, customer_code from dim_customer"))


def by_code(settings: Settings, table: str, columns: str) -> dict:
    names = codes(settings)
    rows = query(settings, f"select customer_key, {columns} from {table}")
    return {names[r[0]]: r[1:] for r in rows}


# AC1: orders, monthly net sales, intervals and penetration, up to the as-of date ------


def test_ac1_every_input_table_is_built(built: Settings, tmp_path: Path) -> None:
    settings = inputs(built, tmp_path)
    tables = {t for (t,) in query(settings, "select table_name from information_schema.tables")}
    assert set(ASOF_INPUT_TABLES) <= tables
    assert ASOF_INPUT_TABLES == (
        "asof_orders",
        "asof_customer_month",
        "asof_customer_category_month",
        "asof_customer_profile",
        "asof_peer_category_share",
    )


def test_ac1_orders_are_one_per_customer_and_date(built: Settings, tmp_path: Path) -> None:
    settings = inputs(built, tmp_path)
    got = by_code(settings, "asof_orders", "order_date, net_sales, n_lines")
    assert query(
        settings,
        "select count(*) from (select customer_key, order_date from asof_orders "
        "group by 1, 2 having count(*) > 1)",
    ) == [(0,)]
    # C1's two February lines are on different dates, so they are two orders
    assert query(settings, "select count(*) from asof_orders")[0][0] == 9
    assert got[f"{S}C3"] == (date(2019, 5, 5), Decimal("8.0000"), 1)  # the copy is excluded


def test_ac1_an_earlier_as_of_date_drops_the_later_orders(built: Settings, tmp_path: Path) -> None:
    settings = inputs(built, tmp_path, asof=date(2019, 2, 15))
    dates = [d for (d,) in query(settings, "select order_date from asof_orders order by 1")]
    assert dates == [date(2019, 1, 10), date(2019, 1, 15), date(2019, 2, 1), date(2019, 2, 10)]


def test_ac1_the_as_of_day_itself_is_included(built: Settings, tmp_path: Path) -> None:
    settings = inputs(built, tmp_path, asof=date(2019, 2, 10))
    assert date(2019, 2, 10) in {
        d for (d,) in query(settings, "select order_date from asof_orders")
    }


def test_ac1_customer_month_net_sales_stop_at_the_as_of_date(
    built: Settings, tmp_path: Path
) -> None:
    settings = inputs(built, tmp_path, asof=date(2019, 2, 15))
    got = query(
        settings,
        "select c.customer_code, m.month_start, m.net_sales, m.n_lines "
        "from asof_customer_month as m inner join dim_customer as c using (customer_key) "
        "where not m.f_zero_filled order by 1, 2",
    )
    assert (f"{S}C1", date(2019, 2, 1), Decimal("10.0000"), 1) in got  # the 20 Feb line is later
    assert not any(row[1] > date(2019, 2, 1) for row in got)


def test_ac1_a_month_cut_by_the_as_of_date_holds_only_the_days_up_to_it(
    built: Settings, tmp_path: Path
) -> None:
    settings = inputs(built, tmp_path, asof=date(2019, 2, 15))
    feb = query(
        settings,
        "select sum(net_sales) from asof_customer_category_month "
        "where month_start = date '2019-02-01'",
    )
    assert feb == [(Decimal("13.0000"),)]  # C1 10 and the unknown customer 3; not the 4 on 20 Feb


def test_ac1_intervals_and_last_order_use_only_orders_up_to_the_date(
    built: Settings, tmp_path: Path
) -> None:
    settings = inputs(built, tmp_path, asof=date(2019, 3, 31))
    got = by_code(
        settings, "asof_customer_profile", "last_order_date, n_orders, median_interval_days"
    )
    # C1 ordered on 10 Jan, 10 Feb, 20 Feb and 10 Mar: gaps 31, 10, 18, median 18
    assert got[f"{S}C1"] == (date(2019, 3, 10), 4, Decimal("18.0000"))
    assert got[f"{S}C2"][:2] == (date(2019, 3, 15), 2)


def test_ac1_peer_penetration_uses_only_lines_up_to_the_date(
    built: Settings, tmp_path: Path
) -> None:
    early = inputs(built, tmp_path / "early", asof=date(2019, 2, 15), peer_groups={"min_size": 1})
    late = inputs(built, tmp_path / "late", peer_groups={"min_size": 1})
    sql = (
        "select n_buying from asof_peer_category_share "
        "where peer_keys = ['GT', 'Magway'] and category = ?"
    )
    assert query(early, sql, CAT_B) == []  # C1 bought B on 20 Feb, after the date
    assert query(late, sql, CAT_B) == [(1,)]


def test_ac1_the_inputs_hold_the_as_of_date_they_were_built_for(
    built: Settings, tmp_path: Path
) -> None:
    settings = inputs(built, tmp_path, asof=date(2019, 3, 1))
    for table in ASOF_INPUT_TABLES:
        assert query(settings, f"select distinct as_of_date from {table}") == [(date(2019, 3, 1),)]


def test_ac1_the_sql_reads_net_sales_only_through_the_fact_and_the_view() -> None:
    raw = (OPPORTUNITIES_DIR / "01_asof_inputs.sql").read_text(encoding="utf-8")
    code = " ".join(line.split("--")[0] for line in raw.splitlines())
    assert "fact_sales" in code and "v_net_sales" in code
    assert "amount_" not in code and "Net_Amount" not in code


# AC2: the engines never read the all-data marts; the inputs reproduce their logic ------


def test_ac2_the_sql_reads_neither_all_data_mart() -> None:
    raw = (OPPORTUNITIES_DIR / "01_asof_inputs.sql").read_text(encoding="utf-8")
    code = " ".join(line.split("--")[0] for line in raw.splitlines())
    for mart in (
        "mart_customer_profile",
        "mart_peer_category_share",
        "mart_customer_month",
        "mart_customer_category_month",
    ):
        assert mart not in code, mart


def test_ac2_the_peer_group_follows_the_peer_groups_settings(
    built: Settings, tmp_path: Path
) -> None:
    by_branch = inputs(
        built,
        tmp_path,
        peer_groups={"columns": ["Branch_Name"], "fallback_columns": [], "min_size": 1},
    )
    keys = {
        tuple(k)
        for (k,) in query(by_branch, "select distinct peer_keys from asof_peer_category_share")
    }
    assert keys == {("Magway",), ("Pyay",)}


def test_ac2_a_small_group_falls_back_as_in_the_mart(built: Settings, tmp_path: Path) -> None:
    settings = inputs(built, tmp_path, peer_groups={"min_size": 3})
    rows = query(
        settings,
        "select peer_keys, f_fallback, f_below_min_size, n_peers from asof_peer_category_share",
    )
    assert {(tuple(k), f, b, n) for k, f, b, n in rows} == {
        (("GT",), True, True, 2),  # C1 and C3, pooled into the channel GT
        (("Modern Trade",), True, True, 1),  # C2 alone
    }


def test_ac2_the_unknown_customer_is_never_a_peer(built: Settings, tmp_path: Path) -> None:
    settings = inputs(built, tmp_path, peer_groups={"min_size": 1})
    assert query(
        settings,
        "select sum(n_peers) from (select distinct peer_columns, peer_keys, n_peers "
        "from asof_peer_category_share)",
    ) == [(3,)]


# AC3: the as-of date defaults to asof.date and can be overridden for one run ------


def test_ac3_the_default_as_of_date_is_asof_date(built: Settings, tmp_path: Path) -> None:
    settings = inputs(built, tmp_path)
    assert settings.asof.date == date(2020, 2, 29)
    assert query(settings, "select distinct as_of_date from asof_orders") == [(date(2020, 2, 29),)]


def test_ac3_with_asof_returns_a_copy_and_leaves_the_settings_alone(built: Settings) -> None:
    moved = with_asof(built, date(2019, 3, 1))
    assert moved.asof.date == date(2019, 3, 1)
    assert built.asof.date == date(2020, 2, 29)
    assert moved.paths == built.paths


def test_ac3_the_override_never_touches_the_config_file(built: Settings, tmp_path: Path) -> None:
    before = DEFAULT_SETTINGS_FILE.read_bytes()
    inputs(built, tmp_path, asof=date(2019, 3, 1))
    assert DEFAULT_SETTINGS_FILE.read_bytes() == before


def test_ac3_a_rebuild_for_another_date_replaces_the_inputs(
    built: Settings, tmp_path: Path
) -> None:
    settings = inputs(built, tmp_path, asof=date(2019, 2, 15))
    build_asof_inputs(with_asof(settings, date(2019, 5, 31)))
    assert query(settings, "select distinct as_of_date from asof_orders") == [(date(2019, 5, 31),)]
    assert query(settings, "select count(*) from asof_orders")[0][0] == 9


def test_ac3_an_as_of_date_before_any_sale_gives_empty_inputs(
    built: Settings, tmp_path: Path
) -> None:
    settings = inputs(built, tmp_path, asof=date(2018, 1, 1))
    for table in ASOF_INPUT_TABLES:
        assert query(settings, f"select count(*) from {table}") == [(0,)], table


# AC4: poison lines after the as-of date change nothing ------


def poison(settings: Settings) -> None:
    """Copy every sales line to 15 December 2019, with net sales 1000 times larger, directly in
    gold: a day for it in dim_date, the lines in the view's table and in the fact."""
    con = duckdb.connect(str(settings.paths.warehouse))
    try:
        con.execute(
            "insert into dim_date select * replace (20191215 as date_key, "
            "date '2019-12-15' as date, date '2019-12-01' as month_start, 12 as month, "
            "4 as quarter) from dim_date where date_key = 20190110"
        )
        con.execute(
            "insert into gold_net_sales_lines by name "
            "select sales_line_id + 1000 as sales_line_id, net_sales * 1000 as net_sales, "
            "net_sales_field_used, included, quantity, "
            "columns('^amount_') from gold_net_sales_lines"
        )
        con.execute(
            "insert into fact_sales by name select * replace ("
            "sales_line_id + 1000 as sales_line_id, "
            "net_sales * 1000 as net_sales, "
            "20191215 as date_key) "
            "from fact_sales"
        )
    finally:
        con.close()


def snapshot(settings: Settings) -> dict[str, list]:
    return {t: query(settings, f"select * from {t} order by all") for t in ASOF_INPUT_TABLES}


def test_ac4_poison_lines_after_the_as_of_date_change_no_input(
    built: Settings, tmp_path: Path
) -> None:
    clean = inputs(built, tmp_path / "clean", asof=date(2019, 3, 31))
    poisoned = copied(built, tmp_path / "poisoned")
    poison(poisoned)
    assert query(poisoned, "select count(*) from fact_sales where date_key = 20191215")[0][0] > 0
    build_asof_inputs(with_asof(poisoned, date(2019, 3, 31)))
    assert snapshot(poisoned) == snapshot(clean)


def test_ac4_the_same_poison_does_show_up_with_a_later_as_of_date(
    built: Settings, tmp_path: Path
) -> None:
    poisoned = copied(built, tmp_path)
    poison(poisoned)
    build_asof_inputs(with_asof(poisoned, date(2019, 12, 31)))
    assert (
        query(poisoned, "select count(*) from asof_orders where order_date = date '2019-12-15'")[0][
            0
        ]
        > 0
    )


def test_ac4_a_line_with_no_date_is_left_out_because_it_cannot_be_placed_before_the_date(
    tmp_path: Path,
) -> None:
    settings = load_settings(
        env={
            "REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb"),
            "REVINT_PATHS_BRONZE": str(tmp_path / "b"),
        }
    )
    build(settings, [sale(8, "X", "2019-01-10", "5"), sale(9, "X", None, "7")])
    run_gold(settings)
    build_asof_inputs(settings)
    # the mart counts the undated line; the as-of inputs do not (spec 04 P1)
    assert query(settings, "select sum(net_sales) from mart_customer_month") == [
        (Decimal("12.0000"),)
    ]
    assert query(settings, "select sum(net_sales) from asof_customer_month") == [
        (Decimal("5.0000"),)
    ]
    assert query(
        settings, "select count(*) from asof_customer_month where month_start is null"
    ) == [(0,)]


# AC5: at the last date the inputs equal the marts ------


def last_day_inputs(built: Settings, tmp_path: Path, **sections) -> Settings:
    return inputs(built, tmp_path, asof=LAST_DAY, **sections)


@pytest.mark.parametrize("zero_fill", [True, False])
def test_ac5_customer_month_equals_the_mart(
    built: Settings, tmp_path: Path, zero_fill: bool
) -> None:
    settings = gold(built, tmp_path / "g", marts={"zero_fill": zero_fill})
    build_asof_inputs(with_asof(settings, LAST_DAY))
    columns = "customer_key, month_start, net_sales, n_lines, f_zero_filled"
    assert query(settings, f"select {columns} from asof_customer_month order by all") == query(
        settings, f"select {columns} from mart_customer_month order by all"
    )


@pytest.mark.parametrize("zero_fill", [True, False])
def test_ac5_customer_category_month_equals_the_mart(
    built: Settings, tmp_path: Path, zero_fill: bool
) -> None:
    settings = gold(built, tmp_path / "g", marts={"zero_fill": zero_fill})
    build_asof_inputs(with_asof(settings, LAST_DAY))
    columns = (
        "customer_key, category, month_start, net_sales, n_lines, f_zero_filled, f_unknown_category"
    )
    assert query(
        settings, f"select {columns} from asof_customer_category_month order by all"
    ) == query(settings, f"select {columns} from mart_customer_category_month order by all")


def test_ac5_customer_profile_equals_the_mart(built: Settings, tmp_path: Path) -> None:
    settings = last_day_inputs(built, tmp_path)
    columns = (
        "customer_key, last_order_date, n_orders, median_interval_days, mean_interval_days, "
        "peer_keys"
    )
    assert query(settings, f"select {columns} from asof_customer_profile order by all") == query(
        settings, f"select {columns} from mart_customer_profile order by all"
    )


@pytest.mark.parametrize("min_size", [1, 2, 10])
def test_ac5_peer_category_share_equals_the_mart(
    built: Settings, tmp_path: Path, min_size: int
) -> None:
    settings = gold(built, tmp_path / "g", peer_groups={"min_size": min_size})
    build_asof_inputs(with_asof(settings, LAST_DAY))
    columns = (
        "peer_columns, peer_keys, f_fallback, f_below_min_size, category, n_peers, n_buying, "
        "penetration, median_buyer_net_sales, total_net_sales, n_lines, f_unknown_category"
    )
    assert query(settings, f"select {columns} from asof_peer_category_share order by all") == query(
        settings, f"select {columns} from mart_peer_category_share order by all"
    )


# AC6: lines with included = false add nothing ------


def test_ac6_a_not_included_line_adds_no_order_or_net_sales(
    built: Settings, tmp_path: Path
) -> None:
    settings = gold(built, tmp_path, net_sales={"exclude_flags": ["f_negative_value"]})
    build_asof_inputs(settings)
    assert query(
        settings, "select count(*) from asof_orders where order_date = date '2019-04-10'"
    ) == [(0,)]  # C1's only April line is a return, so it is not included
    assert query(settings, "select sum(net_sales) from asof_customer_month") == query(
        settings, "select sum(net_sales) from fact_sales where included"
    )


def test_ac6_the_totals_equal_the_fact_total_of_included_rows(
    built: Settings, tmp_path: Path
) -> None:
    settings = inputs(built, tmp_path)
    fact = query(settings, "select sum(net_sales) from fact_sales where included")
    # the fixture has no undated line, so every dated included line is counted
    for table in ("asof_orders", "asof_customer_month", "asof_customer_category_month"):
        assert query(settings, f"select sum(net_sales) from {table}") == fact, table


# Run behaviour and safety ------


def test_the_inputs_need_the_gold_layer(tmp_path: Path) -> None:
    settings = load_settings(env={"REVINT_PATHS_WAREHOUSE": str(tmp_path / "none.duckdb")})
    with pytest.raises(OpportunitiesError, match="revint build gold"):
        build_asof_inputs(settings)


def test_a_rerun_gives_identical_inputs(built: Settings, tmp_path: Path) -> None:
    settings = inputs(built, tmp_path, asof=date(2019, 3, 31))
    first = snapshot(settings)
    build_asof_inputs(with_asof(settings, date(2019, 3, 31)))
    assert snapshot(settings) == first


def test_building_the_inputs_leaves_gold_untouched(built: Settings, tmp_path: Path) -> None:
    settings = copied(built, tmp_path)
    before = {
        t: query(settings, f"select count(*) from {t}")
        for t in ("fact_sales", "mart_customer_month")
    }
    build_asof_inputs(settings)
    assert {t: query(settings, f"select count(*) from {t}") for t in before} == before


def test_logs_and_inputs_hold_no_customer_codes(
    built: Settings, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        settings = inputs(built, tmp_path)
    assert S not in caplog.text
    for table in ("asof_orders", "asof_customer_month", "asof_customer_profile"):
        assert S not in repr(query(settings, f"select * from {table}"))


# AC7 ------


def test_ac7_every_ac_has_a_test_in_this_module() -> None:
    text = Path(__file__).read_text(encoding="utf-8")
    for ac in range(1, 7):
        assert f"def test_ac{ac}_" in text


@pytest.mark.realdata
def test_ac1_ac4_ac5_real_file_inputs(tmp_path: Path) -> None:
    """Counts and sums only. Silver, gold and the inputs build on a temporary warehouse."""
    real = load_settings(env={"REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb")})
    if not list(real.paths.bronze.glob("*__RAW_SCJ_SALES.parquet")):
        pytest.skip("bronze not built: run `uv run revint build bronze` first")
    from revint.silver import run_silver

    run_silver(real)
    run_gold(real)
    build_asof_inputs(real)
    for asof_table, mart in (
        ("asof_customer_month", "mart_customer_month"),
        ("asof_customer_profile", "mart_customer_profile"),
        ("asof_peer_category_share", "mart_peer_category_share"),
    ):
        assert query(real, f"select count(*) from {asof_table}") == query(
            real, f"select count(*) from {mart}"
        ), asof_table
    assert query(real, "select sum(net_sales) from asof_customer_month") == query(
        real, "select sum(net_sales) from mart_customer_month"
    )
    build_asof_inputs(with_asof(real, date(2019, 6, 30)))
    assert query(real, "select max(order_date) from asof_orders")[0][0] <= date(2019, 6, 30)
    assert query(real, "select count(*) from asof_customer_profile")[0][0] < 12_240
