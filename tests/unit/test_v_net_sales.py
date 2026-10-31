"""Story #74: the v_net_sales view (spec 02 section 3, N1 to N5).

Synthetic data only. Silver is built once per module; each test copies the warehouse, changes
settings and runs the (cheap) gold stage on its own copy.
"""

from __future__ import annotations

import logging
import shutil
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
import pytest
import yaml
from silver_helpers import bronze_row, build, query

from revint.config import DEFAULT_SETTINGS_FILE, Settings, load_settings
from revint.gold import GOLD_DIR, GoldError, run_gold
from revint.silver import AMOUNT_COLUMNS

SECRET = "SECRET-"
CANDIDATES = list(AMOUNT_COLUMNS)


def line(
    row: int, net: str, selling: str, qty: str, order: int | None = None, **extra: str
) -> dict[str, str | None]:
    """A sales line; two lines with the same `order` and values are exact duplicates."""
    return bronze_row(
        row,
        OrderReference=f"{SECRET}O{order or row}",
        Customer=f"{SECRET}C",
        Net_Amount_2=net,
        Selling_Amount=selling,
        **{"Quantity(PCS)": qty},
        **extra,
    )


# Silver rows: 8 plain, 9 an exact copy of 8 (excluded), 10 the stray row (excluded),
# 11 a blank Void, 12 free goods, 13 a return.
ROWS = [
    line(8, "10", "12", "2", Void="Unvoid"),
    line(9, "10", "12", "2", order=8, Void="Unvoid"),
    bronze_row(10, Change_to_Ctn="1"),
    line(11, "7", "8", "1"),
    line(12, "0", "0", "3", Void="Unvoid"),
    line(13, "-4", "-5", "-1", Void="Unvoid"),
]


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    root = tmp_path_factory.mktemp("netsales")
    settings = load_settings(
        env={
            "REVINT_PATHS_WAREHOUSE": str(root / "warehouse.duckdb"),
            "REVINT_PATHS_BRONZE": str(root / "bronze"),
        }
    )
    build(settings, ROWS)
    return settings


def variant(root: Path, source: Settings, **sections: dict[str, Any]) -> Settings:
    """The committed settings with some keys changed, pointing at `source`'s warehouse."""
    data = yaml.safe_load(DEFAULT_SETTINGS_FILE.read_text(encoding="utf-8"))
    for name, keys in sections.items():
        data[name] = {**data.get(name, {}), **keys}
    config_file = root / "config" / "settings.yaml"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return load_settings(config_file, env={"REVINT_PATHS_WAREHOUSE": str(source.paths.warehouse)})


def gold(built: Settings, tmp_path: Path, **sections: dict[str, Any]) -> Settings:
    """A private copy of the silver warehouse with the gold stage run under `sections`."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    shutil.copy(built.paths.warehouse, tmp_path / "warehouse.duckdb")
    source = load_settings(env={"REVINT_PATHS_WAREHOUSE": str(tmp_path / "warehouse.duckdb")})
    settings = variant(tmp_path, source, **sections)
    run_gold(settings)
    return settings


def lines(settings: Settings) -> dict[int, tuple[Decimal | None, bool]]:
    rows = query(settings, "select sales_line_id, net_sales, included from v_net_sales")
    return {r[0]: (r[1], r[2]) for r in rows}


# AC1: the view exposes net_sales, net_sales_field_used and included ----------------------------


def test_ac1_v_net_sales_is_a_view(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    kinds = query(
        settings,
        "select table_type from information_schema.tables where table_name = 'v_net_sales'",
    )
    assert kinds == [("VIEW",)]


def test_ac1_it_exposes_net_sales_the_field_used_and_included(
    built: Settings, tmp_path: Path
) -> None:
    settings = gold(built, tmp_path)
    got = query(
        settings,
        "select sales_line_id, net_sales, net_sales_field_used, included "
        "from v_net_sales order by 1",
    )
    assert got == [
        (8, Decimal("10.0000"), "Net_Amount_2", True),
        (11, Decimal("7.0000"), "Net_Amount_2", True),
        (12, Decimal("0.0000"), "Net_Amount_2", True),
        (13, Decimal("-4.0000"), "Net_Amount_2", True),
    ]


def test_ac1_net_sales_is_the_column_named_by_the_setting(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    assert settings.net_sales.field == "Net_Amount_2"
    total = query(settings, "select sum(net_sales) from v_net_sales")[0][0]
    silver = query(settings, "select sum(Net_Amount_2) from silver_sales where not is_excluded")[0][
        0
    ]
    assert total == silver == Decimal("13.0000")


def test_ac1_one_row_per_silver_line_that_gold_loads(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    ids = [r[0] for r in query(settings, "select sales_line_id from v_net_sales")]
    assert len(ids) == len(set(ids)) == 4


def test_ac1_blank_void_free_goods_and_returns_stay_in_the_view(
    built: Settings, tmp_path: Path
) -> None:
    got = lines(gold(built, tmp_path))
    assert {11, 12, 13} <= set(got)
    assert got[13][0] < 0


def test_ac1_gold_needs_silver(tmp_path: Path) -> None:
    settings = load_settings(env={"REVINT_PATHS_WAREHOUSE": str(tmp_path / "none.duckdb")})
    with pytest.raises(GoldError, match="silver"):
        run_gold(settings)


def test_ac1_a_warehouse_without_silver_sales_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "empty.duckdb"
    duckdb.connect(str(path)).close()
    settings = load_settings(env={"REVINT_PATHS_WAREHOUSE": str(path)})
    with pytest.raises(GoldError, match="silver_sales"):
        run_gold(settings)


# AC2: rows gold loads depend on duplicates.exclude_from_net_sales ---------------------------------


def test_ac2_with_exclusion_on_there_is_no_stray_row_and_no_copy(
    built: Settings, tmp_path: Path
) -> None:
    got = lines(gold(built, tmp_path, duplicates={"exclude_from_net_sales": True}))
    assert 9 not in got  # the exact copy
    assert 10 not in got  # the stray row
    assert sorted(got) == [8, 11, 12, 13]


def test_ac2_with_exclusion_off_the_copy_stays_and_the_stray_row_does_not(
    built: Settings, tmp_path: Path
) -> None:
    settings = gold(built, tmp_path, duplicates={"exclude_from_net_sales": False})
    got = lines(settings)
    assert sorted(got) == [8, 9, 11, 12, 13]
    assert 10 not in got
    copy = query(
        settings,
        "select count(*) from silver_sales where _source_row = 9 and is_duplicate",
    )
    assert copy == [(1,)]


def test_ac2_turning_exclusion_off_adds_exactly_the_copy_amount(
    built: Settings, tmp_path: Path
) -> None:
    on = gold(built, tmp_path / "on", duplicates={"exclude_from_net_sales": True})
    off = gold(built, tmp_path / "off", duplicates={"exclude_from_net_sales": False})
    total = "select sum(net_sales) from v_net_sales"
    assert query(off, total)[0][0] - query(on, total)[0][0] == Decimal("10.0000")


def test_ac2_the_stray_row_is_never_loaded(built: Settings, tmp_path: Path) -> None:
    for flag in (True, False):
        settings = gold(built, tmp_path / str(flag), duplicates={"exclude_from_net_sales": flag})
        assert query(settings, "select count(*) from v_net_sales where sales_line_id = 10") == [
            (0,)
        ]


# AC3: exclude_flags set included = false; the rows stay -----------------------------------------


def test_ac3_with_no_flags_every_row_is_included(built: Settings, tmp_path: Path) -> None:
    got = lines(gold(built, tmp_path))
    assert all(included for _, included in got.values())


def test_ac3_a_listed_flag_makes_its_rows_not_included_but_keeps_them(
    built: Settings, tmp_path: Path
) -> None:
    got = lines(gold(built, tmp_path, net_sales={"exclude_flags": ["f_blank_void"]}))
    assert got[11] == (Decimal("7.0000"), False)
    assert all(got[n][1] for n in (8, 12, 13))
    assert sorted(got) == [8, 11, 12, 13]


def test_ac3_several_flags_exclude_a_row_that_has_any_of_them(
    built: Settings, tmp_path: Path
) -> None:
    flags = ["f_blank_void", "f_zero_value_with_qty", "f_negative_value"]
    got = lines(gold(built, tmp_path, net_sales={"exclude_flags": flags}))
    assert {n: included for n, (_, included) in got.items()} == {
        8: True,
        11: False,
        12: False,
        13: False,
    }


def test_ac3_the_duplicate_flag_marks_the_copies_when_they_are_kept(
    built: Settings, tmp_path: Path
) -> None:
    got = lines(
        gold(
            built,
            tmp_path,
            duplicates={"exclude_from_net_sales": False},
            net_sales={"exclude_flags": ["is_duplicate"]},
        )
    )
    assert got[9][1] is False
    assert got[8][1] is True


def test_ac3_total_of_included_rows_follows_the_flags(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path, net_sales={"exclude_flags": ["f_negative_value"]})
    assert query(settings, "select sum(net_sales) from v_net_sales where included") == [
        (Decimal("17.0000"),)
    ]
    assert query(settings, "select sum(net_sales) from v_net_sales") == [(Decimal("13.0000"),)]


# AC4: switching net_sales.field changes the view with no code edit ------------------------------


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("Net_Amount_2", Decimal("13.0000")),
        ("Selling_Amount", Decimal("15.0000")),
    ],
)
def test_ac4_the_view_total_follows_net_sales_field(
    built: Settings, tmp_path: Path, field: str, expected: Decimal
) -> None:
    settings = gold(built, tmp_path, net_sales={"field": field})
    assert query(settings, "select sum(net_sales) from v_net_sales") == [(expected,)]
    assert query(settings, "select distinct net_sales_field_used from v_net_sales") == [(field,)]


def test_ac4_a_rebuild_with_another_field_replaces_the_definition(
    built: Settings, tmp_path: Path
) -> None:
    first = gold(built, tmp_path, net_sales={"field": "Net_Amount_2"})
    second = variant(tmp_path, first, net_sales={"field": "Selling_Amount"})
    run_gold(second)
    assert query(second, "select sum(net_sales) from v_net_sales") == [(Decimal("15.0000"),)]


def test_ac4_the_gold_sql_names_no_candidate_amount_column() -> None:
    text = "\n".join(p.read_text(encoding="utf-8") for p in sorted(GOLD_DIR.glob("*.sql")))
    for column in CANDIDATES:
        assert column not in text, column


def test_ac4_the_sql_files_in_gold_are_numbered_and_the_view_comes_first() -> None:
    names = sorted(p.name for p in GOLD_DIR.glob("*.sql"))
    assert names[0] == "01_v_net_sales.sql"
    assert all(n[:2].isdigit() for n in names)


# AC5: the other candidates and the quantity under stable names -----------------------------------


def test_ac5_the_view_exposes_every_candidate_and_the_quantity(
    built: Settings, tmp_path: Path
) -> None:
    settings = gold(built, tmp_path)
    columns = [
        c
        for (c,) in query(
            settings,
            "select column_name from information_schema.columns "
            "where table_name = 'v_net_sales' order by ordinal_position",
        )
    ]
    assert columns[:5] == [
        "sales_line_id",
        "net_sales",
        "net_sales_field_used",
        "included",
        "quantity",
    ]
    assert columns[5:] == [f"amount_{c}" for c in CANDIDATES]


def test_ac5_the_amounts_and_quantity_are_the_silver_values(
    built: Settings, tmp_path: Path
) -> None:
    settings = gold(built, tmp_path)
    got = query(
        settings,
        "select quantity, amount_Selling_Amount, amount_Net_Amount_2 from v_net_sales "
        "where sales_line_id = 11",
    )
    assert got == [(1, Decimal("8.0000"), Decimal("7.0000"))]


def test_ac5_the_amount_columns_follow_the_candidate_list(built: Settings, tmp_path: Path) -> None:
    settings = gold(
        built,
        tmp_path,
        net_sales={"candidate_columns": ["Net_Amount_2", "Selling_Amount"]},
    )
    columns = [
        c
        for (c,) in query(
            settings,
            "select column_name from information_schema.columns "
            "where table_name = 'v_net_sales' and column_name like 'amount\\_%' escape '\\' "
            "order by ordinal_position",
        )
    ]
    assert sorted(columns) == ["amount_Net_Amount_2", "amount_Selling_Amount"]


def test_ac5_net_sales_equals_the_amount_column_of_the_field(
    built: Settings, tmp_path: Path
) -> None:
    settings = gold(built, tmp_path, net_sales={"field": "Selling_Amount"})
    assert query(
        settings,
        "select count(*) from v_net_sales where net_sales is distinct from amount_Selling_Amount",
    ) == [(0,)]


# Safety ------


def test_the_gold_stage_logs_and_stores_no_cell_values(
    built: Settings, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        settings = gold(built, tmp_path)
    assert SECRET not in caplog.text
    assert SECRET not in repr(query(settings, "select * from v_net_sales"))


def test_a_gold_rerun_gives_identical_rows(built: Settings, tmp_path: Path) -> None:
    settings = gold(built, tmp_path)
    first = query(settings, "select * from v_net_sales order by sales_line_id")
    run_gold(settings)
    assert query(settings, "select * from v_net_sales order by sales_line_id") == first


def test_gold_leaves_silver_untouched(built: Settings, tmp_path: Path) -> None:
    before = query(built, "select count(*), sum(Net_Amount_2) from silver_sales")
    settings = gold(built, tmp_path / "g")
    assert query(settings, "select count(*), sum(Net_Amount_2) from silver_sales") == before


# AC6 ------


def test_ac6_every_ac_has_a_test_in_this_module() -> None:
    text = Path(__file__).read_text(encoding="utf-8")
    for ac in range(1, 6):
        assert f"def test_ac{ac}_" in text


@pytest.mark.realdata
def test_ac1_ac2_ac4_real_file_totals(tmp_path: Path) -> None:
    """Counts and sums only. Runs gold on a temporary warehouse built from the real bronze."""
    real = load_settings(env={"REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb")})
    if not list(real.paths.bronze.glob("*__RAW_SCJ_SALES.parquet")):
        pytest.skip("bronze not built: run `uv run revint build bronze` first")
    from revint.silver import run_silver

    run_silver(real)
    run_gold(real)
    rows, total = query(real, "select count(*), sum(net_sales) from v_net_sales")[0]
    assert rows == 662_128 - 557
    silver = query(real, "select sum(Net_Amount_2) from silver_sales where not is_excluded")
    assert total == silver[0][0]
    off = variant(tmp_path / "off", real, duplicates={"exclude_from_net_sales": False})
    run_gold(off)
    rows_off, total_off = query(off, "select count(*), sum(net_sales) from v_net_sales")[0]
    assert rows_off == 662_128 - 1
    copies = query(
        off,
        "select sum(net_amount_2) from silver_excluded_rows "
        "where exclusion_reason = 'exact_duplicate'",
    )[0][0]
    assert total_off - total == copies
