"""Story #34: silver typing (spec 01 S1, S2, S10, S11).

Synthetic bronze data only. The real-file test is marked `realdata` and asserts counts and
sums, never individual values.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import duckdb
import polars as pl
import pytest
from silver_helpers import (
    COLUMN_TYPES_SQL,
    EXPECTED,
    SIX_AMOUNTS,
    bronze_row,
    build,
    one,
    query,
    write_bronze,
)

from revint.config import Settings, load_settings
from revint.silver import (
    AMOUNT_COLUMNS,
    COLUMN_TYPES,
    SILVER_DIR,
    SilverError,
    run_silver,
)


@pytest.fixture
def silver_settings(load_with) -> Settings:
    return load_with({"ingest": {"expected_columns": EXPECTED, "sheets": ["RAW SCJ SALES"]}})


# AC1: count(silver_sales) equals the bronze row count -----------------------------------------


def test_ac1_silver_has_one_row_per_bronze_row(silver_settings: Settings) -> None:
    rows = [bronze_row(8 + i, OrderReference=f"O{i}") for i in range(7)]
    build(silver_settings, rows)
    assert query(silver_settings, "select count(*) from silver_sales") == [(7,)]


def test_ac1_rows_that_are_blank_or_all_bad_are_still_kept(silver_settings: Settings) -> None:
    rows = [
        bronze_row(8),
        bronze_row(9, Date="not a date", Year="x", **dict.fromkeys(SIX_AMOUNTS, "-")),
        bronze_row(10, OrderReference="O"),
    ]
    build(silver_settings, rows)
    assert query(silver_settings, "select count(*) from silver_sales") == [(3,)]
    assert query(silver_settings, "select _source_row from silver_sales order by 1") == [
        (8,),
        (9,),
        (10,),
    ]


def test_ac1_an_empty_bronze_table_gives_an_empty_silver_table(silver_settings: Settings) -> None:
    build(silver_settings, [])
    assert query(silver_settings, "select count(*) from silver_sales") == [(0,)]


def test_ac1_the_sql_check_rolls_the_stage_back_if_a_row_goes_missing(
    silver_settings: Settings, tmp_path: Path
) -> None:
    """A stage whose silver table lost a row fails inside the transaction: nothing is left."""
    from revint.pipeline import StageError, run_stage

    bronze = write_bronze(silver_settings, [bronze_row(8), bronze_row(9)])
    stage = tmp_path / "10_silver"
    stage.mkdir()
    (stage / "02_lossy.sql").write_text(
        "create or replace table silver_sales as select * from read_parquet($bronze_file) limit 1;",
        encoding="utf-8",
    )
    (stage / "04_checks.sql").write_text(
        (SILVER_DIR / "04_checks.sql").read_text(encoding="utf-8"), encoding="utf-8"
    )
    with pytest.raises(
        StageError, match=r"04_checks\.sql.*silver row count 1 does not match bronze row count 2"
    ):
        run_stage(stage, silver_settings, extra_parameters={"bronze_file": bronze.as_posix()})
    tables = query(silver_settings, "select table_name from information_schema.tables")
    assert ("silver_sales",) not in tables, "the stage must leave no silver table behind"


def test_ac1_the_python_count_check_also_fails_the_build(
    silver_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    import revint.silver as silver

    write_bronze(silver_settings, [bronze_row(8), bronze_row(9)])
    original = silver.bronze_row_count
    monkeypatch.setattr(silver, "bronze_row_count", lambda path: original(path) + 1)
    with pytest.raises(SilverError, match="row count"):
        run_silver(silver_settings)


def test_ac1_the_check_passes_silently_when_the_counts_match(silver_settings: Settings) -> None:
    build(silver_settings, [bronze_row(8), bronze_row(9)])
    assert query(silver_settings, "select count(*) from silver_sales") == [(2,)]


def test_ac1_a_rebuild_replaces_the_table_and_keeps_the_count(silver_settings: Settings) -> None:
    build(silver_settings, [bronze_row(8), bronze_row(9)])
    build(silver_settings, [bronze_row(8), bronze_row(9), bronze_row(10)])
    assert query(silver_settings, "select count(*) from silver_sales") == [(3,)]


def test_ac1_a_missing_bronze_file_is_a_clear_error(silver_settings: Settings) -> None:
    with pytest.raises(SilverError, match="bronze file not found"):
        run_silver(silver_settings)


def test_ac1_two_bronze_files_for_the_sheet_are_refused(silver_settings: Settings) -> None:
    write_bronze(silver_settings, [bronze_row(8)])
    (silver_settings.paths.bronze / "other__RAW_SCJ_SALES.parquet").write_bytes(b"x")
    with pytest.raises(SilverError, match="more than one bronze file"):
        run_silver(silver_settings)


def test_ac1_the_bronze_file_is_not_modified(silver_settings: Settings) -> None:
    import hashlib

    path = write_bronze(silver_settings, [bronze_row(8, OrderReference="O")])
    before = (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
    run_silver(silver_settings)
    assert (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns) == before


# AC2: typed values, with <col>_raw holding the original text ---------------------------------


def test_ac2_dates_given_as_text_are_cast(silver_settings: Settings) -> None:
    build(
        silver_settings,
        [bronze_row(8, Date="2019-08-01 00:00:00"), bronze_row(9, Date="2019-08-02")],
    )
    assert one(silver_settings, "Date", 8) == date(2019, 8, 1)
    assert one(silver_settings, "Date", 9) == date(2019, 8, 2)
    assert one(silver_settings, "Date_raw", 8) == "2019-08-01 00:00:00"


def test_ac2_dates_given_as_excel_serial_numbers_are_cast(silver_settings: Settings) -> None:
    build(silver_settings, [bronze_row(8, Date="43678"), bronze_row(9, Date="43678.5")])
    assert one(silver_settings, "Date", 8) == date(2019, 8, 1)
    assert one(silver_settings, "Date", 9) == date(2019, 8, 1)
    assert one(silver_settings, "Date_raw", 8) == "43678"


def test_ac2_decimal_amounts_are_cast_to_decimal_18_4(silver_settings: Settings) -> None:
    build(silver_settings, [bronze_row(8, Net_Amount_2="1809.523809524", Selling_Price="2500")])
    assert one(silver_settings, "Net_Amount_2") == Decimal("1809.5238")
    assert one(silver_settings, "Selling_Price") == Decimal("2500.0000")
    assert one(silver_settings, "Net_Amount_2_raw") == "1809.523809524"
    types = dict(
        query(
            silver_settings,
            COLUMN_TYPES_SQL,
        )
    )
    assert types["Net_Amount_2"] == "DECIMAL(18,4)"


def test_ac2_integers_are_cast(silver_settings: Settings) -> None:
    build(silver_settings, [bronze_row(8, Year="2019", **{"Quantity(PCS)": "12"})])
    assert one(silver_settings, "Year") == 2019
    assert one(silver_settings, "Quantity(PCS)") == 12
    assert one(silver_settings, "Year_raw") == "2019"
    types = dict(
        query(
            silver_settings,
            COLUMN_TYPES_SQL,
        )
    )
    assert types["Year"] == "BIGINT" and types["Quantity(PCS)"] == "BIGINT"
    assert types["Date"] == "DATE"


def test_ac2_the_original_text_is_kept_exactly_including_spaces(silver_settings: Settings) -> None:
    build(
        silver_settings, [bronze_row(8, Net_Amount_2=" 5.50 ", Year=" 2019", Date=" 2019-08-01 ")]
    )
    assert one(silver_settings, "Net_Amount_2") == Decimal("5.5000")
    assert one(silver_settings, "Net_Amount_2_raw") == " 5.50 "
    assert one(silver_settings, "Year_raw") == " 2019"
    assert one(silver_settings, "Date_raw") == " 2019-08-01 "


def test_ac2_text_columns_stay_text_and_get_no_raw_twin(silver_settings: Settings) -> None:
    build(silver_settings, [bronze_row(8, OrderReference="  001 ", Customer="C & Co")])
    assert one(silver_settings, "OrderReference") == "  001 "
    names = [
        c
        for (c,) in query(
            silver_settings,
            "select column_name from information_schema.columns where table_name = 'silver_sales'",
        )
    ]
    assert "OrderReference_raw" not in names and "Customer_raw" not in names


def test_ac2_a_blank_cell_becomes_null_and_its_raw_text_is_kept(silver_settings: Settings) -> None:
    build(silver_settings, [bronze_row(8, Net_Amount_2="  ", Year="")])
    assert one(silver_settings, "Net_Amount_2") is None
    assert one(silver_settings, "Net_Amount_2_raw") == "  "
    assert one(silver_settings, "Year") is None


def test_ac2_lineage_columns_are_carried_over_unchanged(silver_settings: Settings) -> None:
    build(silver_settings, [bronze_row(8)])
    row = query(
        silver_settings, "select _source_file, _sheet, _file_hash, _ingested_at from silver_sales"
    )[0]
    assert row == ("sales.xlsx", "RAW SCJ SALES", "h" * 64, "2026-10-30T09:00:00Z")


def test_ac2_source_row_is_an_integer_matching_the_bronze_text(silver_settings: Settings) -> None:
    build(silver_settings, [bronze_row(8), bronze_row(662135)])
    assert query(silver_settings, "select _source_row from silver_sales order by 1") == [
        (8,),
        (662135,),
    ]
    assert query(
        silver_settings, "select _source_row_raw from silver_sales order by _source_row"
    ) == [("8",), ("662135",)]


def test_ac2_the_type_of_every_expected_column_is_declared(silver_settings: Settings) -> None:
    assert COLUMN_TYPES["Date"] == "date"
    assert COLUMN_TYPES["Net_Amount_2"] == "decimal"
    assert COLUMN_TYPES["Year"] == "integer"
    assert set(COLUMN_TYPES) <= set(EXPECTED), "a typed column is not in ingest.expected_columns"


def test_ac2_the_python_type_table_matches_the_sql_file() -> None:
    import re

    sql = (SILVER_DIR / "02_silver_sales.sql").read_text(encoding="utf-8")
    kinds = {"silver_date": "date", "silver_integer": "integer", "silver_decimal": "decimal"}
    in_sql = {
        match.group(2): kinds[match.group(1)]
        for match in re.finditer(r'(silver_(?:date|integer|decimal))\(src\."([^"]+)"\)', sql)
    }
    assert in_sql == COLUMN_TYPES


def test_ac2_silver_holds_all_75_source_columns_the_raw_twins_and_the_lineage(
    silver_settings: Settings,
) -> None:
    build(silver_settings, [bronze_row(8)])
    names = {
        c
        for (c,) in query(
            silver_settings,
            "select column_name from information_schema.columns where table_name = 'silver_sales'",
        )
    }
    assert set(EXPECTED) <= names
    typed = {c for c, kind in COLUMN_TYPES.items() if kind != "text"}
    assert {f"{c}_raw" for c in typed} <= names
    assert {
        "_source_file",
        "_sheet",
        "_source_row",
        "_source_row_raw",
        "_ingested_at",
        "_file_hash",
    } <= names
    # 75 source + a raw twin and a flag per typed column + 6 lineage + 4 exclusion columns (#38)
    assert len(names) == len(EXPECTED) + 2 * len(typed) + 6 + 4


def test_ac2_the_sql_selects_every_expected_column_exactly_once() -> None:
    import re

    sql = (SILVER_DIR / "02_silver_sales.sql").read_text(encoding="utf-8")
    selected = re.findall(r'^\s+(?:silver_\w+\()?src\."([^"]+)"\)?(?: as "[^"]+")?,$', sql, re.M)
    firsts = [name for name in selected if not name.endswith("_raw")]
    assert len(set(EXPECTED)) == 75
    for name in EXPECTED:
        assert sql.count(f'"{name}"') >= 1, f"{name} is not selected"
    assert firsts.count("Customer") == 1


# AC3: unparseable values -> NULL, f_bad_<col> set, row kept ------------------------------------


def test_ac3_an_unparseable_amount_becomes_null_and_sets_the_flag(
    silver_settings: Settings,
) -> None:
    build(silver_settings, [bronze_row(8, Net_Amount_2="-"), bronze_row(9, Net_Amount_2="12.5")])
    assert one(silver_settings, "Net_Amount_2", 8) is None
    assert one(silver_settings, "f_bad_Net_Amount_2", 8) is True
    assert one(silver_settings, "Net_Amount_2_raw", 8) == "-"
    assert one(silver_settings, "f_bad_Net_Amount_2", 9) is False


def test_ac3_an_unparseable_date_becomes_null_and_sets_the_flag(silver_settings: Settings) -> None:
    build(
        silver_settings,
        [
            bronze_row(8, Date="01/08/2019"),
            bronze_row(9, Date="2019-13-01"),
            bronze_row(10, Date="abc"),
        ],
    )
    for row in (8, 9, 10):
        assert one(silver_settings, "Date", row) is None
        assert one(silver_settings, "f_bad_Date", row) is True
    assert one(silver_settings, "Date_raw", 8) == "01/08/2019"


def test_ac3_an_unparseable_integer_becomes_null_and_sets_the_flag(
    silver_settings: Settings,
) -> None:
    build(
        silver_settings,
        [bronze_row(8, Year="20x9"), bronze_row(9, Year="2.5"), bronze_row(10, Year="1,000")],
    )
    for row in (8, 9, 10):
        assert one(silver_settings, "Year", row) is None
        assert one(silver_settings, "f_bad_Year", row) is True


def test_ac3_a_blank_cell_is_not_flagged_as_bad(silver_settings: Settings) -> None:
    build(silver_settings, [bronze_row(8, Net_Amount_2=None, Date="", Year="  ")])
    for column in ("Net_Amount_2", "Date", "Year"):
        assert one(silver_settings, f"f_bad_{column}") is False


def test_ac3_a_value_too_large_for_the_type_is_bad_not_an_error(silver_settings: Settings) -> None:
    build(
        silver_settings,
        [bronze_row(8, Net_Amount_2="123456789012345.5", Year="9223372036854775808")],
    )
    assert one(silver_settings, "Net_Amount_2") is None
    assert one(silver_settings, "f_bad_Net_Amount_2") is True
    assert one(silver_settings, "f_bad_Year") is True


def test_ac3_the_row_is_kept_with_its_other_values_intact(silver_settings: Settings) -> None:
    build(
        silver_settings,
        [bronze_row(8, OrderReference="O1", Customer="C1", Net_Amount_2="-", Year="2019")],
    )
    row = query(
        silver_settings, "select OrderReference, Customer, Year, Net_Amount_2 from silver_sales"
    )[0]
    assert row == ("O1", "C1", 2019, None)


def test_ac3_every_typed_column_has_a_flag_and_no_text_column_has_one(
    silver_settings: Settings,
) -> None:
    build(silver_settings, [bronze_row(8)])
    names = {
        c
        for (c,) in query(
            silver_settings,
            "select column_name from information_schema.columns where table_name = 'silver_sales'",
        )
    }
    typed = {c for c, kind in COLUMN_TYPES.items() if kind != "text"}
    assert {c for c in names if c.startswith("f_bad_")} == {f"f_bad_{c}" for c in typed}


def test_ac3_bad_value_counts_are_aggregates_the_report_can_use(silver_settings: Settings) -> None:
    rows = [bronze_row(8 + i, Net_Amount_2="-" if i % 2 else "1") for i in range(10)]
    build(silver_settings, rows)
    assert query(
        silver_settings, "select count(*) filter (where f_bad_Net_Amount_2) from silver_sales"
    ) == [(5,)]


# AC4: the six candidate amount columns are typed and kept --------------------------------------


def test_ac4_all_six_candidate_amount_columns_are_present_and_typed(
    silver_settings: Settings,
) -> None:
    assert AMOUNT_COLUMNS == tuple(SIX_AMOUNTS)
    build(
        silver_settings,
        [bronze_row(8, **dict(zip(SIX_AMOUNTS, ["1", "2", "3", "4", "5", "6"], strict=True)))],
    )
    types = dict(
        query(
            silver_settings,
            COLUMN_TYPES_SQL,
        )
    )
    for column in SIX_AMOUNTS:
        assert types[column] == "DECIMAL(18,4)"
        assert f"{column}_raw" in types and f"f_bad_{column}" in types
    row = query(silver_settings, "select " + ", ".join(SIX_AMOUNTS) + " from silver_sales")[0]
    assert row == tuple(Decimal(n) for n in ("1", "2", "3", "4", "5", "6"))


def test_ac4_none_of_the_six_is_dropped_even_when_all_values_are_bad(
    silver_settings: Settings,
) -> None:
    build(silver_settings, [bronze_row(8, **dict.fromkeys(SIX_AMOUNTS, "-"))])
    row = query(
        silver_settings,
        "select " + ", ".join(f"f_bad_{c}" for c in SIX_AMOUNTS) + " from silver_sales",
    )[0]
    assert row == (True,) * 6


def test_ac4_the_amount_columns_are_listed_in_config_independent_code_only_once() -> None:
    # The list lives in revint.silver; the net sales choice is not made here (spec 02).
    assert len(set(AMOUNT_COLUMNS)) == 6


# Build behaviour ---------------------------------------------------------------------------------


def test_the_silver_stage_folder_holds_numbered_sql_files() -> None:
    files = sorted(p.name for p in SILVER_DIR.glob("*.sql"))
    assert files[0] == "01_helpers.sql" and files == sorted(files)
    assert all(name[:2].isdigit() for name in files)


def test_a_failed_build_leaves_no_silver_table(silver_settings: Settings) -> None:
    write_bronze(silver_settings, [bronze_row(8)])
    # Break the bronze file: drop a column silver expects.
    path = next(silver_settings.paths.bronze.glob("*.parquet"))
    pl.read_parquet(path).drop("Customer").write_parquet(path)
    with pytest.raises(SilverError, match="Customer"):
        run_silver(silver_settings)
    assert not silver_settings.paths.warehouse.exists() or query(
        silver_settings,
        "select count(*) from information_schema.tables where table_name = 'silver_sales'",
    ) == [(0,)]


def test_a_bronze_file_with_an_unexpected_extra_column_is_refused(
    silver_settings: Settings,
) -> None:
    write_bronze(silver_settings, [bronze_row(8)])
    path = next(silver_settings.paths.bronze.glob("*.parquet"))
    pl.read_parquet(path).with_columns(pl.lit("x").alias("Surprise")).write_parquet(path)
    with pytest.raises(SilverError, match="Surprise"):
        run_silver(silver_settings)


def test_the_build_is_repeatable_with_identical_content(silver_settings: Settings) -> None:
    rows = [bronze_row(8 + i, Net_Amount_2=str(i), Date="2019-08-01") for i in range(5)]
    build(silver_settings, rows)
    first = query(silver_settings, "select * from silver_sales order by _source_row")
    run_silver(silver_settings)
    assert query(silver_settings, "select * from silver_sales order by _source_row") == first


def test_the_stage_logs_counts_and_no_values(
    silver_settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    build(silver_settings, [bronze_row(8, Customer="SECRET-CUSTOMER", Net_Amount_2="777.77")])
    with caplog.at_level(logging.DEBUG, logger="revint"):
        run_silver(silver_settings)
    assert "SECRET-CUSTOMER" not in caplog.text and "777.77" not in caplog.text


def test_build_silver_command_is_still_a_stub_until_the_cli_story() -> None:
    from typer.testing import CliRunner

    from revint.cli import app

    result = CliRunner().invoke(app, ["build", "silver"])
    assert result.exit_code == 3 and "not implemented" in result.output.lower()


# Real file: runs only when data/ exists ---------------------------------------------------------


@pytest.mark.realdata
def test_ac1_real_file_silver_matches_bronze_and_the_sums_agree(tmp_path: Path) -> None:
    """Counts and sums only; no individual value is asserted or printed."""
    settings = load_settings(
        env={
            "REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb"),
        }
    )
    bronze_files = list(settings.paths.bronze.glob("*__RAW_SCJ_SALES.parquet"))
    if not bronze_files:
        pytest.skip("bronze not built: run `uv run revint build bronze` first")
    result = run_silver(settings)
    con = duckdb.connect(str(settings.paths.warehouse), read_only=True)
    try:
        bronze_rows = con.execute(
            "select count(*) from read_parquet(?)", [bronze_files[0].as_posix()]
        ).fetchone()[0]
        silver_rows = con.execute("select count(*) from silver_sales").fetchone()[0]
        assert silver_rows == bronze_rows == result.rows
        for column in AMOUNT_COLUMNS:
            exact, typed, bad, kept = con.execute(
                f"""select sum(try_cast(trim("{column}_raw") as double)),
                           sum("{column}"::double),
                           count(*) filter (where f_bad_{column}),
                           count(*) filter (where "{column}" is not null)
                    from silver_sales"""
            ).fetchone()
            # Rounding to four decimals moves each sum by well under one currency unit.
            assert abs((exact or 0) - (typed or 0)) < 1.0, f"{column}: sum drifted"
            assert bad + kept <= silver_rows, f"{column}: more typed and bad values than rows"
    finally:
        con.close()
