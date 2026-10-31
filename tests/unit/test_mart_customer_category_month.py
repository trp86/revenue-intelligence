"""Story #81: mart_customer_category_month (spec 02 section 6).

Synthetic data only; customer codes and categories carry a SECRET- marker to prove none reaches
logs. Silver is built once per module, each test copies the warehouse and runs gold on its own
copy. The real-file test is marked `realdata` and asserts counts and sums only.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from gold_helpers import gold, variant
from silver_helpers import bronze_row, build, query

from revint.config import Settings, load_settings
from revint.gold import GOLD_DIR, run_gold

S = "SECRET-"
CAT_A, CAT_B = f"{S}A", f"{S}B"


def sale(
    row: int,
    customer: str | None,
    product: str | None,
    category: str | None,
    day: str | None,
    net: str,
    order: int | None = None,
) -> dict[str, str | None]:
    return bronze_row(
        row,
        OrderReference=f"O{order or row}",
        CustomerCode=customer,
        Customer=f"{S}name" if customer else None,
        SCJ_CODE_1=product,
        Internal_Category=category,
        Date=day,
        Net_Amount_2=net,
        Selling_Amount=str(int(net) * 2),
        **{"Quantity(PCS)": "1"},
    )


# C1: category A in January (two lines, one a return) and April; category B in February.
# C2: a product with no category, bought in January and March.
# C3: a copy of its own line (silver excludes the copy), a blank customer, an undated line.
ROWS = [
    sale(8, f"{S}C1", "P1", CAT_A, "2019-01-10", "10"),
    sale(9, f"{S}C1", "P1", CAT_A, "2019-01-20", "5"),
    sale(10, f"{S}C1", "P1", CAT_A, "2019-01-25", "-1"),
    sale(11, f"{S}C1", "P1", CAT_A, "2019-04-02", "7"),
    sale(12, f"{S}C1", "P2", CAT_B, "2019-02-05", "3"),
    sale(13, f"{S}C2", "P3", None, "2019-01-03", "4"),
    sale(14, f"{S}C2", "P3", None, "2019-03-03", "6"),
    sale(15, f"{S}C3", "P1", CAT_A, "2019-05-01", "2"),
    sale(16, f"{S}C3", "P1", CAT_A, "2019-05-01", "2", order=15),
    sale(17, None, "P2", CAT_B, "2019-02-10", "8"),
    sale(18, f"{S}C3", "P2", CAT_B, None, "9"),
    bronze_row(19, Change_to_Ctn="1"),
]
JAN, FEB, MAR, APR, MAY = (date(2019, m, 1) for m in range(1, 6))


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    root = tmp_path_factory.mktemp("martccm")
    settings = load_settings(
        env={
            "REVINT_PATHS_WAREHOUSE": str(root / "warehouse.duckdb"),
            "REVINT_PATHS_BRONZE": str(root / "bronze"),
        }
    )
    build(settings, ROWS)
    return settings


def mart(settings: Settings) -> dict[tuple[str | None, str, date | None], tuple]:
    rows = query(
        settings,
        "select c.customer_code, m.category, m.month_start, m.net_sales, m.n_lines, "
        "m.f_zero_filled, m.f_unknown_category "
        "from mart_customer_category_month as m inner join dim_customer as c "
        "on c.customer_key = m.customer_key",
    )
    return {(r[0], r[1], r[2]): r[3:] for r in rows}


# AC1: grain customer x category x month, built from v_net_sales, header comment ------


def test_ac1_the_table_has_the_documented_columns(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    columns = [
        c
        for (c,) in query(
            settings,
            "select column_name from information_schema.columns "
            "where table_name = 'mart_customer_category_month' order by ordinal_position",
        )
    ]
    assert columns == [
        "customer_key",
        "category",
        "month_start",
        "net_sales",
        "n_lines",
        "f_zero_filled",
        "f_unknown_category",
    ]


def test_ac1_the_grain_is_customer_by_category_by_month(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    assert query(
        settings,
        "select count(*) from (select customer_key, category, month_start "
        "from mart_customer_category_month group by 1, 2, 3 having count(*) > 1)",
    ) == [(0,)]


def test_ac1_monthly_net_sales_of_a_known_customer_and_category(
    built: Settings, tmp_path: Path
) -> None:
    got = mart(gold(built, tmp_path))
    assert got[(f"{S}C1", CAT_A, JAN)] == (Decimal("14.0000"), 3, False, False)
    assert got[(f"{S}C1", CAT_A, APR)] == (Decimal("7.0000"), 1, False, False)
    assert got[(f"{S}C1", CAT_B, FEB)] == (Decimal("3.0000"), 1, False, False)


def test_ac1_a_customer_has_a_row_for_each_category_it_bought(
    built: Settings, tmp_path: Path
) -> None:
    got = mart(gold(built, tmp_path))
    assert {k[1] for k in got if k[0] == f"{S}C1"} == {CAT_A, CAT_B}
    assert {k[1] for k in got if k[0] == f"{S}C3"} == {CAT_A, CAT_B}


def test_ac1_the_category_comes_from_dim_product_through_the_fact(
    built: Settings, tmp_path: Path
) -> None:
    settings = gold(built, tmp_path)
    assert query(
        settings,
        "select count(*) from mart_customer_category_month as m "
        "where m.category not in (select category from dim_product)",
    ) == [(0,)]


def test_ac1_the_unknown_customer_rows_are_kept(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    assert query(
        settings,
        "select category, month_start, net_sales from mart_customer_category_month "
        "where customer_key = -1",
    ) == [(CAT_B, FEB, Decimal("8.0000"))]


def test_ac1_an_undated_line_keeps_a_row_with_no_month(built: Settings, tmp_path: Path) -> None:
    got = mart(gold(built, tmp_path))
    assert got[(f"{S}C3", CAT_B, None)] == (Decimal("9.0000"), 1, False, False)


def test_ac1_the_sql_reads_net_sales_only_from_v_net_sales() -> None:
    raw = (GOLD_DIR / "08_mart_customer_category_month.sql").read_text(encoding="utf-8")
    text = " ".join(line.split("--")[0] for line in raw.splitlines())
    assert "v_net_sales" in text
    assert "silver_sales" not in text
    assert "amount_" not in text
    assert "Net_Amount" not in text
    assert "Internal_Category" not in text


def test_ac1_the_header_comment_states_the_grain_and_the_definition() -> None:
    raw = (GOLD_DIR / "08_mart_customer_category_month.sql").read_text(encoding="utf-8")
    header = raw.split("create or replace table")[0].lower()
    for word in ("grain", "customer", "category", "month", "v_net_sales", "net sales"):
        assert word in header


# AC2: a product with category Unknown keeps its rows, flagged ------


def test_ac2_rows_of_a_product_with_no_category_are_kept_and_flagged(
    built: Settings, tmp_path: Path
) -> None:
    got = mart(gold(built, tmp_path))
    assert got[(f"{S}C2", "Unknown", JAN)] == (Decimal("4.0000"), 1, False, True)
    assert got[(f"{S}C2", "Unknown", MAR)] == (Decimal("6.0000"), 1, False, True)


def test_ac2_only_the_unknown_category_is_flagged(built: Settings, tmp_path: Path) -> None:
    got = mart(gold(built, tmp_path))
    flagged = {k[1] for k, v in got.items() if v[3]}
    assert flagged == {"Unknown"}
    assert all(v[3] is (k[1] == "Unknown") for k, v in got.items())


def test_ac2_unknown_category_net_sales_stay_in_the_total(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    unknown = query(
        settings,
        "select sum(net_sales) from mart_customer_category_month where f_unknown_category",
    )[0][0]
    assert unknown == Decimal("10.0000")


def test_ac2_a_line_with_no_product_falls_in_the_unknown_category(tmp_path: Path) -> None:
    settings = load_settings(
        env={
            "REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb"),
            "REVINT_PATHS_BRONZE": str(tmp_path / "b"),
        }
    )
    build(settings, [sale(8, "C", None, CAT_A, "2019-01-05", "5")])
    run_gold(settings)
    assert query(
        settings,
        "select category, f_unknown_category, net_sales from mart_customer_category_month",
    ) == [("Unknown", True, Decimal("5.0000"))]


# AC3: zero fill ------


def test_ac3_with_zero_fill_empty_months_inside_a_category_span_are_present_with_zero(
    built: Settings, tmp_path: Path
) -> None:
    got = mart(gold(built, tmp_path, marts={"zero_fill": True}))
    assert got[(f"{S}C1", CAT_A, FEB)] == (Decimal("0.0000"), 0, True, False)
    assert got[(f"{S}C1", CAT_A, MAR)] == (Decimal("0.0000"), 0, True, False)
    assert got[(f"{S}C2", "Unknown", FEB)] == (Decimal("0.0000"), 0, True, True)


def test_ac3_the_fill_is_per_customer_and_category_not_per_customer(
    built: Settings, tmp_path: Path
) -> None:
    got = mart(gold(built, tmp_path, marts={"zero_fill": True}))
    months_b = sorted(k[2] for k in got if k[0] == f"{S}C1" and k[1] == CAT_B)
    assert months_b == [FEB]  # category B was bought once: no fill outside its own span
    months_a = sorted(k[2] for k in got if k[0] == f"{S}C1" and k[1] == CAT_A)
    assert months_a == [JAN, FEB, MAR, APR]


def test_ac3_with_zero_fill_off_the_empty_months_are_absent(
    built: Settings, tmp_path: Path
) -> None:
    got = mart(gold(built, tmp_path, marts={"zero_fill": False}))
    assert sorted(k[2] for k in got if k[0] == f"{S}C1" and k[1] == CAT_A) == [JAN, APR]
    assert all(v[2] is False for v in got.values())


def test_ac3_zero_fill_changes_the_row_count_but_not_the_total(
    built: Settings, tmp_path: Path
) -> None:
    on = gold(built, tmp_path / "on", marts={"zero_fill": True})
    off = gold(built, tmp_path / "off", marts={"zero_fill": False})
    count = "select count(*) from mart_customer_category_month"
    total = "select sum(net_sales) from mart_customer_category_month"
    assert query(on, count)[0][0] - query(off, count)[0][0] == 3  # C1/A: Feb, Mar; C2/Unknown: Feb
    assert query(on, total) == query(off, total)


def test_ac3_only_the_filled_rows_are_flagged(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path, marts={"zero_fill": True})
    assert query(
        settings,
        "select count(*) from mart_customer_category_month where f_zero_filled <> (n_lines = 0)",
    ) == [(0,)]


def test_ac3_the_setting_comes_from_config() -> None:
    raw = (GOLD_DIR / "08_mart_customer_category_month.sql").read_text(encoding="utf-8")
    text = " ".join(line.split("--")[0] for line in raw.splitlines())
    assert "$marts_zero_fill" in text


# AC4: the total equals the fact total; the customer x month rollup equals the other mart ------


@pytest.mark.parametrize("exclude", [True, False])
@pytest.mark.parametrize("zero_fill", [True, False])
def test_ac4_the_total_equals_the_fact_total_of_included_rows(
    built: Settings, tmp_path: Path, exclude: bool, zero_fill: bool
) -> None:
    settings = gold(
        built,
        tmp_path,
        duplicates={"exclude_from_net_sales": exclude},
        marts={"zero_fill": zero_fill},
    )
    mart_total = query(settings, "select sum(net_sales) from mart_customer_category_month")[0][0]
    fact_total = query(settings, "select sum(net_sales) from fact_sales where included")[0][0]
    assert mart_total == fact_total
    assert query(settings, "select sum(n_lines) from mart_customer_category_month") == query(
        settings, "select count(*) from fact_sales where included"
    )


@pytest.mark.parametrize("exclude", [True, False])
@pytest.mark.parametrize("zero_fill", [True, False])
def test_ac4_the_customer_by_month_rollup_equals_mart_customer_month(
    built: Settings, tmp_path: Path, exclude: bool, zero_fill: bool
) -> None:
    settings = gold(
        built,
        tmp_path,
        duplicates={"exclude_from_net_sales": exclude},
        marts={"zero_fill": zero_fill},
    )
    differing = query(
        settings,
        "with roll as (select customer_key, month_start, sum(net_sales) as net_sales, "
        "sum(n_lines) as n_lines from mart_customer_category_month group by 1, 2) "
        "select count(*) from roll full join mart_customer_month as m "
        "on roll.customer_key = m.customer_key "
        "and roll.month_start is not distinct from m.month_start "
        "where coalesce(roll.net_sales, 0) <> coalesce(m.net_sales, 0) "
        "or coalesce(roll.n_lines, 0) <> coalesce(m.n_lines, 0)",
    )
    assert differing == [(0,)]


def test_ac4_not_included_lines_add_nothing(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path, net_sales={"exclude_flags": ["f_negative_value"]})
    got = mart(settings)
    assert got[(f"{S}C1", CAT_A, JAN)] == (Decimal("15.0000"), 2, False, False)
    assert query(settings, "select sum(net_sales) from mart_customer_category_month") == query(
        settings, "select sum(net_sales) from fact_sales where included"
    )


def test_ac4_the_total_follows_net_sales_field(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path, net_sales={"field": "Selling_Amount"})
    total = query(settings, "select sum(net_sales) from mart_customer_category_month")
    assert total == query(settings, "select sum(net_sales) from fact_sales where included")
    assert total == [(Decimal("106.0000"),)]  # twice the Net_Amount_2 total of 53


# Settings, files and safety ------


def test_the_file_runs_after_mart_customer_month() -> None:
    names = sorted(p.name for p in GOLD_DIR.glob("*.sql"))
    assert names.index("07_mart_customer_month.sql") < names.index(
        "08_mart_customer_category_month.sql"
    )


def test_the_earlier_gold_objects_are_still_built(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    for table in ("v_net_sales", "fact_sales", "dim_product", "mart_customer_month"):
        assert query(settings, f"select count(*) from {table}")[0][0] > 0


def test_a_gold_rerun_gives_identical_rows(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    sql = "select * from mart_customer_category_month order by 1, 2, 3"
    first = query(settings, sql)
    run_gold(settings)
    assert query(settings, sql) == first


def test_changing_zero_fill_between_runs_replaces_the_mart(built: Settings, tmp_path: Path) -> None:
    first = gold(built, tmp_path, marts={"zero_fill": True})
    count = "select count(*) from mart_customer_category_month"
    filled = query(first, count)[0][0]
    second = variant(tmp_path / "again", first, marts={"zero_fill": False})
    run_gold(second)
    assert query(second, count)[0][0] == filled - 3


def test_the_gold_stage_logs_and_the_mart_holds_no_customer_values(
    built: Settings, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        settings = gold(built, tmp_path)
    assert S not in caplog.text
    # the mart holds a category name (a dimension value, as dim_product does) but no customer
    codes = query(
        settings, "select customer_key, month_start, net_sales from mart_customer_category_month"
    )
    assert S not in repr(codes)


# AC5 ------


def test_ac5_every_ac_has_a_test_in_this_module() -> None:
    text = Path(__file__).read_text(encoding="utf-8")
    for ac in range(1, 5):
        assert f"def test_ac{ac}_" in text


@pytest.mark.realdata
def test_ac1_ac3_ac4_real_file_mart(tmp_path: Path) -> None:
    """Counts and sums only. Gold runs on a temporary warehouse built from the real bronze files."""
    real = load_settings(env={"REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb")})
    if not list(real.paths.bronze.glob("*__RAW_SCJ_SALES.parquet")):
        pytest.skip("bronze not built: run `uv run revint build bronze` first")
    from revint.silver import run_silver

    run_silver(real)
    run_gold(real)
    assert query(
        real,
        "select count(*) from (select customer_key, category, month_start "
        "from mart_customer_category_month group by 1, 2, 3 having count(*) > 1)",
    ) == [(0,)]
    assert query(real, "select sum(net_sales) from mart_customer_category_month") == query(
        real, "select sum(net_sales) from fact_sales where included"
    )
    assert query(real, "select sum(n_lines) from mart_customer_category_month") == query(
        real, "select count(*) from fact_sales where included"
    )
    rollup = query(
        real,
        "with roll as (select customer_key, month_start, sum(net_sales) as net_sales "
        "from mart_customer_category_month group by 1, 2) "
        "select count(*) from roll full join mart_customer_month as m "
        "on roll.customer_key = m.customer_key "
        "and roll.month_start is not distinct from m.month_start "
        "where coalesce(roll.net_sales, 0) <> coalesce(m.net_sales, 0)",
    )
    assert rollup == [(0,)]
    unknown = query(
        real, "select count(*) from mart_customer_category_month where f_unknown_category"
    )[0][0]
    assert unknown > 0
    filled, total = query(
        real,
        "select count(*) filter (where f_zero_filled), count(*) from mart_customer_category_month",
    )[0]
    off = variant(tmp_path / "off", real, marts={"zero_fill": False})
    run_gold(off)
    assert query(off, "select count(*) from mart_customer_category_month") == [(total - filled,)]
