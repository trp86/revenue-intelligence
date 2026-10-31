"""Story #36: value flags, free goods and returns (spec 01 S7, S8).

Synthetic bronze data only. The real-file test is marked `realdata` and asserts counts, never
individual values.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from silver_helpers import (
    COLUMN_TYPES_SQL,
    EXPECTED,
    bronze_row,
    build,
    query,
    write_bronze,
)

from revint.config import ConfigError, Settings, load_settings
from revint.silver import SILVER_DIR, SilverError, run_silver

NET = "Net_Amount_2"
QTY = "Quantity(PCS)"


@pytest.fixture
def silver_settings(load_with) -> Settings:
    return load_with({"ingest": {"expected_columns": EXPECTED, "sheets": ["RAW SCJ SALES"]}})


def with_net_sales(load_with, field: str, name: str = "alt") -> Settings:
    return load_with(
        {
            "ingest": {"expected_columns": EXPECTED, "sheets": ["RAW SCJ SALES"]},
            "net_sales": {"field": field},
        },
        name=name,
    )


def line(source_row: int, net: str | None, qty: str | None, **cells: str | None):
    """An order line made different from every other by its order reference, so the
    duplicate rule never fires and the flags are what is under test."""
    base = {"OrderReference": f"O{source_row}", NET: net, QTY: qty}
    base.update(cells)
    return bronze_row(source_row, **base)


def flags(settings: Settings, source_row: int) -> tuple:
    return query(
        settings,
        "select f_zero_value_with_qty, f_negative_qty, f_negative_value, is_excluded "
        "from silver_sales where _source_row = ?",
        source_row,
    )[0]


# AC1: zero net sales with a quantity above zero is a possible free good ----------


def test_ac1_zero_value_with_quantity_is_flagged_and_the_row_is_kept(
    silver_settings: Settings,
) -> None:
    build(silver_settings, [line(8, "0", "3")])
    assert flags(silver_settings, 8) == (True, False, False, False)
    assert query(silver_settings, "select count(*) from silver_sales") == [(1,)]


@pytest.mark.parametrize(
    ("net", "qty", "expected"),
    [
        ("0", "3", True),
        ("0.0", "1", True),
        ("0.00004", "1", True),  # rounds to 0.0000 in decimal(18,4): zero in silver
        (" 0 ", "2", True),
        ("5", "3", False),  # a value: not a free good
        ("0", "0", False),  # no quantity
        ("0", "-1", False),  # a return, not a free good
        ("0", None, False),  # no quantity at all
        (None, "3", False),  # no value at all: unknown, not zero
        ("-", "3", False),  # a bad value: unknown, not zero
        ("0", "x", False),  # a bad quantity: unknown
        ("-2", "3", False),  # negative value
    ],
)
def test_ac1_the_zero_value_rule_on_each_combination(
    silver_settings: Settings, net: str | None, qty: str | None, expected: bool
) -> None:
    build(silver_settings, [line(8, net, qty)])
    assert flags(silver_settings, 8)[0] is expected


def test_ac1_a_free_good_is_never_excluded(silver_settings: Settings) -> None:
    build(silver_settings, [line(8, "0", "3"), line(9, "0", "5"), line(10, "4", "1")])
    assert query(
        silver_settings, "select count(*) filter (where is_excluded) from silver_sales"
    ) == [(0,)]
    assert query(silver_settings, "select count(*) from silver_excluded_rows") == [(0,)]
    assert query(silver_settings, "select count(*) from silver_sales") == [(3,)]


def test_ac1_the_flag_never_changes_a_value_or_the_row_count(silver_settings: Settings) -> None:
    build(silver_settings, [line(8, "0", "3", Customer="C")])
    row = query(silver_settings, f'select "{NET}", "{QTY}", "Customer" from silver_sales')[0]
    from decimal import Decimal

    assert row == (Decimal("0.0000"), 3, "C")


# AC2: negative quantity or value ----------


@pytest.mark.parametrize(
    ("net", "qty", "negative_qty", "negative_value"),
    [
        ("10", "-2", True, False),
        ("-10", "2", False, True),
        ("-10", "-2", True, True),
        ("10", "2", False, False),
        ("0", "0", False, False),  # zero is not negative
        ("-0", "-0", False, False),
        ("-0.00004", "1", False, False),  # rounds to -0.0000 = 0 in silver
        ("-0.00006", "1", False, True),  # rounds to -0.0001
        (None, None, False, False),
        ("-", "x", False, False),  # unparseable: unknown, not negative
    ],
)
def test_ac2_the_negative_flags_on_each_combination(
    silver_settings: Settings,
    net: str | None,
    qty: str | None,
    negative_qty: bool,
    negative_value: bool,
) -> None:
    build(silver_settings, [line(8, net, qty)])
    _, got_qty, got_value, excluded = flags(silver_settings, 8)
    assert (got_qty, got_value, excluded) == (negative_qty, negative_value, False)


def test_ac2_returns_are_data_not_errors(silver_settings: Settings) -> None:
    build(silver_settings, [line(8, "-10", "-2"), line(9, "5", "1")])  # would raise on an error
    assert query(silver_settings, "select count(*) from silver_sales") == [(2,)]
    assert query(
        silver_settings, "select count(*) filter (where is_excluded) from silver_sales"
    ) == [(0,)]
    assert query(silver_settings, "select count(*) from silver_excluded_rows") == [(0,)]


def test_ac2_a_return_is_not_a_free_good(silver_settings: Settings) -> None:
    build(silver_settings, [line(8, "0", "-3")])
    assert flags(silver_settings, 8)[:3] == (False, True, False)


def test_ac2_the_flags_are_not_null_for_any_row(silver_settings: Settings) -> None:
    build(
        silver_settings,
        [line(8, None, None), line(9, "-", "x"), line(10, "0", "3"), line(11, "-1", "-1")],
    )
    nulls = query(
        silver_settings,
        "select count(*) filter (where f_zero_value_with_qty is null), "
        "count(*) filter (where f_negative_qty is null), "
        "count(*) filter (where f_negative_value is null) from silver_sales",
    )
    assert nulls == [(0, 0, 0)]


def test_ac2_the_flag_columns_are_booleans(silver_settings: Settings) -> None:
    build(silver_settings, [line(8, "0", "3")])
    types = dict(query(silver_settings, COLUMN_TYPES_SQL))
    for name in ("f_zero_value_with_qty", "f_negative_qty", "f_negative_value"):
        assert types[name] == "BOOLEAN", name


# AC3: the flags follow net_sales.field and quantity_field with no code edit ----------


def test_ac3_the_zero_value_flag_follows_the_configured_net_sales_field(load_with) -> None:
    rows = [
        line(8, "0", "3", Net_AMOUNT_3="7"),  # zero in column 46, a value in column 48
        line(9, "9", "3", Net_AMOUNT_3="0"),  # a value in column 46, zero in column 48
    ]
    default = with_net_sales(load_with, "Net_Amount_2", name="a")
    other = with_net_sales(load_with, "Net_AMOUNT_3", name="b")
    build(default, rows)
    build(other, rows)
    assert (flags(default, 8)[0], flags(default, 9)[0]) == (True, False)
    assert (flags(other, 8)[0], flags(other, 9)[0]) == (False, True)


def test_ac3_the_negative_value_flag_follows_the_configured_net_sales_field(load_with) -> None:
    rows = [line(8, "-5", "1", Net_AMOUNT_3="5"), line(9, "5", "1", Net_AMOUNT_3="-5")]
    default = with_net_sales(load_with, "Net_Amount_2", name="a")
    other = with_net_sales(load_with, "Net_AMOUNT_3", name="b")
    build(default, rows)
    build(other, rows)
    assert (flags(default, 8)[2], flags(default, 9)[2]) == (True, False)
    assert (flags(other, 8)[2], flags(other, 9)[2]) == (False, True)


def test_ac3_the_quantity_column_comes_from_config(load_with) -> None:
    settings = load_with(
        {
            "ingest": {"expected_columns": EXPECTED, "sheets": ["RAW SCJ SALES"]},
            "net_sales": {"quantity_field": "UOM"},
        }
    )
    rows = [line(8, "0", "0", UOM="6"), line(9, "0", "6", UOM="0")]
    build(settings, rows)
    assert (flags(settings, 8)[0], flags(settings, 9)[0]) == (True, False)


def test_ac3_the_quantity_negative_flag_follows_the_configured_quantity(load_with) -> None:
    settings = load_with(
        {
            "ingest": {"expected_columns": EXPECTED, "sheets": ["RAW SCJ SALES"]},
            "net_sales": {"quantity_field": "UOM"},
        }
    )
    build(settings, [line(8, "1", "5", UOM="-6")])
    assert flags(settings, 8)[1] is True


def test_ac3_the_net_sales_field_must_be_one_of_the_typed_amounts(load_with) -> None:
    # A text column cannot be tested for zero or below, so the build refuses it.
    settings = load_with(
        {
            "ingest": {"expected_columns": EXPECTED, "sheets": ["RAW SCJ SALES"]},
            "net_sales": {"field": "Net_Amount_2", "candidate_columns": ["Net_Amount_2", "Region"]},
        }
    )
    write_bronze(settings, [line(8, "0", "3")])
    with pytest.raises(SilverError, match=r"net_sales\.candidate_columns.*Region"):
        run_silver(settings)


def test_ac3_a_quantity_field_that_is_text_is_refused(load_with) -> None:
    settings = load_with(
        {
            "ingest": {"expected_columns": EXPECTED, "sheets": ["RAW SCJ SALES"]},
            "net_sales": {"quantity_field": "Region"},
        }
    )
    write_bronze(settings, [line(8, "0", "3")])
    with pytest.raises(SilverError, match=r"net_sales\.quantity_field.*Region"):
        run_silver(settings)


def test_ac3_a_bad_config_value_still_fails_before_any_build(load_with) -> None:
    with pytest.raises(ConfigError, match=r"net_sales\.field"):
        with_net_sales(load_with, "Not_A_Column")


def test_ac3_no_silver_sql_file_hard_codes_a_net_sales_column() -> None:
    for name in ("05_value_flags.sql",):
        text = (SILVER_DIR / name).read_text(encoding="utf-8")
        assert "net_amount_2" not in text.lower(), name
        assert "quantity(pcs)" not in text.lower(), name
        assert "$net_sales_field" in text and "$net_sales_quantity_field" in text


# Interaction with the rest of the stage ----------


def test_the_value_flags_run_between_the_duplicates_and_the_audit_table() -> None:
    names = sorted(p.name for p in SILVER_DIR.glob("*.sql"))
    assert names == [
        "01_helpers.sql",
        "02_silver_sales.sql",
        "03_exclusions.sql",
        "04_duplicates.sql",
        "05_value_flags.sql",
        "06_void_flags.sql",
        "07_label_normalisation.sql",
        "08_excluded_rows.sql",
        "09_customer_codes.sql",
        "10_quality_results.sql",
        "99_checks.sql",
    ]


def test_a_free_good_that_is_also_a_duplicate_keeps_both_marks(silver_settings: Settings) -> None:
    same = {"OrderReference": "O1", NET: "0", QTY: "3"}
    build(silver_settings, [bronze_row(8, **same), bronze_row(9, **same)])
    assert query(
        silver_settings,
        "select _source_row, f_zero_value_with_qty, is_duplicate, is_excluded, exclusion_reason "
        "from silver_sales order by 1",
    ) == [(8, True, False, False, None), (9, True, True, True, "exact_duplicate")]


def test_the_stray_row_is_not_a_free_good(silver_settings: Settings) -> None:
    build(silver_settings, [line(8, "5", "1"), bronze_row(9, Change_to_Ctn="1")])
    assert flags(silver_settings, 9) == (False, False, False, True)


def test_the_build_is_repeatable_with_identical_content(silver_settings: Settings) -> None:
    rows = [line(8, "0", "3"), line(9, "-2", "-1"), line(10, "4", "1")]
    build(silver_settings, rows)
    sql = (
        "select _source_row, f_zero_value_with_qty, f_negative_qty, f_negative_value "
        "from silver_sales order by 1"
    )
    first = query(silver_settings, sql)
    run_silver(silver_settings)
    assert query(silver_settings, sql) == first


def test_the_logs_carry_counts_and_no_values(
    silver_settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    write_bronze(silver_settings, [line(8, "0", "3", Customer="SECRET-CUSTOMER")])
    with caplog.at_level(logging.DEBUG, logger="revint"):
        run_silver(silver_settings)
    assert "SECRET-CUSTOMER" not in caplog.text


# Real file: runs only when data/ exists ----------


@pytest.mark.realdata
def test_ac1_real_file_flag_counts_match_the_profiling(tmp_path: Path) -> None:
    """Counts only. The free-goods count for `Net_Amount_2` was reported by the profiler (#31)."""
    import duckdb

    settings = load_settings(env={"REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb")})
    if not list(settings.paths.bronze.glob("*__RAW_SCJ_SALES.parquet")):
        pytest.skip("bronze not built: run `uv run revint build bronze` first")
    run_silver(settings)
    con = duckdb.connect(str(settings.paths.warehouse), read_only=True)
    try:
        free, neg_qty, neg_value, total, excluded = con.execute(
            "select count(*) filter (where f_zero_value_with_qty), "
            "count(*) filter (where f_negative_qty), count(*) filter (where f_negative_value), "
            "count(*), count(*) filter (where is_excluded) from silver_sales"
        ).fetchone()
        assert total == 662_128
        assert free == 120_727, "profiling #31: zero Net_Amount_2 with Quantity(PCS) above zero"
        assert excluded == 557, (
            "free goods and returns add no exclusions (556 duplicates + 1 stray)"
        )
        assert neg_qty >= 0 and neg_value >= 0
        nulls = con.execute(
            "select count(*) filter (where f_zero_value_with_qty is null or f_negative_qty is null "
            "or f_negative_value is null) from silver_sales"
        ).fetchone()[0]
        assert nulls == 0
    finally:
        con.close()
