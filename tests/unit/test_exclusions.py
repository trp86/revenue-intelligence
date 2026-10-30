"""Story #38: exclusion marking and the audit table (spec 01 S9, S10, S12; decision D1).

Synthetic bronze data only. The real-file test is marked `realdata` and asserts counts and
sums, never individual values.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from silver_helpers import (
    COLUMN_TYPES_SQL,
    EXPECTED,
    SIX_AMOUNTS,
    bronze_row,
    build,
    force_exact_duplicate_sql,
    query,
    run_custom_stage,
    write_bronze,
)

from revint.config import Settings, load_settings
from revint.pipeline import StageError
from revint.silver import (
    ALLOWED_EXCLUSION_REASONS,
    SILVER_DIR,
    SilverError,
    run_silver,
)

CTN = "Change_to_Ctn"
STRAY = {CTN: "1"}  # only Change to Ctn filled, with 1: the stray row (decision D1)


@pytest.fixture
def silver_settings(load_with) -> Settings:
    return load_with({"ingest": {"expected_columns": EXPECTED, "sheets": ["RAW SCJ SALES"]}})


def with_flag(load_with, exclude: bool) -> Settings:
    return load_with(
        {
            "ingest": {"expected_columns": EXPECTED, "sheets": ["RAW SCJ SALES"]},
            "duplicates": {"exclude_from_net_sales": exclude},
        },
        name="on" if exclude else "off",
    )


def data_row(source_row: int, **cells: str | None):
    """An ordinary order line: several cells filled, so it is never a stray row."""
    base = {
        "OrderReference": f"O{source_row}",
        "Customer": "C",
        "Quantity(PCS)": "2",
        "Net_Amount_2": "10",
    }
    base.update(cells)
    return bronze_row(source_row, **base)


def amounts(**values: str) -> dict[str, str | None]:
    return {**dict.fromkeys(SIX_AMOUNTS), **values}


# AC1: the stray row is marked, flagged and kept --------------------------------------------


def test_ac1_the_stray_row_is_excluded_with_its_reason_and_flag(silver_settings: Settings) -> None:
    build(silver_settings, [data_row(8), data_row(9), bronze_row(10, **STRAY)])
    row = query(
        silver_settings,
        "select is_excluded, exclusion_reason, f_stray_row "
        "from silver_sales where _source_row = 10",
    )[0]
    assert row == (True, "stray_row", True)


def test_ac1_the_stray_row_stays_in_silver_sales(silver_settings: Settings) -> None:
    build(silver_settings, [data_row(8), bronze_row(9, **STRAY)])
    assert query(silver_settings, "select count(*) from silver_sales") == [(2,)]
    assert query(silver_settings, "select _source_row from silver_sales order by 1") == [(8,), (9,)]


def test_ac1_ordinary_rows_are_not_excluded_and_not_flagged(silver_settings: Settings) -> None:
    build(silver_settings, [data_row(8), data_row(9), bronze_row(10, **STRAY)])
    rows = query(
        silver_settings,
        "select _source_row, is_excluded, exclusion_reason, f_stray_row, is_duplicate "
        "from silver_sales where _source_row < 10 order by 1",
    )
    assert rows == [(8, False, None, False, False), (9, False, None, False, False)]


def test_ac1_a_row_with_only_change_to_ctn_equal_to_one_is_the_stray_row(
    silver_settings: Settings,
) -> None:
    # three matching rows would fail the build (AC2), so build one spelling at a time
    for spelling in ("1.0", " 1 ", "1.00", "1"):
        build(silver_settings, [data_row(8), bronze_row(9, **{CTN: spelling})])
        found = query(silver_settings, "select _source_row from silver_sales where f_stray_row")
        assert found == [(9,)], f"Change to Ctn = {spelling!r} was not found"


@pytest.mark.parametrize(
    "cells",
    [
        {CTN: "1", "Customer": "C"},  # another cell is filled
        {CTN: "1", "Quantity(PCS)": "0"},  # another cell is filled, even with zero
        {CTN: "2"},  # not 1
        {CTN: "0"},
        {CTN: "-"},  # not a number
        {CTN: "1x"},
        {CTN: None},  # nothing filled at all: a blank row, not the stray row
    ],
)
def test_ac1_other_rows_are_not_the_stray_row(silver_settings: Settings, cells) -> None:
    build(silver_settings, [data_row(8), bronze_row(9, **cells)])
    assert query(silver_settings, "select count(*) from silver_sales where f_stray_row") == [(0,)]
    assert query(silver_settings, "select count(*) from silver_sales where is_excluded") == [(0,)]


def test_ac1_cells_with_only_spaces_count_as_blank(silver_settings: Settings) -> None:
    build(
        silver_settings,
        [data_row(8), bronze_row(9, **{CTN: "1", "Customer": "  ", "OrderReference": " "})],
    )
    assert query(silver_settings, "select _source_row from silver_sales where f_stray_row") == [
        (9,)
    ]


def test_ac1_a_stray_row_anywhere_in_the_sheet_is_found(silver_settings: Settings) -> None:
    build(silver_settings, [data_row(8), bronze_row(9, **STRAY), data_row(10)])
    assert query(silver_settings, "select _source_row from silver_sales where f_stray_row") == [
        (9,)
    ]


def test_ac1_a_sheet_without_a_stray_row_builds_with_no_exclusions(
    silver_settings: Settings,
) -> None:
    build(silver_settings, [data_row(8), data_row(9)])
    assert query(silver_settings, "select count(*) from silver_sales where is_excluded") == [(0,)]
    assert query(silver_settings, "select count(*) from silver_excluded_rows") == [(0,)]


def test_ac1_the_flag_columns_have_the_declared_types(silver_settings: Settings) -> None:
    build(silver_settings, [data_row(8), bronze_row(9, **STRAY)])
    types = dict(query(silver_settings, COLUMN_TYPES_SQL))
    assert types["is_excluded"] == "BOOLEAN"
    assert types["exclusion_reason"] == "VARCHAR"
    assert types["f_stray_row"] == "BOOLEAN"
    assert types["is_duplicate"] == "BOOLEAN"


def test_ac1_the_flag_columns_are_never_null(silver_settings: Settings) -> None:
    build(silver_settings, [data_row(8), bronze_row(9, **STRAY), data_row(10)])
    nulls = query(
        silver_settings,
        "select count(*) filter (where is_excluded is null), "
        "count(*) filter (where f_stray_row is null), "
        "count(*) filter (where is_duplicate is null) from silver_sales",
    )
    assert nulls == [(0, 0, 0)]


def test_ac1_the_stray_rows_other_columns_are_untouched(silver_settings: Settings) -> None:
    build(silver_settings, [bronze_row(8, **STRAY)])
    row = query(
        silver_settings,
        'select "Change_to_Ctn", "Change_to_Ctn_raw", "Customer", _source_row from silver_sales',
    )[0]
    assert row == (Decimal("1.0000"), "1", None, 8)


# AC2: two matching rows fail the build for review ----------------------------------------------


def test_ac2_two_stray_rows_fail_the_build(silver_settings: Settings) -> None:
    write_bronze(silver_settings, [data_row(8), bronze_row(9, **STRAY), bronze_row(10, **STRAY)])
    with pytest.raises(SilverError, match=r"2 rows match the stray-row rule.*review"):
        run_silver(silver_settings)


def test_ac2_a_failed_build_leaves_no_silver_tables(silver_settings: Settings) -> None:
    write_bronze(silver_settings, [data_row(8), bronze_row(9, **STRAY), bronze_row(10, **STRAY)])
    with pytest.raises(SilverError):
        run_silver(silver_settings)
    tables = (
        query(silver_settings, "select table_name from information_schema.tables")
        if silver_settings.paths.warehouse.exists()
        else []
    )
    assert ("silver_sales",) not in tables and ("silver_excluded_rows",) not in tables


def test_ac2_a_failed_rebuild_keeps_the_previous_good_tables(silver_settings: Settings) -> None:
    build(silver_settings, [data_row(8), bronze_row(9, **STRAY)])
    write_bronze(silver_settings, [data_row(8), bronze_row(9, **STRAY), bronze_row(10, **STRAY)])
    with pytest.raises(SilverError):
        run_silver(silver_settings)
    assert query(silver_settings, "select count(*) from silver_sales") == [(2,)]
    assert query(silver_settings, "select count(*) from silver_excluded_rows") == [(1,)]


def test_ac2_the_error_names_counts_and_source_rows_but_no_cell_values(
    silver_settings: Settings,
) -> None:
    rows = [
        data_row(8, Customer="SECRET-CUSTOMER"),
        bronze_row(9, **STRAY),
        bronze_row(10, **STRAY),
    ]
    write_bronze(silver_settings, rows)
    with pytest.raises(SilverError) as info:
        run_silver(silver_settings)
    message = str(info.value)
    assert "SECRET-CUSTOMER" not in message
    assert "07_checks.sql" in message
    assert "source rows 9, 10" in message
    assert "\n" not in message


def test_ac2_the_check_is_a_sql_check_inside_the_stage(
    silver_settings: Settings, tmp_path: Path
) -> None:
    rows = [data_row(8), bronze_row(9, **STRAY), bronze_row(10, **STRAY)]
    with pytest.raises(StageError, match=r"07_checks\.sql.*2 rows match the stray-row rule"):
        run_custom_stage(silver_settings, rows, tmp_path / "10_silver")


# AC3: silver_excluded_rows -------------------------------------------------------------------


def test_ac3_every_excluded_row_is_recorded_with_the_required_columns(
    silver_settings: Settings,
) -> None:
    build(silver_settings, [data_row(8), bronze_row(9, **STRAY)])
    columns = [
        c
        for (c,) in query(
            silver_settings,
            "select column_name from information_schema.columns "
            "where table_name = 'silver_excluded_rows' order by ordinal_position",
        )
    ]
    assert columns == [
        "_source_row",
        "exclusion_reason",
        "duplicate_of_source_row",
        *SIX_AMOUNTS,
        "excluded_at",
    ]


def test_ac3_the_recorded_row_matches_the_silver_row(silver_settings: Settings) -> None:
    build(silver_settings, [data_row(8), bronze_row(9, **STRAY)])
    audit = query(
        silver_settings,
        "select _source_row, exclusion_reason, duplicate_of_source_row from silver_excluded_rows",
    )
    assert audit == [(9, "stray_row", None)]
    # a stray row has no amounts, so all six are NULL
    sums = query(
        silver_settings,
        "select " + ", ".join(f"count({c})" for c in SIX_AMOUNTS) + " from silver_excluded_rows",
    )
    assert sums == [(0, 0, 0, 0, 0, 0)]


def test_ac3_the_six_amounts_are_copied_from_silver_for_an_excluded_row(
    silver_settings: Settings, tmp_path: Path
) -> None:
    """An exact duplicate (story #39) is a full order line, so its amounts must be copied."""
    files = {"04b_force.sql": force_exact_duplicate_sql(9)}  # after 04, before the audit file
    rows = [
        data_row(8),
        data_row(9, **amounts(Selling_Amount="5", Net_Amount_2="12.5", TAX_AMOUNT="3")),
    ]
    run_custom_stage(silver_settings, rows, tmp_path / "s", files)
    audit = query(
        silver_settings,
        "select _source_row, Selling_Amount, Net_Amount_2, TAX_AMOUNT, AMOUNT_AF_DIS "
        "from silver_excluded_rows",
    )
    assert audit == [(9, Decimal("5.0000"), Decimal("12.5000"), Decimal("3.0000"), None)]


def test_ac3_the_audit_table_holds_exactly_the_excluded_rows(silver_settings: Settings) -> None:
    build(silver_settings, [data_row(8), bronze_row(9, **STRAY), data_row(10)])
    assert query(
        silver_settings,
        "select (select count(*) from silver_excluded_rows), "
        "(select count(*) from silver_sales where is_excluded)",
    ) == [(1, 1)]
    assert query(
        silver_settings,
        "select count(*) from silver_sales s join silver_excluded_rows e using (_source_row) "
        "where s.is_excluded",
    ) == [(1,)]


def test_ac3_duplicate_of_source_row_is_null_for_a_stray_row(silver_settings: Settings) -> None:
    build(silver_settings, [data_row(8), bronze_row(9, **STRAY)])
    assert query(silver_settings, "select duplicate_of_source_row from silver_excluded_rows") == [
        (None,)
    ]
    types = dict(
        query(
            silver_settings,
            "select column_name, data_type from information_schema.columns "
            "where table_name = 'silver_excluded_rows'",
        )
    )
    assert types["duplicate_of_source_row"] == "BIGINT"
    assert types["_source_row"] == "BIGINT"
    assert types["excluded_at"] == "TIMESTAMP"
    for column in SIX_AMOUNTS:
        assert types[column] == "DECIMAL(18,4)"


def test_ac3_excluded_at_is_one_utc_timestamp_for_the_whole_build(
    silver_settings: Settings,
) -> None:
    before = datetime.now(UTC).replace(tzinfo=None)
    build(silver_settings, [data_row(8), bronze_row(9, **STRAY)])
    after = datetime.now(UTC).replace(tzinfo=None)
    stamps = query(silver_settings, "select distinct excluded_at from silver_excluded_rows")
    assert len(stamps) == 1
    assert before.replace(microsecond=0) <= stamps[0][0] <= after


def test_ac3_the_audit_table_is_rebuilt_not_appended(silver_settings: Settings) -> None:
    build(silver_settings, [data_row(8), bronze_row(9, **STRAY)])
    run_silver(silver_settings)
    assert query(silver_settings, "select count(*) from silver_excluded_rows") == [(1,)]


def test_ac3_a_rebuild_without_the_stray_row_empties_the_audit_table(
    silver_settings: Settings,
) -> None:
    build(silver_settings, [data_row(8), bronze_row(9, **STRAY)])
    build(silver_settings, [data_row(8), data_row(9)])
    assert query(silver_settings, "select count(*) from silver_excluded_rows") == [(0,)]


def test_ac3_the_other_columns_of_the_stray_row_are_not_copied_to_the_audit_table(
    silver_settings: Settings,
) -> None:
    build(silver_settings, [bronze_row(9, **STRAY)])
    names = {
        c
        for (c,) in query(
            silver_settings,
            "select column_name from information_schema.columns "
            "where table_name = 'silver_excluded_rows'",
        )
    }
    assert "Customer" not in names and "CustomerCode" not in names


# AC4: any other exclusion reason fails a check ---------------------------------------------------


def force_reason(reason: str, where: str = "_source_row = 9") -> dict[str, str]:
    return {
        "03b_force.sql": (
            "update silver_sales set is_excluded = true, "
            f"exclusion_reason = '{reason}' where {where};"
        )
    }


def stage_files_with_force(reason: str) -> dict[str, str]:
    # Runs after the real exclusion file and before the checks, which must then catch it.
    return force_reason(reason)


def test_ac4_the_allowed_reasons_are_exactly_stray_row_and_exact_duplicate() -> None:
    assert ALLOWED_EXCLUSION_REASONS == ("stray_row", "exact_duplicate")


def test_ac4_an_unknown_reason_fails_the_check_and_names_it(
    silver_settings: Settings, tmp_path: Path
) -> None:
    rows = [data_row(8), data_row(9), bronze_row(10, **STRAY)]
    with pytest.raises(StageError, match=r"exclusion reason.*not allowed.*other_reason"):
        run_custom_stage(
            silver_settings, rows, tmp_path / "s", extra_files=force_reason("other_reason")
        )


def test_ac4_a_void_or_negative_reason_is_refused_too(
    silver_settings: Settings, tmp_path: Path
) -> None:
    for number, reason in enumerate(["void", "negative_qty", "free_goods"]):
        with pytest.raises(StageError, match=r"not allowed"):
            run_custom_stage(
                silver_settings,
                [data_row(8), data_row(9), bronze_row(10, **STRAY)],
                tmp_path / f"s{number}",
                extra_files=force_reason(reason),
            )


def test_ac4_an_excluded_row_without_a_reason_fails_the_check(
    silver_settings: Settings, tmp_path: Path
) -> None:
    files = {"03b_force.sql": "update silver_sales set is_excluded = true where _source_row = 9;"}
    with pytest.raises(StageError, match=r"without a reason"):
        run_custom_stage(silver_settings, [data_row(8), data_row(9)], tmp_path / "s", files)


def test_ac4_a_reason_on_a_row_that_is_not_excluded_fails_the_check(
    silver_settings: Settings, tmp_path: Path
) -> None:
    files = {
        "03b_force.sql": (
            "update silver_sales set exclusion_reason = 'stray_row' where _source_row = 9;"
        )
    }
    with pytest.raises(StageError, match=r"reason.*not excluded"):
        run_custom_stage(silver_settings, [data_row(8), data_row(9)], tmp_path / "s", files)


def test_ac4_an_excluded_row_missing_from_the_audit_table_fails_the_check(
    silver_settings: Settings, tmp_path: Path
) -> None:
    files = {
        "06b_force.sql": (
            "update silver_sales set is_excluded = true, exclusion_reason = 'stray_row' "
            "where _source_row = 9;"
        )
    }
    # runs after 06_excluded_rows.sql, so the audit table lacks row 9
    with pytest.raises(
        StageError, match=r"silver_excluded_rows.*differ|differ.*silver_excluded_rows"
    ):
        run_custom_stage(
            silver_settings,
            [data_row(8), data_row(9), bronze_row(10, **STRAY)],
            tmp_path / "s",
            files,
        )


def test_ac4_two_reasons_that_are_allowed_pass_the_check(
    silver_settings: Settings, tmp_path: Path
) -> None:
    # exact_duplicate is a valid reason even though the rule that sets it arrives in #39;
    # the audit table is rebuilt after the forced update, so the checks pass.
    files = {"04b_force.sql": force_exact_duplicate_sql(9)}  # after 04, before the audit file
    result = run_custom_stage(silver_settings, [data_row(8), data_row(9)], tmp_path / "s", files)
    assert result.statements > 0
    assert query(silver_settings, "select exclusion_reason from silver_excluded_rows") == [
        ("exact_duplicate",)
    ]


def test_ac4_the_real_build_never_produces_another_reason(silver_settings: Settings) -> None:
    build(silver_settings, [data_row(8), bronze_row(9, **STRAY), data_row(10)])
    reasons = {
        r for (r,) in query(silver_settings, "select distinct exclusion_reason from silver_sales")
    }
    assert reasons <= {None, *ALLOWED_EXCLUSION_REASONS}


# AC5: identical for both settings of duplicates.exclude_from_net_sales ----------------------------


def test_ac5_the_audit_table_and_is_excluded_do_not_depend_on_the_setting(load_with) -> None:
    rows = [data_row(8), data_row(9), bronze_row(10, **STRAY), data_row(11)]
    results = {}
    for exclude in (True, False):
        settings = with_flag(load_with, exclude)
        build(settings, rows)
        results[exclude] = (
            query(
                settings,
                "select _source_row, is_excluded, exclusion_reason, f_stray_row, is_duplicate "
                "from silver_sales order by _source_row",
            ),
            query(
                settings,
                "select _source_row, exclusion_reason, duplicate_of_source_row, "
                + ", ".join(SIX_AMOUNTS)
                + " from silver_excluded_rows order by _source_row",
            ),
        )
    assert results[True] == results[False]
    assert results[True][1] != [], "the comparison must not be on two empty tables"


def test_ac5_the_setting_is_not_read_by_the_silver_sql() -> None:

    for path in SILVER_DIR.glob("*.sql"):
        text = path.read_text(encoding="utf-8")
        assert "duplicates_exclude_from_net_sales" not in text, path.name


def test_ac5_the_setting_changes_nothing_in_silver_even_with_an_exact_duplicate_present(
    load_with, tmp_path: Path
) -> None:
    files = {"04b_force.sql": force_exact_duplicate_sql(9)}  # after 04, before the audit file
    rows = [data_row(8), data_row(9), bronze_row(10, **STRAY)]
    seen = []
    for exclude in (True, False):
        settings = with_flag(load_with, exclude)
        run_custom_stage(settings, rows, tmp_path / f"s{exclude}", files)
        seen.append(
            query(
                settings,
                "select _source_row, exclusion_reason from silver_excluded_rows order by 1",
            )
        )
    assert seen[0] == seen[1] == [(9, "exact_duplicate"), (10, "stray_row")]


# Build behaviour ---------------------------------------------------------------------------


def test_the_silver_stage_has_the_exclusion_file_between_typing_and_checks() -> None:

    names = sorted(p.name for p in SILVER_DIR.glob("*.sql"))
    assert names.index("02_silver_sales.sql") < names.index("03_exclusions.sql")
    assert (
        names.index("03_exclusions.sql")
        < names.index("06_excluded_rows.sql")
        < names.index("07_checks.sql")
    )
    assert "03_checks.sql" not in names and "04_checks.sql" not in names


def test_every_bronze_row_still_has_a_silver_row(silver_settings: Settings) -> None:
    rows = [data_row(8), bronze_row(9, **STRAY), data_row(10)]
    build(silver_settings, rows)
    assert query(silver_settings, "select count(*) from silver_sales") == [(len(rows),)]


def test_the_stage_logs_counts_and_no_values(
    silver_settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    write_bronze(silver_settings, [data_row(8, Customer="SECRET-CUSTOMER"), bronze_row(9, **STRAY)])
    with caplog.at_level(logging.DEBUG, logger="revint"):
        run_silver(silver_settings)
    assert "SECRET-CUSTOMER" not in caplog.text


def test_silver_columns_now_include_the_exclusion_columns(silver_settings: Settings) -> None:
    build(silver_settings, [data_row(8)])
    names = {
        c
        for (c,) in query(
            silver_settings,
            "select column_name from information_schema.columns where table_name = 'silver_sales'",
        )
    }
    assert {"is_excluded", "exclusion_reason", "f_stray_row", "is_duplicate"} <= names


# Real file: runs only when data/ exists -----------------------------------------------------


@pytest.mark.realdata
def test_ac1_real_file_has_exactly_one_stray_row_and_it_is_the_last_row(tmp_path: Path) -> None:
    """Counts and structure only; no individual value is asserted or printed."""
    import duckdb

    settings = load_settings(env={"REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb")})
    if not list(settings.paths.bronze.glob("*__RAW_SCJ_SALES.parquet")):
        pytest.skip("bronze not built: run `uv run revint build bronze` first")
    run_silver(settings)
    con = duckdb.connect(str(settings.paths.warehouse), read_only=True)
    try:
        excluded, strays, audit, stray_row = con.execute(
            "select count(*) filter (where is_excluded), count(*) filter (where f_stray_row), "
            "(select count(*) from silver_excluded_rows), "
            "min(_source_row) filter (where f_stray_row) from silver_sales"
        ).fetchone()
        assert (excluded, strays, audit) == (1, 1, 1)
        assert stray_row == 662135
        reasons = con.execute(
            "select distinct exclusion_reason from silver_sales where is_excluded"
        ).fetchall()
        assert reasons == [("stray_row",)]
        total = con.execute("select count(*) from silver_sales").fetchone()[0]
        assert total == 662_128
    finally:
        con.close()
