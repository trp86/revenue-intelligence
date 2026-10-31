"""Story #79: fact_sales (spec 02 section 5).

Synthetic data only; customer, product and branch values carry a SECRET- marker to prove none
reaches logs. Silver is built once per module, each test copies the warehouse and runs gold on
its own copy. The real-file test is marked `realdata` and asserts counts and sums only.
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
from revint.silver import AMOUNT_COLUMNS
from revint.silver_schema import SILVER_FLAG_COLUMNS

S = "SECRET-"


def sale(
    row: int,
    customer: str | None,
    product: str | None,
    branch: str | None,
    day: str | None,
    net: str,
    selling: str,
    qty: str,
    order: int | None = None,
    **extra: str,
) -> dict[str, str | None]:
    return bronze_row(
        row,
        OrderReference=f"O{order or row}",
        CustomerCode=customer,
        Customer=f"{S}name" if customer else None,
        SCJ_CODE_1=product,
        Product_Decription=f"{S}product" if product else None,
        Branch_Name=branch,
        Date=day,
        Net_Amount_2=net,
        Selling_Amount=selling,
        **{"Quantity(PCS)": qty},
        **extra,
    )


# Silver rows 8 to 14 (7 lines):
#   8   a plain line, every key present
#   9   an exact copy of 8 (silver excludes it)
#   10  the stray row (silver excludes it)
#   11  a blank customer code
#   12  free goods with no product, no branch and no date
#   13  a return dated after the as-of date, with a blank Void
#   14  an unparseable date
ROWS = [
    sale(8, f"{S}C1", f"{S}P1", "Magway", "2019-01-05", "10", "12", "2", Void="Unvoid"),
    sale(9, f"{S}C1", f"{S}P1", "Magway", "2019-01-05", "10", "12", "2", order=8, Void="Unvoid"),
    bronze_row(10, Change_to_Ctn="1"),
    sale(11, None, f"{S}P2", "PYAY", "2019-02-01", "7", "8", "1", Void="Unvoid"),
    sale(12, f"{S}C2", None, None, None, "0", "0", "3", Void="Unvoid"),
    sale(13, f"{S}C3", f"{S}P1", "Magway", "2020-03-01", "-4", "-5", "-1"),
    sale(14, f"{S}C4", f"{S}P2", "PYAY", "not a date", "5", "6", "1", Void="Unvoid"),
]
SILVER_ROWS = 7
EXCLUDED = 2  # the copy and the stray row
STRAY = 1
KEPT = [8, 11, 12, 13, 14]
AMOUNTS = [f"amount_{c}" for c in AMOUNT_COLUMNS]


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    root = tmp_path_factory.mktemp("factsales")
    settings = load_settings(
        env={
            "REVINT_PATHS_WAREHOUSE": str(root / "warehouse.duckdb"),
            "REVINT_PATHS_BRONZE": str(root / "bronze"),
        }
    )
    build(settings, ROWS)
    return settings


def fact(settings: Settings) -> dict[int, dict]:
    cursor_rows = query(settings, "select * from fact_sales order by sales_line_id")
    names = [
        c
        for (c,) in query(
            settings,
            "select column_name from information_schema.columns "
            "where table_name = 'fact_sales' order by ordinal_position",
        )
    ]
    return {r[0]: dict(zip(names, r, strict=True)) for r in cursor_rows}


# AC1: config true, fact rows = silver rows minus count(silver_excluded_rows) ------


def test_ac1_fact_rows_equal_silver_rows_minus_the_excluded_rows(
    built: Settings, tmp_path: Path
) -> None:
    settings = gold(built, tmp_path, duplicates={"exclude_from_net_sales": True})
    silver = query(settings, "select count(*) from silver_sales")[0][0]
    excluded = query(settings, "select count(*) from silver_excluded_rows")[0][0]
    assert (silver, excluded) == (SILVER_ROWS, EXCLUDED)
    assert query(settings, "select count(*) from fact_sales") == [(silver - excluded,)]


def test_ac1_no_copy_and_no_stray_row_is_in_the_fact(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path, duplicates={"exclude_from_net_sales": True})
    assert sorted(fact(settings)) == KEPT
    assert query(
        settings,
        "select count(*) from fact_sales as f inner join silver_sales as s "
        "on s._source_row = f.sales_line_id where s.is_excluded",
    ) == [(0,)]


def test_ac1_the_fact_rows_are_the_rows_of_v_net_sales(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    assert query(settings, "select sales_line_id from fact_sales order by 1") == query(
        settings, "select sales_line_id from v_net_sales order by 1"
    )


# AC2: config false, fact rows = silver rows minus the stray rows ------


def test_ac2_fact_rows_equal_silver_rows_minus_the_stray_rows(
    built: Settings, tmp_path: Path
) -> None:
    settings = gold(built, tmp_path, duplicates={"exclude_from_net_sales": False})
    assert query(settings, "select count(*) from fact_sales") == [(SILVER_ROWS - STRAY,)]


def test_ac2_the_copy_stays_with_is_duplicate_true_and_the_stray_row_is_absent(
    built: Settings, tmp_path: Path
) -> None:
    settings = gold(built, tmp_path, duplicates={"exclude_from_net_sales": False})
    got = fact(settings)
    assert sorted(got) == [8, 9, 11, 12, 13, 14]
    assert got[9]["is_duplicate"] is True
    assert got[8]["is_duplicate"] is False
    assert 10 not in got


def test_ac2_a_kept_copy_keeps_the_keys_of_its_original(built: Settings, tmp_path: Path) -> None:
    got = fact(gold(built, tmp_path, duplicates={"exclude_from_net_sales": False}))
    keys = ("date_key", "customer_key", "product_key", "branch_key", "net_sales", "quantity")
    assert [got[9][k] for k in keys] == [got[8][k] for k in keys]


# AC3: grain, keys, quantity, amounts, net_sales and all silver flags ------


def test_ac3_the_table_has_the_documented_columns_in_order(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    columns = [
        c
        for (c,) in query(
            settings,
            "select column_name from information_schema.columns "
            "where table_name = 'fact_sales' order by ordinal_position",
        )
    ]
    assert columns[:8] == [
        "sales_line_id",
        "date_key",
        "customer_key",
        "product_key",
        "branch_key",
        "quantity",
        "net_sales",
        "included",
    ]
    assert columns[8:14] == AMOUNTS
    assert columns[14] == "void_flag"
    assert set(columns[15:-1]) == set(SILVER_FLAG_COLUMNS)
    assert columns[-1] == "f_after_asof"
    assert len(columns) == len(set(columns))


def test_ac3_one_row_per_silver_line_and_sales_line_id_is_the_source_row(
    built: Settings, tmp_path: Path
) -> None:
    settings = gold(built, tmp_path)
    assert query(settings, "select count(*), count(distinct sales_line_id) from fact_sales") == [
        (len(KEPT), len(KEPT))
    ]
    assert sorted(fact(settings)) == KEPT


def test_ac3_keys_point_at_the_dimension_rows_of_the_line(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    got = query(
        settings,
        "select f.sales_line_id, d.date, c.customer_code, p.product_code, b.branch_name "
        "from fact_sales as f "
        "inner join dim_date as d on d.date_key = f.date_key "
        "inner join dim_customer as c on c.customer_key = f.customer_key "
        "inner join dim_product as p on p.product_key = f.product_key "
        "inner join dim_branch as b on b.branch_key = f.branch_key "
        "where f.sales_line_id = 8",
    )
    assert got == [(8, date(2019, 1, 5), f"{S}C1", f"{S}P1", "Magway")]


def test_ac3_the_branch_key_follows_the_normalised_label(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    got = query(
        settings,
        "select b.branch_name from fact_sales as f "
        "inner join dim_branch as b on b.branch_key = f.branch_key where f.sales_line_id = 11",
    )
    assert got == [("Pyay",)]  # the label map turns PYAY into Pyay


def test_ac3_quantity_and_net_sales_and_amounts_come_from_v_net_sales(
    built: Settings, tmp_path: Path
) -> None:
    settings = gold(built, tmp_path)
    columns = "sales_line_id, quantity, net_sales, included, " + ", ".join(AMOUNTS)
    assert query(settings, f"select {columns} from fact_sales order by 1") == query(
        settings, f"select {columns} from v_net_sales order by 1"
    )
    row = fact(settings)[11]
    assert (row["quantity"], row["net_sales"]) == (1, Decimal("7.0000"))
    assert row["amount_Selling_Amount"] == Decimal("8.0000")


@pytest.mark.parametrize("flag", ["void_flag", *SILVER_FLAG_COLUMNS])
def test_ac3_every_silver_flag_is_carried_over_unchanged(
    built: Settings, tmp_path: Path, flag: str
) -> None:
    settings = gold(built, tmp_path / flag, duplicates={"exclude_from_net_sales": False})
    differing = query(
        settings,
        f"select count(*) from fact_sales as f inner join silver_sales as s "
        f'on s._source_row = f.sales_line_id where f."{flag}" is distinct from s."{flag}"',
    )
    assert differing == [(0,)]


def test_ac3_known_flags_on_known_lines(built: Settings, tmp_path: Path) -> None:
    got = fact(gold(built, tmp_path))
    assert got[12]["f_zero_value_with_qty"] is True  # free goods
    assert got[13]["f_negative_value"] is True and got[13]["f_negative_qty"] is True  # a return
    assert got[13]["f_blank_void"] is True and got[8]["f_blank_void"] is False
    assert got[8]["void_flag"] is None  # 'Unvoid' is not in void.value_map yet
    assert got[8]["f_unmapped_void"] is True
    assert got[13]["void_flag"] == 0  # a blank Void is not void (provisional D3)
    assert got[14]["f_bad_Date"] is True


def test_ac3_f_after_asof_comes_from_dim_date(built: Settings, tmp_path: Path) -> None:
    got = fact(gold(built, tmp_path))
    assert {k: v["f_after_asof"] for k, v in got.items()} == {
        8: False,
        11: False,
        12: False,
        13: True,  # 2020-03-01 is after the as-of date 2020-02-29
        14: False,
    }


def test_ac3_a_line_after_the_as_of_date_is_kept(built: Settings, tmp_path: Path) -> None:
    assert 13 in fact(gold(built, tmp_path))


def test_ac3_the_flag_columns_are_true_or_false_never_null(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    for flag in (*SILVER_FLAG_COLUMNS, "included", "f_after_asof"):
        assert query(settings, f'select count(*) from fact_sales where "{flag}" is null') == [(0,)]


# AC4: unknown members and no orphan foreign keys ------


def test_ac4_blank_or_unknown_values_use_key_minus_one_and_no_row_is_dropped(
    built: Settings, tmp_path: Path
) -> None:
    got = fact(gold(built, tmp_path))
    assert got[11]["customer_key"] == -1  # blank customer code
    assert (got[12]["product_key"], got[12]["branch_key"], got[12]["date_key"]) == (-1, -1, -1)
    assert got[14]["date_key"] == -1  # a date silver could not type
    assert got[8]["date_key"] == 20190105
    assert len(got) == len(KEPT)


@pytest.mark.parametrize(
    ("column", "dimension", "key"),
    [
        ("date_key", "dim_date", "date_key"),
        ("customer_key", "dim_customer", "customer_key"),
        ("product_key", "dim_product", "product_key"),
        ("branch_key", "dim_branch", "branch_key"),
    ],
)
@pytest.mark.parametrize("exclude", [True, False])
def test_ac4_there_are_no_orphan_foreign_keys(
    built: Settings, tmp_path: Path, column: str, dimension: str, key: str, exclude: bool
) -> None:
    settings = gold(
        built, tmp_path / f"{column}{exclude}", duplicates={"exclude_from_net_sales": exclude}
    )
    orphans = query(
        settings,
        f"select count(*) from fact_sales as f left join {dimension} as d on d.{key} = f.{column} "
        f"where d.{key} is null",
    )
    assert orphans == [(0,)]


def test_ac4_no_key_is_null(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    for column in ("date_key", "customer_key", "product_key", "branch_key"):
        assert query(settings, f"select count(*) from fact_sales where {column} is null") == [(0,)]


def test_ac4_a_line_is_never_multiplied_by_a_join(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    assert query(settings, "select count(*), count(distinct sales_line_id) from fact_sales") == [
        (len(KEPT), len(KEPT))
    ]


def test_ac4_near_duplicate_codes_keep_their_own_keys(tmp_path: Path) -> None:
    settings = load_settings(
        env={
            "REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb"),
            "REVINT_PATHS_BRONZE": str(tmp_path / "b"),
        }
    )
    build(
        settings,
        [
            sale(8, "C1", "P1", "Magway", "2019-01-05", "1", "1", "1"),
            sale(9, "c1", "P1", "Magway", "2019-01-05", "2", "2", "1"),
        ],
    )
    run_gold(settings)
    got = fact(settings)
    assert got[8]["customer_key"] != got[9]["customer_key"]
    assert -1 not in (got[8]["customer_key"], got[9]["customer_key"])


# AC5: switching true to false raises every candidate total by the exact_duplicate amount ------


@pytest.mark.parametrize("amount", AMOUNTS)
def test_ac5_each_candidate_total_rises_by_exactly_the_duplicate_amount(
    built: Settings, tmp_path: Path, amount: str
) -> None:
    on = gold(built, tmp_path / "on", duplicates={"exclude_from_net_sales": True})
    off = gold(built, tmp_path / "off", duplicates={"exclude_from_net_sales": False})
    column = amount.removeprefix("amount_")
    total = f"select coalesce(sum({amount}), 0) from fact_sales"
    copies = query(
        off,
        f'select coalesce(sum("{column}"), 0) from silver_sales '
        "where exclusion_reason = 'exact_duplicate'",
    )[0][0]
    assert query(off, total)[0][0] - query(on, total)[0][0] == copies


def test_ac5_the_net_sales_total_rises_by_the_duplicate_amount_too(
    built: Settings, tmp_path: Path
) -> None:
    on = gold(built, tmp_path / "on", duplicates={"exclude_from_net_sales": True})
    off = gold(built, tmp_path / "off", duplicates={"exclude_from_net_sales": False})
    total = "select sum(net_sales) from fact_sales"
    assert query(off, total)[0][0] - query(on, total)[0][0] == Decimal("10.0000")


def test_ac5_the_audit_table_amount_equals_the_rise(built: Settings, tmp_path: Path) -> None:
    on = gold(built, tmp_path / "on", duplicates={"exclude_from_net_sales": True})
    off = gold(built, tmp_path / "off", duplicates={"exclude_from_net_sales": False})
    audit = query(
        off,
        "select coalesce(sum(net_amount_2), 0) from silver_excluded_rows "
        "where exclusion_reason = 'exact_duplicate'",
    )[0][0]
    rise = (
        query(off, "select sum(net_sales) from fact_sales")[0][0]
        - query(on, "select sum(net_sales) from fact_sales")[0][0]
    )
    assert audit == rise


# AC6: a line with included = false stays in the fact ------


def test_ac6_a_line_with_an_exclude_flag_stays_with_included_false(
    built: Settings, tmp_path: Path
) -> None:
    settings = gold(built, tmp_path, net_sales={"exclude_flags": ["f_blank_void"]})
    got = fact(settings)
    assert got[13]["included"] is False
    assert all(got[n]["included"] for n in (8, 11, 12, 14))
    assert sorted(got) == KEPT


def test_ac6_the_row_count_does_not_change_with_exclude_flags(
    built: Settings, tmp_path: Path
) -> None:
    plain = gold(built, tmp_path / "a")
    flagged = gold(
        built,
        tmp_path / "b",
        net_sales={"exclude_flags": ["f_blank_void", "f_zero_value_with_qty", "f_negative_value"]},
    )
    count = "select count(*) from fact_sales"
    assert query(plain, count) == query(flagged, count)
    # row 12 is free goods; row 13 is a blank Void and a return, so it is counted once
    assert query(flagged, "select count(*) from fact_sales where not included") == [(2,)]


def test_ac6_not_included_lines_still_carry_their_amounts(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path, net_sales={"exclude_flags": ["f_negative_value"]})
    assert fact(settings)[13]["net_sales"] == Decimal("-4.0000")


# The field can change without a code edit ------


def test_switching_net_sales_field_changes_the_fact_net_sales(
    built: Settings, tmp_path: Path
) -> None:
    default = gold(built, tmp_path / "a")
    other = gold(built, tmp_path / "b", net_sales={"field": "Selling_Amount"})
    total = "select sum(net_sales) from fact_sales"
    assert query(default, total) == [(Decimal("18.0000"),)]
    assert query(other, total) == [(Decimal("21.0000"),)]


# Settings and files ------


def test_the_sql_hard_codes_no_source_column_name() -> None:
    raw = (GOLD_DIR / "06_fact_sales.sql").read_text(encoding="utf-8")
    text = " ".join(line.split("--")[0] for line in raw.splitlines())
    for column in AMOUNT_COLUMNS:
        assert column not in text
    for name in ("CustomerCode", "SCJ_CODE_1", "Branch_Name", '"Date"'):
        assert name not in text
    for parameter in (
        "$customers_code_column",
        "$product_code_column",
        "$labels_branch_columns",
        "$calendar_date_column",
        "$silver_flag_columns",
    ):
        assert parameter in text


def test_the_file_runs_after_the_dimensions_and_the_view() -> None:
    names = sorted(p.name for p in GOLD_DIR.glob("*.sql"))
    assert names.index("05_dim_product.sql") < names.index("06_fact_sales.sql")
    assert names.index("01_v_net_sales.sql") < names.index("06_fact_sales.sql")


def test_the_flag_columns_come_from_the_silver_schema_list() -> None:
    assert len(SILVER_FLAG_COLUMNS) == 9 + 28


def test_a_gold_rerun_gives_identical_rows(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    first = query(settings, "select * from fact_sales order by sales_line_id")
    run_gold(settings)
    assert query(settings, "select * from fact_sales order by sales_line_id") == first


def test_changing_the_setting_between_runs_replaces_the_fact(
    built: Settings, tmp_path: Path
) -> None:
    first = gold(built, tmp_path, duplicates={"exclude_from_net_sales": True})
    assert query(first, "select count(*) from fact_sales") == [(len(KEPT),)]
    second = variant(tmp_path / "again", first, duplicates={"exclude_from_net_sales": False})
    run_gold(second)
    assert query(second, "select count(*) from fact_sales") == [(len(KEPT) + 1,)]


def test_gold_leaves_silver_untouched(built: Settings, tmp_path: Path) -> None:
    before = query(built, "select count(*), sum(Net_Amount_2) from silver_sales")
    settings = gold(built, tmp_path)
    assert query(settings, "select count(*), sum(Net_Amount_2) from silver_sales") == before


# Safety ------


def test_the_gold_stage_logs_no_customer_product_or_branch_values(
    built: Settings, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        settings = gold(built, tmp_path)
    assert S not in caplog.text
    # the fact holds keys, numbers and flags, never a code or a name
    assert S not in repr(query(settings, "select * from fact_sales"))


# AC7 ------


def test_ac7_every_ac_has_a_test_in_this_module() -> None:
    text = Path(__file__).read_text(encoding="utf-8")
    for ac in range(1, 7):
        assert f"def test_ac{ac}_" in text


@pytest.mark.realdata
def test_ac1_ac2_ac4_ac5_real_file_fact(tmp_path: Path) -> None:
    """Counts and sums only. Gold runs on a temporary warehouse built from the real bronze files."""
    real = load_settings(env={"REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb")})
    if not list(real.paths.bronze.glob("*__RAW_SCJ_SALES.parquet")):
        pytest.skip("bronze not built: run `uv run revint build bronze` first")
    from revint.silver import run_silver

    run_silver(real)
    run_gold(real)
    totals_on = {
        amount: query(real, f"select sum({amount}) from fact_sales")[0][0] for amount in AMOUNTS
    }
    assert query(real, "select count(*) from fact_sales") == [(662_128 - 557,)]
    assert query(real, "select count(*) from fact_sales where sales_line_id = 662135") == [(0,)]
    for column, dimension in (
        ("date_key", "dim_date"),
        ("customer_key", "dim_customer"),
        ("product_key", "dim_product"),
        ("branch_key", "dim_branch"),
    ):
        key = column
        assert query(
            real,
            f"select count(*) from fact_sales as f left join {dimension} as d "
            f"on d.{key} = f.{column} where d.{key} is null",
        ) == [(0,)]
    assert query(real, "select sum(net_sales) from fact_sales") == query(
        real, "select sum(net_sales) from v_net_sales"
    )
    # `off` shares the warehouse file, so its gold run replaces the tables read above.
    off = variant(tmp_path / "off", real, duplicates={"exclude_from_net_sales": False})
    run_gold(off)
    assert query(off, "select count(*) from fact_sales") == [(662_128 - 1,)]
    for amount in AMOUNTS:
        column = amount.removeprefix("amount_")
        rise = query(off, f"select sum({amount}) from fact_sales")[0][0] - totals_on[amount]
        copies = query(
            off,
            f'select coalesce(sum("{column}"), 0) from silver_sales '
            "where exclusion_reason = 'exact_duplicate'",
        )[0][0]
        assert rise == copies
