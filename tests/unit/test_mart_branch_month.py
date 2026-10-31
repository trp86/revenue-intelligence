"""Story #84: mart_branch_month (spec 02 section 6).

Synthetic data only. Silver is built once per module, each test copies the warehouse and runs
gold on its own copy. The real-file test is marked `realdata` and asserts counts and sums only.
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
    branch: str | None,
    day: str | None,
    net: str,
    order: int | None = None,
) -> dict[str, str | None]:
    """A sales line; two lines with the same `order` and values are exact duplicates."""
    return bronze_row(
        row,
        OrderReference=f"O{order or row}",
        CustomerCode=f"{S}C{order or row}",
        Branch_Name=branch,
        Date=day,
        Net_Amount_2=net,
        Selling_Amount=str(int(net) * 2),
        **{"Quantity(PCS)": "1"},
    )


# Magway sells in January (a return among three lines) and April; PYAY (mapped to Pyay) sells in
# February; row 13 is a copy of row 12 (silver excludes it); one line has no branch and one no
# date; row 17 is the stray row.
ROWS = [
    sale(8, "Magway", "2019-01-10", "10"),
    sale(9, "Magway", "2019-01-20", "5"),
    sale(10, "Magway", "2019-01-25", "-1"),
    sale(11, "Magway", "2019-04-02", "7"),
    sale(12, "PYAY", "2019-02-05", "3"),
    sale(13, "PYAY", "2019-02-05", "3", order=12),
    sale(14, None, "2019-03-01", "4"),
    sale(15, "Magway", None, "2"),
    sale(16, "Dawei", "2019-02-20", "6"),
    bronze_row(17, Change_to_Ctn="1"),
]
JAN, FEB, MAR, APR = (date(2019, m, 1) for m in range(1, 5))


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    root = tmp_path_factory.mktemp("martbm")
    settings = load_settings(
        env={
            "REVINT_PATHS_WAREHOUSE": str(root / "warehouse.duckdb"),
            "REVINT_PATHS_BRONZE": str(root / "bronze"),
        }
    )
    build(settings, ROWS)
    return settings


def mart(settings: Settings) -> dict[tuple[str, date | None], tuple]:
    rows = query(
        settings,
        "select b.branch_name, m.month_start, m.net_sales, m.n_lines, m.f_zero_filled "
        "from mart_branch_month as m inner join dim_branch as b on b.branch_key = m.branch_key",
    )
    return {(r[0], r[1]): r[2:] for r in rows}


# AC1: grain branch x month, built from v_net_sales, header comment ------


def test_ac1_the_table_has_the_documented_columns(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    columns = [
        c
        for (c,) in query(
            settings,
            "select column_name from information_schema.columns "
            "where table_name = 'mart_branch_month' order by ordinal_position",
        )
    ]
    assert columns == ["branch_key", "month_start", "net_sales", "n_lines", "f_zero_filled"]


def test_ac1_the_grain_is_branch_by_month(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    assert query(
        settings,
        "select count(*) from (select branch_key, month_start from mart_branch_month "
        "group by 1, 2 having count(*) > 1)",
    ) == [(0,)]


def test_ac1_monthly_net_sales_of_a_known_branch(built: Settings, tmp_path: Path) -> None:
    got = mart(gold(built, tmp_path))
    assert got[("Magway", JAN)] == (Decimal("14.0000"), 3, False)  # 10 + 5 - 1
    assert got[("Magway", APR)] == (Decimal("7.0000"), 1, False)
    assert got[("Pyay", FEB)] == (Decimal("3.0000"), 1, False)  # the label map; the copy is out
    assert got[("Dawei", FEB)] == (Decimal("6.0000"), 1, False)


def test_ac1_an_undated_line_keeps_a_row_with_no_month(built: Settings, tmp_path: Path) -> None:
    assert mart(gold(built, tmp_path))[("Magway", None)] == (Decimal("2.0000"), 1, False)


def test_ac1_the_sql_reads_net_sales_only_from_v_net_sales() -> None:
    raw = (GOLD_DIR / "11_mart_branch_month.sql").read_text(encoding="utf-8")
    text = " ".join(line.split("--")[0] for line in raw.splitlines())
    assert "v_net_sales" in text
    assert "silver_sales" not in text
    assert "amount_" not in text and "Net_Amount" not in text and "Branch_Name" not in text


def test_ac1_the_header_comment_states_the_grain_and_the_definition() -> None:
    raw = (GOLD_DIR / "11_mart_branch_month.sql").read_text(encoding="utf-8")
    header = raw.split("create or replace table")[0].lower()
    for word in ("grain", "branch", "month", "v_net_sales", "net sales", "overview"):
        assert word in header


# AC2: the total equals the fact total of included rows; the unknown branch is kept ------


@pytest.mark.parametrize("exclude", [True, False])
@pytest.mark.parametrize("zero_fill", [True, False])
def test_ac2_the_total_equals_the_fact_total_of_included_rows(
    built: Settings, tmp_path: Path, exclude: bool, zero_fill: bool
) -> None:
    settings = gold(
        built,
        tmp_path,
        duplicates={"exclude_from_net_sales": exclude},
        marts={"zero_fill": zero_fill},
    )
    assert query(settings, "select sum(net_sales) from mart_branch_month") == query(
        settings, "select sum(net_sales) from fact_sales where included"
    )
    assert query(settings, "select sum(n_lines) from mart_branch_month") == query(
        settings, "select count(*) from fact_sales where included"
    )


def test_ac2_the_unknown_branch_is_kept(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    assert query(
        settings,
        "select month_start, net_sales from mart_branch_month where branch_key = -1",
    ) == [(MAR, Decimal("4.0000"))]


def test_ac2_not_included_lines_add_nothing(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path, net_sales={"exclude_flags": ["f_negative_value"]})
    assert mart(settings)[("Magway", JAN)] == (Decimal("15.0000"), 2, False)
    assert query(settings, "select sum(net_sales) from mart_branch_month") == query(
        settings, "select sum(net_sales) from fact_sales where included"
    )


def test_ac2_the_total_follows_net_sales_field(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path, net_sales={"field": "Selling_Amount"})
    total = query(settings, "select sum(net_sales) from mart_branch_month")
    assert total == query(settings, "select sum(net_sales) from fact_sales where included")
    assert total == [(Decimal("72.0000"),)]  # twice the Net_Amount_2 total of 36


def test_ac2_with_the_copies_kept_the_total_rises_by_the_copy_amount(
    built: Settings, tmp_path: Path
) -> None:
    on = gold(built, tmp_path / "on", duplicates={"exclude_from_net_sales": True})
    off = gold(built, tmp_path / "off", duplicates={"exclude_from_net_sales": False})
    total = "select sum(net_sales) from mart_branch_month"
    assert query(off, total)[0][0] - query(on, total)[0][0] == Decimal("3.0000")


def test_ac2_it_agrees_with_the_customer_month_mart_by_month(
    built: Settings, tmp_path: Path
) -> None:
    settings = gold(built, tmp_path, marts={"zero_fill": False})
    differing = query(
        settings,
        "with b as (select month_start, sum(net_sales) as ns from mart_branch_month group by 1), "
        "c as (select month_start, sum(net_sales) as ns from mart_customer_month group by 1) "
        "select count(*) from b full join c on b.month_start is not distinct from c.month_start "
        "where coalesce(b.ns, 0) <> coalesce(c.ns, 0)",
    )
    assert differing == [(0,)]


# AC3: zero fill ------


def test_ac3_with_zero_fill_empty_months_inside_a_branch_span_are_present_with_zero(
    built: Settings, tmp_path: Path
) -> None:
    got = mart(gold(built, tmp_path, marts={"zero_fill": True}))
    assert got[("Magway", FEB)] == (Decimal("0.0000"), 0, True)
    assert got[("Magway", MAR)] == (Decimal("0.0000"), 0, True)


def test_ac3_the_fill_stays_inside_each_branchs_own_first_and_last_month(
    built: Settings, tmp_path: Path
) -> None:
    got = mart(gold(built, tmp_path, marts={"zero_fill": True}))
    assert sorted(m for (b, m) in got if b == "Magway" and m) == [JAN, FEB, MAR, APR]
    assert [m for (b, m) in got if b == "Pyay"] == [FEB]
    assert [m for (b, m) in got if b == "Dawei"] == [FEB]


def test_ac3_with_zero_fill_off_the_empty_months_are_absent(
    built: Settings, tmp_path: Path
) -> None:
    got = mart(gold(built, tmp_path, marts={"zero_fill": False}))
    assert sorted(m for (b, m) in got if b == "Magway" and m) == [JAN, APR]
    assert all(v[2] is False for v in got.values())


def test_ac3_zero_fill_changes_the_row_count_but_not_the_total(
    built: Settings, tmp_path: Path
) -> None:
    on = gold(built, tmp_path / "on", marts={"zero_fill": True})
    off = gold(built, tmp_path / "off", marts={"zero_fill": False})
    count = "select count(*) from mart_branch_month"
    total = "select sum(net_sales) from mart_branch_month"
    assert query(on, count)[0][0] - query(off, count)[0][0] == 2  # Magway: Feb and Mar
    assert query(on, total) == query(off, total)


def test_ac3_only_the_filled_rows_are_flagged(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path, marts={"zero_fill": True})
    assert query(
        settings, "select count(*) from mart_branch_month where f_zero_filled <> (n_lines = 0)"
    ) == [(0,)]


def test_ac3_the_setting_comes_from_config() -> None:
    raw = (GOLD_DIR / "11_mart_branch_month.sql").read_text(encoding="utf-8")
    assert "$marts_zero_fill" in " ".join(line.split("--")[0] for line in raw.splitlines())


# Files, settings and safety ------


def test_the_file_runs_after_the_profile_mart_and_leaves_room_for_the_peer_mart() -> None:
    names = sorted(p.name for p in GOLD_DIR.glob("*.sql"))
    assert names.index("09_mart_customer_profile.sql") < names.index("11_mart_branch_month.sql")


def test_a_gold_rerun_gives_identical_rows(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    sql = "select * from mart_branch_month order by branch_key, month_start"
    first = query(settings, sql)
    run_gold(settings)
    assert query(settings, sql) == first


def test_changing_zero_fill_between_runs_replaces_the_mart(built: Settings, tmp_path: Path) -> None:
    first = gold(built, tmp_path, marts={"zero_fill": True})
    count = "select count(*) from mart_branch_month"
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
    assert S not in repr(query(settings, "select * from mart_branch_month"))


# AC4 ------


def test_ac4_every_ac_has_a_test_in_this_module() -> None:
    text = Path(__file__).read_text(encoding="utf-8")
    for ac in range(1, 4):
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
        "select count(*) from (select branch_key, month_start from mart_branch_month "
        "group by 1, 2 having count(*) > 1)",
    ) == [(0,)]
    assert query(real, "select sum(net_sales) from mart_branch_month") == query(
        real, "select sum(net_sales) from fact_sales where included"
    )
    # the only line with no branch is the excluded stray row, so there is no unknown-branch row
    assert query(real, "select count(*) from mart_branch_month where branch_key = -1") == [(0,)]
    assert query(real, "select count(distinct branch_key) from mart_branch_month") == [(33,)]
    filled, total = query(
        real, "select count(*) filter (where f_zero_filled), count(*) from mart_branch_month"
    )[0]
    off = variant(tmp_path / "off", real, marts={"zero_fill": False})
    run_gold(off)
    assert query(off, "select count(*) from mart_branch_month") == [(total - filled,)]
