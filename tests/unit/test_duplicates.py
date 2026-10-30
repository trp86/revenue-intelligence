"""Story #39: exact duplicates (spec 01 S5, decision D4, provisional).

Synthetic bronze data only. The real-file test is marked `realdata` and asserts counts, never
individual values.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from silver_helpers import (
    EXPECTED,
    SIX_AMOUNTS,
    bronze_row,
    build,
    query,
    write_bronze,
)

from revint.config import Settings, load_settings
from revint.silver import SILVER_DIR, SilverError, run_silver


@pytest.fixture
def silver_settings(load_with) -> Settings:
    return load_with({"ingest": {"expected_columns": EXPECTED, "sheets": ["RAW SCJ SALES"]}})


def with_flag(load_with, exclude: bool, **ingest: object) -> Settings:
    return load_with(
        {
            "ingest": {"expected_columns": EXPECTED, "sheets": ["RAW SCJ SALES"], **ingest},
            "duplicates": {"exclude_from_net_sales": exclude},
        },
        name="on" if exclude else "off",
    )


def line(source_row: int, **cells: str | None):
    """An order line. The default cells are the same for every row, so lines with different
    `source_row` values are exact duplicates unless a cell is changed."""
    base = {"OrderReference": "O1", "Customer": "C", "Quantity(PCS)": "2", "Net_Amount_2": "10"}
    base.update(cells)
    return bronze_row(source_row, **base)


def state(settings: Settings) -> list[tuple]:
    return query(
        settings,
        "select _source_row, is_duplicate, is_excluded, exclusion_reason "
        "from silver_sales order by _source_row",
    )


def audit(settings: Settings) -> list[tuple]:
    return query(
        settings,
        "select _source_row, exclusion_reason, duplicate_of_source_row "
        "from silver_excluded_rows order by _source_row",
    )


# AC1: 3 identical rows -> the lowest _source_row is kept, the other two are marked ---------------


def test_ac1_three_identical_rows_keep_the_first_and_mark_the_other_two(
    silver_settings: Settings,
) -> None:
    build(silver_settings, [line(8), line(9), line(10)])
    assert state(silver_settings) == [
        (8, False, False, None),
        (9, True, True, "exact_duplicate"),
        (10, True, True, "exact_duplicate"),
    ]


def test_ac1_the_first_occurrence_is_the_lowest_source_row_whatever_the_file_order(
    silver_settings: Settings,
) -> None:
    build(silver_settings, [line(12), line(8), line(10)])
    assert state(silver_settings) == [
        (8, False, False, None),
        (10, True, True, "exact_duplicate"),
        (12, True, True, "exact_duplicate"),
    ]


def test_ac1_every_copy_points_at_the_kept_first_occurrence(silver_settings: Settings) -> None:
    build(silver_settings, [line(8), line(9), line(10)])
    assert audit(silver_settings) == [
        (9, "exact_duplicate", 8),
        (10, "exact_duplicate", 8),
    ]


def test_ac1_the_copies_stay_in_silver_sales(silver_settings: Settings) -> None:
    build(silver_settings, [line(8), line(9), line(10)])
    assert query(silver_settings, "select count(*) from silver_sales") == [(3,)]


def test_ac1_separate_groups_each_keep_their_own_first_row(silver_settings: Settings) -> None:
    rows = [
        line(8),
        line(9, OrderReference="O2"),
        line(10),
        line(11, OrderReference="O2"),
        line(12, OrderReference="O3"),
    ]
    build(silver_settings, rows)
    assert audit(silver_settings) == [(10, "exact_duplicate", 8), (11, "exact_duplicate", 9)]
    flags = {r: dup for r, dup, *_ in state(silver_settings)}
    assert flags == {8: False, 9: False, 10: True, 11: True, 12: False}


def test_ac1_the_audit_table_holds_the_six_amounts_of_each_copy(silver_settings: Settings) -> None:
    amounts = {"Net_Amount_2": "12.5", "TAX_AMOUNT": "3", "Selling_Amount": "5"}
    build(silver_settings, [line(8, **amounts), line(9, **amounts)])
    row = query(
        silver_settings,
        "select _source_row, Selling_Amount, Net_Amount_2, TAX_AMOUNT, AMOUNT_AF_DIS "
        "from silver_excluded_rows",
    )
    from decimal import Decimal

    assert row == [(9, Decimal("5.0000"), Decimal("12.5000"), Decimal("3.0000"), None)]


def test_ac1_the_flag_columns_are_never_null(silver_settings: Settings) -> None:
    build(silver_settings, [line(8), line(9), line(10, OrderReference="O9")])
    nulls = query(
        silver_settings,
        "select count(*) filter (where is_duplicate is null), "
        "count(*) filter (where is_excluded is null) from silver_sales",
    )
    assert nulls == [(0, 0)]


def test_ac1_no_duplicates_means_no_marks(silver_settings: Settings) -> None:
    build(silver_settings, [line(8), line(9, OrderReference="O2"), line(10, OrderReference="O3")])
    assert query(
        silver_settings, "select count(*) filter (where is_duplicate) from silver_sales"
    ) == [(0,)]
    assert audit(silver_settings) == []


def test_ac1_a_kept_first_occurrence_is_not_excluded_and_has_no_reason(
    silver_settings: Settings,
) -> None:
    build(silver_settings, [line(8), line(9)])
    first = query(
        silver_settings,
        "select is_duplicate, is_excluded, exclusion_reason "
        "from silver_sales where _source_row = 8",
    )
    assert first == [(False, False, None)]


# AC2: rows that differ in one column are not duplicates ----------------------------------------


@pytest.mark.parametrize(
    ("column", "other"),
    [
        ("OrderReference", "O2"),
        ("Customer", "D"),
        ("Quantity(PCS)", "3"),
        ("Net_Amount_2", "10.5"),
        ("Region", "R"),  # a column the other row leaves blank
        ("Void", "Unvoid"),
    ],
)
def test_ac2_rows_that_differ_in_one_column_are_not_duplicates(
    silver_settings: Settings, column: str, other: str
) -> None:
    build(silver_settings, [line(8), line(9, **{column: other})])
    assert state(silver_settings) == [(8, False, False, None), (9, False, False, None)]
    assert audit(silver_settings) == []


def test_ac2_a_difference_in_any_of_the_75_source_columns_breaks_the_match(
    silver_settings: Settings,
) -> None:
    for column in EXPECTED:
        build(silver_settings, [line(8, **{column: "same"}), line(9, **{column: "different"})])
        found = query(
            silver_settings, "select count(*) filter (where is_duplicate) from silver_sales"
        )
        assert found == [(0,)], f"{column} did not break the match"


def test_ac2_the_pair_is_a_duplicate_only_when_nothing_differs(silver_settings: Settings) -> None:
    build(silver_settings, [line(8), line(9), line(10, Customer="D")])
    assert audit(silver_settings) == [(9, "exact_duplicate", 8)]


def test_ac2_lineage_columns_are_ignored_when_comparing(silver_settings: Settings) -> None:
    first, second = line(8), line(9)
    second["_ingested_at"] = "2030-01-01T00:00:00Z"
    second["_file_hash"] = "z" * 64
    second["_source_file"] = "other.xlsx"
    second["_sheet"] = "OTHER"
    build(silver_settings, [first, second])
    assert audit(silver_settings) == [(9, "exact_duplicate", 8)]


def test_ac2_source_row_alone_does_not_make_rows_different(silver_settings: Settings) -> None:
    build(silver_settings, [line(8), line(662135)])
    assert audit(silver_settings) == [(662135, "exact_duplicate", 8)]


def test_ac2_the_stray_row_is_never_the_copy_of_another_row(silver_settings: Settings) -> None:
    stray = {"Change_to_Ctn": "1"}
    only_ctn = bronze_row(10, **stray)
    twin = bronze_row(11, **stray)
    # two identical stray rows fail the build (story 38); one stray row next to data does not
    build(silver_settings, [line(8), line(9), only_ctn])
    reasons = query(
        silver_settings,
        "select _source_row, exclusion_reason from silver_excluded_rows order by 1",
    )
    assert reasons == [(9, "exact_duplicate"), (10, "stray_row")]
    with pytest.raises(SilverError, match="stray-row rule"):
        build(silver_settings, [line(8), only_ctn, twin])


# AC3: blank cells compare equal; case and spaces differ ------------------------------------------


def test_ac3_null_empty_and_whitespace_only_cells_compare_equal(silver_settings: Settings) -> None:
    rows = [
        line(8, Customer=None),
        line(9, Customer=""),
        line(10, Customer="   "),
        line(11, Customer="\t"),
        line(12, Customer=" "),
    ]
    build(silver_settings, rows)
    assert audit(silver_settings) == [
        (9, "exact_duplicate", 8),
        (10, "exact_duplicate", 8),
        (11, "exact_duplicate", 8),
        (12, "exact_duplicate", 8),
    ]


def test_ac3_blank_cells_in_several_columns_compare_equal_together(
    silver_settings: Settings,
) -> None:
    a = line(8, Customer=None, Region="")
    b = line(9, Customer="  ", Region=None)
    build(silver_settings, [a, b])
    assert audit(silver_settings) == [(9, "exact_duplicate", 8)]


def test_ac3_a_versus_lower_case_a_differ(silver_settings: Settings) -> None:
    build(silver_settings, [line(8, Customer="A"), line(9, Customer="a")])
    assert audit(silver_settings) == []


def test_ac3_a_versus_a_with_a_trailing_space_differ(silver_settings: Settings) -> None:
    build(silver_settings, [line(8, Customer="A"), line(9, Customer="A ")])
    assert audit(silver_settings) == []


def test_ac3_a_leading_space_and_a_double_space_differ(silver_settings: Settings) -> None:
    build(
        silver_settings,
        [line(8, Customer="A B"), line(9, Customer=" A B"), line(10, Customer="A  B")],
    )
    assert audit(silver_settings) == []


def test_ac3_a_blank_cell_does_not_equal_a_filled_cell(silver_settings: Settings) -> None:
    build(silver_settings, [line(8, Customer=None), line(9, Customer="A")])
    assert audit(silver_settings) == []


def test_ac3_the_text_is_compared_not_the_typed_value(silver_settings: Settings) -> None:
    """`10` and `10.0` are the same number but different text, so they are not duplicates."""
    build(silver_settings, [line(8, Net_Amount_2="10"), line(9, Net_Amount_2="10.0")])
    assert audit(silver_settings) == []
    assert query(silver_settings, "select count(distinct Net_Amount_2) from silver_sales") == [(1,)]


def test_ac3_values_that_look_alike_but_differ_in_a_bad_cell_are_still_compared_as_text(
    silver_settings: Settings,
) -> None:
    build(silver_settings, [line(8, Net_Amount_2="-"), line(9, Net_Amount_2="-")])
    assert audit(silver_settings) == [(9, "exact_duplicate", 8)]


# AC4: the setting duplicates.exclude_from_net_sales does not change silver -----------------------


def test_ac4_with_the_setting_false_silver_still_marks_and_records_the_copies(load_with) -> None:
    settings = with_flag(load_with, False)
    build(settings, [line(8), line(9), line(10)])
    assert state(settings) == [
        (8, False, False, None),
        (9, True, True, "exact_duplicate"),
        (10, True, True, "exact_duplicate"),
    ]
    assert audit(settings) == [(9, "exact_duplicate", 8), (10, "exact_duplicate", 8)]


def test_ac4_both_settings_give_identical_silver_and_audit_tables(load_with) -> None:
    rows = [line(8), line(9), line(10, OrderReference="O2"), line(11, OrderReference="O2")]
    seen = {}
    for exclude in (True, False):
        settings = with_flag(load_with, exclude)
        build(settings, rows)
        seen[exclude] = (
            state(settings),
            query(
                settings,
                "select _source_row, exclusion_reason, duplicate_of_source_row, "
                + ", ".join(SIX_AMOUNTS)
                + " from silver_excluded_rows order by _source_row",
            ),
        )
    assert seen[True] == seen[False]
    assert len(seen[True][1]) == 2, "the comparison must not be on empty tables"


def test_ac4_no_silver_sql_file_reads_the_setting() -> None:
    for path in SILVER_DIR.glob("*.sql"):
        assert "duplicates_exclude_from_net_sales" not in path.read_text(encoding="utf-8")


# The comparison columns come from config ------------------------------------------------


def test_the_key_columns_default_to_every_expected_column(load_with) -> None:
    settings = load_with({"ingest": {"expected_columns": EXPECTED, "sheets": ["RAW SCJ SALES"]}})
    assert settings.duplicate_key_columns == [c for c in EXPECTED if c != "_source_row"]


def test_explicit_key_columns_narrow_the_comparison(load_with) -> None:
    settings = load_with(
        {
            "ingest": {"expected_columns": EXPECTED, "sheets": ["RAW SCJ SALES"]},
            "duplicates": {"key_columns": ["OrderReference", "Customer"]},
        }
    )
    build(settings, [line(8, Net_Amount_2="1"), line(9, Net_Amount_2="2")])
    assert audit(settings) == [(9, "exact_duplicate", 8)]


def test_a_key_column_that_is_not_in_the_bronze_file_fails_the_build(load_with) -> None:
    settings = load_with(
        {
            "ingest": {"expected_columns": EXPECTED, "sheets": ["RAW SCJ SALES"]},
            "duplicates": {"key_columns": ["OrderReference", "No_Such_Column"]},
        }
    )
    write_bronze(settings, [line(8), line(9)])
    with pytest.raises(SilverError, match="No_Such_Column"):
        run_silver(settings)
    assert not settings.paths.warehouse.exists()


def test_an_empty_key_list_fails_the_build_with_a_clear_message(load_with) -> None:
    settings = load_with(
        {
            "ingest": {"expected_columns": EXPECTED, "sheets": ["RAW SCJ SALES"]},
            "duplicates": {"key_columns": []},
        }
    )
    write_bronze(settings, [line(8), line(9)])
    with pytest.raises(SilverError, match=r"duplicates\.key_columns"):
        run_silver(settings)


def test_changing_the_key_columns_in_config_needs_no_code_edit(load_with) -> None:
    rows = [line(8, Net_Amount_2="1"), line(9, Net_Amount_2="2")]
    wide = load_with(
        {"ingest": {"expected_columns": EXPECTED, "sheets": ["RAW SCJ SALES"]}}, name="w"
    )
    narrow = load_with(
        {
            "ingest": {"expected_columns": EXPECTED, "sheets": ["RAW SCJ SALES"]},
            "duplicates": {"key_columns": ["OrderReference"]},
        },
        name="n",
    )
    build(wide, rows)
    build(narrow, rows)
    assert audit(wide) == []
    assert audit(narrow) == [(9, "exact_duplicate", 8)]


# Interaction with the checks and the rest of the stage --------------------------------------


def test_every_bronze_row_still_has_a_silver_row(silver_settings: Settings) -> None:
    rows = [line(8), line(9), line(10), line(11, OrderReference="O2")]
    build(silver_settings, rows)
    assert query(silver_settings, "select count(*) from silver_sales") == [(len(rows),)]


def test_the_checks_pass_with_duplicates_present(silver_settings: Settings) -> None:
    build(silver_settings, [line(8), line(9), line(10)])  # would raise if a check failed
    assert query(
        silver_settings,
        "select (select count(*) from silver_excluded_rows), "
        "(select count(*) from silver_sales where is_excluded)",
    ) == [(2, 2)]


def test_a_copy_flagged_by_the_rule_has_no_stray_flag(silver_settings: Settings) -> None:
    build(silver_settings, [line(8), line(9)])
    assert query(
        silver_settings, "select count(*) filter (where f_stray_row) from silver_sales"
    ) == [(0,)]


def test_the_stage_runs_the_duplicate_rule_before_the_audit_table_and_the_checks() -> None:
    names = sorted(p.name for p in SILVER_DIR.glob("*.sql"))
    assert names == [
        "01_helpers.sql",
        "02_silver_sales.sql",
        "03_exclusions.sql",
        "04_duplicates.sql",
        "05_value_flags.sql",
        "06_void_flags.sql",
        "07_excluded_rows.sql",
        "08_customer_codes.sql",
        "99_checks.sql",
    ]


def test_the_build_is_repeatable_with_identical_content(silver_settings: Settings) -> None:
    rows = [line(8), line(9), line(10), line(11, OrderReference="O2")]
    build(silver_settings, rows)
    first = (state(silver_settings), audit(silver_settings))
    run_silver(silver_settings)
    assert (state(silver_settings), audit(silver_settings)) == first


def test_the_logs_carry_counts_and_no_values(
    silver_settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    write_bronze(
        silver_settings, [line(8, Customer="SECRET-CUSTOMER"), line(9, Customer="SECRET-CUSTOMER")]
    )
    with caplog.at_level(logging.DEBUG, logger="revint"):
        run_silver(silver_settings)
    assert "SECRET-CUSTOMER" not in caplog.text


# Real file: runs only when data/ exists ----------------------------------------------------


@pytest.mark.realdata
def test_ac1_real_file_has_the_documented_duplicate_count(tmp_path: Path) -> None:
    """Counts and structure only; no individual value is asserted or printed."""
    import duckdb

    settings = load_settings(env={"REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb")})
    if not list(settings.paths.bronze.glob("*__RAW_SCJ_SALES.parquet")):
        pytest.skip("bronze not built: run `uv run revint build bronze` first")
    run_silver(settings)
    con = duckdb.connect(str(settings.paths.warehouse), read_only=True)
    try:
        dups, excluded, audit_rows, strays, total = con.execute(
            "select count(*) filter (where is_duplicate), count(*) filter (where is_excluded), "
            "(select count(*) from silver_excluded_rows), count(*) filter (where f_stray_row), "
            "count(*) from silver_sales"
        ).fetchone()
        assert total == 662_128
        assert dups == 556, "the profiling count (spec 01 S5 documents about 556)"
        assert strays == 1
        assert excluded == audit_rows == dups + strays
        by_reason = dict(
            con.execute(
                "select exclusion_reason, count(*) from silver_sales where is_excluded group by 1"
            ).fetchall()
        )
        assert by_reason == {"exact_duplicate": 556, "stray_row": 1}
        orphans = con.execute(
            "select count(*) from silver_excluded_rows e left join silver_sales s "
            "on s._source_row = e.duplicate_of_source_row "
            "where e.exclusion_reason = 'exact_duplicate' "
            "and (s._source_row is null or s.is_excluded)"
        ).fetchone()[0]
        assert orphans == 0, "every copy points at a kept first occurrence"
    finally:
        con.close()
