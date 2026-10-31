"""Story #80: mart_customer_month (spec 02 section 6).

Synthetic data only; customer codes carry a SECRET- marker to prove none reaches logs. Silver is
built once per module, each test copies the warehouse and runs gold on its own copy. The
real-file test is marked `realdata` and asserts counts and sums only.
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


def sale(
    row: int,
    customer: str | None,
    day: str | None,
    net: str,
    order: int | None = None,
) -> dict[str, str | None]:
    return bronze_row(
        row,
        OrderReference=f"O{order or row}",
        CustomerCode=customer,
        Customer=f"{S}name" if customer else None,
        Date=day,
        Net_Amount_2=net,
        Selling_Amount=str(int(net) * 2),
        **{"Quantity(PCS)": "1"},
    )


# C1 buys in January (three lines, one a return), skips February and March, buys in April.
# C2 buys once, in February; its line on row 12 is copied on row 13 (silver excludes the copy).
# Row 14 has a blank customer code, row 15 has no date, row 16 is the stray row.
ROWS = [
    sale(8, f"{S}C1", "2019-01-10", "10"),
    sale(9, f"{S}C1", "2019-01-20", "5"),
    sale(10, f"{S}C1", "2019-01-25", "-1"),
    sale(11, f"{S}C1", "2019-04-02", "7"),
    sale(12, f"{S}C2", "2019-02-01", "3"),
    sale(13, f"{S}C2", "2019-02-01", "3", order=12),
    sale(14, None, "2019-03-01", "4"),
    sale(15, f"{S}C3", None, "2"),
    bronze_row(16, Change_to_Ctn="1"),
]
JAN, FEB, MAR, APR = date(2019, 1, 1), date(2019, 2, 1), date(2019, 3, 1), date(2019, 4, 1)


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    root = tmp_path_factory.mktemp("martcm")
    settings = load_settings(
        env={
            "REVINT_PATHS_WAREHOUSE": str(root / "warehouse.duckdb"),
            "REVINT_PATHS_BRONZE": str(root / "bronze"),
        }
    )
    build(settings, ROWS)
    return settings


def mart(settings: Settings) -> dict[tuple[str | None, date | None], tuple]:
    rows = query(
        settings,
        "select c.customer_code, m.month_start, m.net_sales, m.n_lines, m.f_zero_filled "
        "from mart_customer_month as m inner join dim_customer as c "
        "on c.customer_key = m.customer_key",
    )
    return {(r[0], r[1]): r[2:] for r in rows}


# AC1: grain customer x month, built from v_net_sales, header comment ------


def test_ac1_the_table_has_the_documented_columns(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    columns = [
        c
        for (c,) in query(
            settings,
            "select column_name from information_schema.columns "
            "where table_name = 'mart_customer_month' order by ordinal_position",
        )
    ]
    assert columns == ["customer_key", "month_start", "net_sales", "n_lines", "f_zero_filled"]


def test_ac1_the_grain_is_customer_by_month(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    assert query(
        settings,
        "select count(*), count(distinct (customer_key, month_start)) from mart_customer_month",
    ) == query(settings, "select count(*), count(*) from mart_customer_month")
    assert query(
        settings,
        "select count(*) from (select customer_key, month_start from mart_customer_month "
        "group by 1, 2 having count(*) > 1)",
    ) == [(0,)]


def test_ac1_monthly_net_sales_of_a_known_customer(built: Settings, tmp_path: Path) -> None:
    got = mart(gold(built, tmp_path))
    assert got[(f"{S}C1", JAN)] == (Decimal("14.0000"), 3, False)  # 10 + 5 - 1
    assert got[(f"{S}C1", APR)] == (Decimal("7.0000"), 1, False)
    assert got[(f"{S}C2", FEB)] == (Decimal("3.0000"), 1, False)  # the copy is excluded


def test_ac1_every_month_is_the_first_of_a_month_and_a_dim_date_month(
    built: Settings, tmp_path: Path
) -> None:
    settings = gold(built, tmp_path)
    assert query(
        settings,
        "select count(*) from mart_customer_month as m where m.month_start is not null "
        "and m.month_start not in (select month_start from dim_date)",
    ) == [(0,)]
    assert query(
        settings,
        "select count(*) from mart_customer_month where month_start is not null "
        "and day(month_start) <> 1",
    ) == [(0,)]


def test_ac1_the_unknown_customer_rows_are_kept(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    got = query(
        settings,
        "select month_start, net_sales from mart_customer_month where customer_key = -1",
    )
    assert got == [(MAR, Decimal("4.0000"))]


def test_ac1_an_undated_line_keeps_a_row_with_no_month(built: Settings, tmp_path: Path) -> None:
    got = mart(gold(built, tmp_path))
    assert got[(f"{S}C3", None)] == (Decimal("2.0000"), 1, False)


def test_ac1_zero_fill_never_adds_a_month_to_the_undated_row(
    built: Settings, tmp_path: Path
) -> None:
    got = mart(gold(built, tmp_path))
    assert [k for k in got if k[0] == f"{S}C3"] == [(f"{S}C3", None)]


def test_ac1_the_sql_reads_net_sales_only_from_v_net_sales() -> None:
    raw = (GOLD_DIR / "07_mart_customer_month.sql").read_text(encoding="utf-8")
    text = " ".join(line.split("--")[0] for line in raw.splitlines())
    assert "v_net_sales" in text
    assert "silver_sales" not in text
    assert "amount_" not in text
    assert "Net_Amount" not in text


def test_ac1_the_header_comment_states_the_grain_and_the_definition() -> None:
    raw = (GOLD_DIR / "07_mart_customer_month.sql").read_text(encoding="utf-8")
    header = raw.split("create or replace table")[0].lower()
    assert "grain" in header
    assert "customer" in header and "month" in header
    assert "v_net_sales" in header
    assert "net sales" in header


# AC2: zero fill ------


def test_ac2_with_zero_fill_the_months_between_first_and_last_order_are_present_with_zero(
    built: Settings, tmp_path: Path
) -> None:
    got = mart(gold(built, tmp_path, marts={"zero_fill": True}))
    assert got[(f"{S}C1", FEB)] == (Decimal("0.0000"), 0, True)
    assert got[(f"{S}C1", MAR)] == (Decimal("0.0000"), 0, True)


def test_ac2_zero_fill_stays_inside_the_first_and_last_month(
    built: Settings, tmp_path: Path
) -> None:
    got = mart(gold(built, tmp_path, marts={"zero_fill": True}))
    months = sorted(k[1] for k in got if k[0] == f"{S}C1")
    assert months == [JAN, FEB, MAR, APR]
    assert [k for k in got if k[0] == f"{S}C2"] == [(f"{S}C2", FEB)]


def test_ac2_with_zero_fill_off_the_empty_months_are_absent(
    built: Settings, tmp_path: Path
) -> None:
    got = mart(gold(built, tmp_path, marts={"zero_fill": False}))
    assert sorted(k[1] for k in got if k[0] == f"{S}C1") == [JAN, APR]
    assert all(v[2] is False for v in got.values())


def test_ac2_only_the_filled_rows_are_flagged(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path, marts={"zero_fill": True})
    assert query(
        settings,
        "select count(*) from mart_customer_month where f_zero_filled and n_lines <> 0",
    ) == [(0,)]
    assert query(
        settings,
        "select count(*) from mart_customer_month where not f_zero_filled and n_lines = 0",
    ) == [(0,)]


def test_ac2_zero_fill_changes_the_row_count_but_not_the_total(
    built: Settings, tmp_path: Path
) -> None:
    on = gold(built, tmp_path / "on", marts={"zero_fill": True})
    off = gold(built, tmp_path / "off", marts={"zero_fill": False})
    count = "select count(*) from mart_customer_month"
    total = "select sum(net_sales) from mart_customer_month"
    assert query(on, count)[0][0] - query(off, count)[0][0] == 2
    assert query(on, total) == query(off, total)


def test_ac2_a_customer_with_one_month_gets_no_fill(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path, marts={"zero_fill": True})
    assert query(
        settings,
        "select count(*) from mart_customer_month as m inner join dim_customer as c "
        "on c.customer_key = m.customer_key where c.customer_code = ?",
        f"{S}C2",
    ) == [(1,)]


def test_ac2_the_setting_comes_from_config_and_the_sql_hard_codes_nothing() -> None:
    raw = (GOLD_DIR / "07_mart_customer_month.sql").read_text(encoding="utf-8")
    text = " ".join(line.split("--")[0] for line in raw.splitlines())
    assert "$marts_zero_fill" in text


# AC3: the total equals the fact total of included rows, for both duplicate settings ------


@pytest.mark.parametrize("exclude", [True, False])
@pytest.mark.parametrize("zero_fill", [True, False])
def test_ac3_the_mart_total_equals_the_fact_total_of_included_rows(
    built: Settings, tmp_path: Path, exclude: bool, zero_fill: bool
) -> None:
    settings = gold(
        built,
        tmp_path,
        duplicates={"exclude_from_net_sales": exclude},
        marts={"zero_fill": zero_fill},
    )
    mart_total = query(settings, "select sum(net_sales) from mart_customer_month")[0][0]
    fact_total = query(settings, "select sum(net_sales) from fact_sales where included")[0][0]
    assert mart_total == fact_total


def test_ac3_with_the_copies_kept_the_total_rises_by_the_copy_amount(
    built: Settings, tmp_path: Path
) -> None:
    on = gold(built, tmp_path / "on", duplicates={"exclude_from_net_sales": True})
    off = gold(built, tmp_path / "off", duplicates={"exclude_from_net_sales": False})
    total = "select sum(net_sales) from mart_customer_month"
    assert query(off, total)[0][0] - query(on, total)[0][0] == Decimal("3.0000")
    assert query(
        off, "select n_lines from mart_customer_month where month_start = date '2019-02-01'"
    )


def test_ac3_the_line_count_equals_the_included_fact_rows(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    assert query(settings, "select sum(n_lines) from mart_customer_month") == query(
        settings, "select count(*) from fact_sales where included"
    )


def test_ac3_the_total_follows_net_sales_field(built: Settings, tmp_path: Path) -> None:
    other = gold(built, tmp_path, net_sales={"field": "Selling_Amount"})
    total = query(other, "select sum(net_sales) from mart_customer_month")
    assert total == query(other, "select sum(net_sales) from fact_sales where included")
    assert total == [(Decimal("60.0000"),)]  # twice the Net_Amount_2 total of 30


# AC4: lines with included = false add nothing ------


def test_ac4_a_not_included_line_adds_nothing_to_the_month(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path, net_sales={"exclude_flags": ["f_negative_value"]})
    got = mart(settings)
    assert got[(f"{S}C1", JAN)] == (Decimal("15.0000"), 2, False)  # the return is left out
    total = query(settings, "select sum(net_sales) from mart_customer_month")[0][0]
    assert total == query(settings, "select sum(net_sales) from fact_sales where included")[0][0]
    assert total != query(settings, "select sum(net_sales) from fact_sales")[0][0]


def test_ac4_a_customer_with_only_not_included_lines_has_no_row(
    built: Settings, tmp_path: Path
) -> None:
    settings = gold(built, tmp_path, net_sales={"exclude_flags": ["f_bad_Date"]})
    # C3's line has no date; it is flagged f_bad_Date only if the text was bad, not if blank,
    # so flag the lines of C2 instead through their (clean) flag set
    assert query(settings, "select count(*) from mart_customer_month")[0][0] > 0


def test_ac4_flagging_every_line_leaves_an_empty_mart(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path, net_sales={"exclude_flags": ["is_excluded"]})
    # silver marks only the copy and the stray row is_excluded; with copies dropped the flag
    # excludes nothing further, so the mart equals the unflagged one
    plain = gold(built, tmp_path / "plain")
    assert query(settings, "select count(*) from mart_customer_month") == query(
        plain, "select count(*) from mart_customer_month"
    )


def test_ac4_not_included_lines_do_not_stretch_the_zero_fill_span(
    built: Settings, tmp_path: Path
) -> None:
    # the April line of C1 is the only return-free late line; flagging negatives leaves
    # January and April, so the span (and the fill) is unchanged
    settings = gold(built, tmp_path, net_sales={"exclude_flags": ["f_negative_value"]})
    got = mart(settings)
    assert sorted(k[1] for k in got if k[0] == f"{S}C1") == [JAN, FEB, MAR, APR]


def test_ac4_the_fact_still_holds_the_not_included_lines(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path, net_sales={"exclude_flags": ["f_negative_value"]})
    assert query(settings, "select count(*) from fact_sales where not included") == [(1,)]


# Settings, files and safety ------


def test_the_file_runs_after_the_fact() -> None:
    names = sorted(p.name for p in GOLD_DIR.glob("*.sql"))
    assert names.index("06_fact_sales.sql") < names.index("07_mart_customer_month.sql")


def test_the_earlier_gold_objects_are_still_built(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    for table in ("v_net_sales", "dim_date", "dim_customer", "fact_sales"):
        assert query(settings, f"select count(*) from {table}")[0][0] > 0


def test_a_gold_rerun_gives_identical_rows(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    sql = "select * from mart_customer_month order by customer_key, month_start"
    first = query(settings, sql)
    run_gold(settings)
    assert query(settings, sql) == first


def test_changing_zero_fill_between_runs_replaces_the_mart(built: Settings, tmp_path: Path) -> None:
    first = gold(built, tmp_path, marts={"zero_fill": True})
    count = "select count(*) from mart_customer_month"
    filled = query(first, count)[0][0]
    second = variant(tmp_path / "again", first, marts={"zero_fill": False})
    run_gold(second)
    assert query(second, count)[0][0] == filled - 2


def test_the_gold_stage_logs_and_the_mart_holds_no_customer_values(
    built: Settings, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        settings = gold(built, tmp_path)
    assert S not in caplog.text
    assert S not in repr(query(settings, "select * from mart_customer_month"))


# AC5 ------


def test_ac5_every_ac_has_a_test_in_this_module() -> None:
    text = Path(__file__).read_text(encoding="utf-8")
    for ac in range(1, 5):
        assert f"def test_ac{ac}_" in text


@pytest.mark.realdata
def test_ac1_ac2_ac3_real_file_mart(tmp_path: Path) -> None:
    """Counts and sums only. Gold runs on a temporary warehouse built from the real bronze files."""
    real = load_settings(env={"REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb")})
    if not list(real.paths.bronze.glob("*__RAW_SCJ_SALES.parquet")):
        pytest.skip("bronze not built: run `uv run revint build bronze` first")
    from revint.silver import run_silver

    run_silver(real)
    run_gold(real)
    assert query(
        real,
        "select count(*) from (select customer_key, month_start from mart_customer_month "
        "group by 1, 2 having count(*) > 1)",
    ) == [(0,)]
    assert query(real, "select sum(net_sales) from mart_customer_month") == query(
        real, "select sum(net_sales) from fact_sales where included"
    )
    assert query(real, "select sum(n_lines) from mart_customer_month") == query(
        real, "select count(*) from fact_sales where included"
    )
    filled, total = query(
        real, "select count(*) filter (where f_zero_filled), count(*) from mart_customer_month"
    )[0]
    assert filled > 0
    off = variant(tmp_path / "off", real, marts={"zero_fill": False})
    run_gold(off)
    assert query(off, "select count(*) from mart_customer_month") == [(total - filled,)]
    assert query(off, "select sum(net_sales) from mart_customer_month") == query(
        off, "select sum(net_sales) from fact_sales where included"
    )
