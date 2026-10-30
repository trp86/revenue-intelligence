"""Story #35: void flags (spec 01 S6, decision D3, provisional).

Synthetic bronze data only. The real-file test is marked `realdata` and asserts counts, never
individual values (the Void values themselves are listed in the profiling on #31).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from silver_helpers import COLUMN_TYPES_SQL, EXPECTED, bronze_row, build, query, write_bronze

from revint.config import ConfigError, Settings, load_settings
from revint.silver import SILVER_DIR, SilverError, run_silver

VOID = "Void"


def settings_with(load_with, name: str = "cfg", **void: object) -> Settings:
    extra: dict = {"ingest": {"expected_columns": EXPECTED, "sheets": ["RAW SCJ SALES"]}}
    if void:
        extra["void"] = void
    return load_with(extra, name=name)


@pytest.fixture
def silver_settings(load_with) -> Settings:
    return settings_with(load_with)


def line(source_row: int, void: str | None, **cells: str | None):
    """An order line made different from every other by its order reference, so the duplicate
    rule never fires and the void flags are what is under test."""
    base = {"OrderReference": f"O{source_row}", VOID: void}
    base.update(cells)
    return bronze_row(source_row, **base)


def void_state(settings: Settings, source_row: int) -> tuple:
    return query(
        settings,
        'select void_flag, f_blank_void, f_unmapped_void, "Void", is_excluded '
        "from silver_sales where _source_row = ?",
        source_row,
    )[0]


# AC1: a blank Void -> void_flag 0, f_blank_void true, the original Void column unchanged --------


@pytest.mark.parametrize("blank", [None, "", " ", "   ", "\t", " "])
def test_ac1_a_blank_void_is_not_void_and_flagged_blank(
    silver_settings: Settings, blank: str | None
) -> None:
    build(silver_settings, [line(8, blank)])
    flag, f_blank, f_unmapped, original, excluded = void_state(silver_settings, 8)
    assert (flag, f_blank, f_unmapped, excluded) == (0, True, False, False)
    assert original == blank, "the original Void column is unchanged"


def test_ac1_the_original_void_column_is_never_modified_for_any_value(
    silver_settings: Settings,
) -> None:
    values = [None, "", "  ", "Unvoid", " Unvoid ", "VOID", "x"]
    build(silver_settings, [line(8 + i, v) for i, v in enumerate(values)])
    got = query(silver_settings, 'select "Void" from silver_sales order by _source_row')
    assert [row[0] for row in got] == values


def test_ac1_f_blank_void_is_false_when_the_cell_has_a_value(silver_settings: Settings) -> None:
    build(silver_settings, [line(8, "Unvoid")])
    assert void_state(silver_settings, 8)[1] is False


def test_ac1_blank_means_void_sets_void_flag_one_when_configured(load_with) -> None:
    settings = settings_with(load_with, blank_means="void")
    build(settings, [line(8, None), line(9, "")])
    assert [void_state(settings, r)[:2] for r in (8, 9)] == [(1, True), (1, True)]


def test_ac1_blank_means_not_void_is_the_default(silver_settings: Settings) -> None:
    assert silver_settings.void.blank_means == "not_void"


def test_ac1_f_blank_void_stays_true_whichever_way_blank_is_read(load_with) -> None:
    for number, mode in enumerate(("not_void", "void")):
        settings = settings_with(load_with, name=f"m{number}", blank_means=mode)
        build(settings, [line(8, None)])
        assert void_state(settings, 8)[1] is True


# AC2: a mapped non-blank value -> void_flag from void.value_map ----------


def test_ac2_a_mapped_value_takes_its_flag_from_the_map(load_with) -> None:
    settings = settings_with(load_with, value_map={"Voided": 1, "Unvoid": 0})
    build(settings, [line(8, "Voided"), line(9, "Unvoid")])
    assert void_state(settings, 8)[:3] == (1, False, False)
    assert void_state(settings, 9)[:3] == (0, False, False)


def test_ac2_the_map_is_exact_and_case_sensitive(load_with) -> None:
    settings = settings_with(load_with, value_map={"Voided": 1})
    build(settings, [line(8, "Voided"), line(9, "voided"), line(10, "VOIDED")])
    assert [void_state(settings, r)[0] for r in (8, 9, 10)] == [1, None, None]


def test_ac2_surrounding_spaces_do_not_stop_a_value_from_matching(load_with) -> None:
    settings = settings_with(load_with, value_map={"Voided": 1})
    build(settings, [line(8, " Voided"), line(9, "Voided\t"), line(10, " Voided ")])
    assert [void_state(settings, r)[:3] for r in (8, 9, 10)] == [(1, False, False)] * 3
    assert void_state(settings, 8)[3] == " Voided", "the original text is kept"


def test_ac2_a_map_key_with_special_characters_matches(load_with) -> None:
    settings = settings_with(load_with, value_map={"Void'd (yes) / é": 1})
    build(settings, [line(8, "Void'd (yes) / é")])
    assert void_state(settings, 8)[:3] == (1, False, False)


def test_ac2_changing_the_map_changes_the_flags_with_no_code_edit(load_with) -> None:
    rows = [line(8, "A"), line(9, "B")]
    one = settings_with(load_with, name="one", value_map={"A": 1, "B": 0})
    two = settings_with(load_with, name="two", value_map={"A": 0, "B": 1})
    build(one, rows)
    build(two, rows)
    assert [void_state(one, r)[0] for r in (8, 9)] == [1, 0]
    assert [void_state(two, r)[0] for r in (8, 9)] == [0, 1]


def test_ac2_a_mapped_flag_of_zero_is_not_void(load_with) -> None:
    settings = settings_with(load_with, value_map={"Unvoid": 0})
    build(settings, [line(8, "Unvoid")])
    assert void_state(settings, 8)[0] == 0


def test_ac2_a_blank_is_decided_by_blank_means_never_by_the_map(load_with) -> None:
    settings = settings_with(load_with, value_map={"": 1, " ": 1})
    build(settings, [line(8, ""), line(9, None)])
    assert [void_state(settings, r)[:2] for r in (8, 9)] == [(0, True), (0, True)]


# AC3: a non-blank value with no mapping -> void_flag NULL, f_unmapped_void true ----------


def test_ac3_an_unmapped_value_gives_a_null_flag_and_the_unmapped_mark(
    silver_settings: Settings,
) -> None:
    build(silver_settings, [line(8, "Unvoid")])
    assert void_state(silver_settings, 8)[:3] == (None, False, True)


def test_ac3_with_the_default_empty_map_every_non_blank_value_is_unmapped(
    silver_settings: Settings,
) -> None:
    build(silver_settings, [line(8, "Unvoid"), line(9, "Voided"), line(10, "x"), line(11, None)])
    got = query(
        silver_settings,
        "select count(*) filter (where f_unmapped_void), "
        "count(*) filter (where void_flag is null), "
        "count(*) filter (where f_blank_void) from silver_sales",
    )
    assert got == [(3, 3, 1)]


def test_ac3_a_value_missing_from_a_non_empty_map_is_still_unmapped(load_with) -> None:
    settings = settings_with(load_with, value_map={"Voided": 1})
    build(settings, [line(8, "Voided"), line(9, "Other")])
    assert void_state(settings, 8)[:3] == (1, False, False)
    assert void_state(settings, 9)[:3] == (None, False, True)


def test_ac3_an_unmapped_value_is_never_guessed_as_zero_or_one(silver_settings: Settings) -> None:
    build(silver_settings, [line(8, "0"), line(9, "1"), line(10, "false"), line(11, "yes")])
    flags = query(silver_settings, "select void_flag from silver_sales order by _source_row")
    assert flags == [(None,)] * 4


def test_ac3_the_unmapped_values_are_reported_as_counts_only(silver_settings: Settings) -> None:
    build(silver_settings, [line(8 + i, "Unvoid") for i in range(5)])
    got = query(
        silver_settings,
        "select count(*) from silver_sales where f_unmapped_void",
    )
    assert got == [(5,)]


# AC4: void_flag = 1 does not set is_excluded ----------


def test_ac4_a_voided_line_is_not_excluded(load_with) -> None:
    settings = settings_with(load_with, value_map={"Voided": 1})
    build(settings, [line(8, "Voided"), line(9, "Voided", OrderReference="O9")])
    assert query(
        settings,
        "select count(*) filter (where void_flag = 1), count(*) filter (where is_excluded) "
        "from silver_sales",
    ) == [(2, 0)]
    assert query(settings, "select count(*) from silver_excluded_rows") == [(0,)]
    assert query(settings, "select count(*) from silver_sales") == [(2,)]


def test_ac4_blank_means_void_does_not_exclude_either(load_with) -> None:
    settings = settings_with(load_with, blank_means="void")
    build(settings, [line(8, None), line(9, "")])
    assert query(settings, "select count(*) filter (where is_excluded) from silver_sales") == [(0,)]


def test_ac4_an_unmapped_value_does_not_exclude(silver_settings: Settings) -> None:
    build(silver_settings, [line(8, "Unvoid")])
    assert void_state(silver_settings, 8)[4] is False


def test_ac4_voided_values_stay_in_the_amount_columns(load_with) -> None:
    settings = settings_with(load_with, value_map={"Voided": 1})
    build(settings, [line(8, "Voided", Net_Amount_2="12.5")])
    from decimal import Decimal

    assert query(settings, "select Net_Amount_2 from silver_sales") == [(Decimal("12.5000"),)]


def test_ac4_the_void_rule_never_sets_an_exclusion_reason() -> None:
    text = (SILVER_DIR / "06_void_flags.sql").read_text(encoding="utf-8")
    lowered = text.lower()
    assert "is_excluded" not in lowered and "exclusion_reason" not in lowered


# The void flag columns ----------


def test_the_void_columns_have_the_declared_types(silver_settings: Settings) -> None:
    build(silver_settings, [line(8, "x")])
    types = dict(query(silver_settings, COLUMN_TYPES_SQL))
    assert types["void_flag"] == "TINYINT"
    assert types["f_blank_void"] == "BOOLEAN"
    assert types["f_unmapped_void"] == "BOOLEAN"


def test_the_two_boolean_flags_are_never_null(silver_settings: Settings) -> None:
    build(silver_settings, [line(8, None), line(9, "x"), line(10, "")])
    nulls = query(
        silver_settings,
        "select count(*) filter (where f_blank_void is null), "
        "count(*) filter (where f_unmapped_void is null) from silver_sales",
    )
    assert nulls == [(0, 0)]


def test_a_blank_row_is_blank_void_not_unmapped(silver_settings: Settings) -> None:
    build(silver_settings, [bronze_row(8)])
    assert void_state(silver_settings, 8)[:3] == (0, True, False)


def test_the_stray_row_has_a_blank_void(silver_settings: Settings) -> None:
    build(silver_settings, [line(8, "x"), bronze_row(9, Change_to_Ctn="1")])
    assert void_state(silver_settings, 9)[:3] == (0, True, False)


def test_a_void_value_that_is_also_a_duplicate_keeps_both_marks(load_with) -> None:
    settings = settings_with(load_with, value_map={"Voided": 1})
    same = {"OrderReference": "O1", VOID: "Voided"}
    build(settings, [bronze_row(8, **same), bronze_row(9, **same)])
    got = query(
        settings,
        "select _source_row, void_flag, is_duplicate, is_excluded from silver_sales order by 1",
    )
    assert got == [(8, 1, False, False), (9, 1, True, True)]


# The configuration ----------


def test_the_value_map_is_bound_as_parameters_not_pasted_into_the_sql(load_with) -> None:
    text = (SILVER_DIR / "06_void_flags.sql").read_text(encoding="utf-8")
    assert "$void_value_map_keys" in text and "$void_value_map_values" in text
    assert "$void_blank_means" in text


def test_a_value_map_flag_other_than_zero_or_one_still_fails_at_load_time(load_with) -> None:
    with pytest.raises(ConfigError, match=r"void\.value_map"):
        settings_with(load_with, value_map={"x": 2})


def test_a_map_key_with_a_quote_does_not_break_the_sql(load_with) -> None:
    settings = settings_with(load_with, value_map={"a'; drop table silver_sales; --": 1})
    build(settings, [line(8, "a'; drop table silver_sales; --"), line(9, "other")])
    assert void_state(settings, 8)[:3] == (1, False, False)
    assert query(settings, "select count(*) from silver_sales") == [(2,)]


def test_the_stage_runs_the_void_flags_before_the_audit_table() -> None:
    names = sorted(p.name for p in SILVER_DIR.glob("*.sql"))
    assert names == [
        "01_helpers.sql",
        "02_silver_sales.sql",
        "03_exclusions.sql",
        "04_duplicates.sql",
        "05_value_flags.sql",
        "06_void_flags.sql",
        "07_excluded_rows.sql",
        "99_checks.sql",
    ]


def test_the_build_is_repeatable_with_identical_content(load_with) -> None:
    settings = settings_with(load_with, value_map={"Voided": 1})
    build(settings, [line(8, "Voided"), line(9, None), line(10, "x")])
    sql = (
        "select _source_row, void_flag, f_blank_void, f_unmapped_void from silver_sales order by 1"
    )
    first = query(settings, sql)
    run_silver(settings)
    assert query(settings, sql) == first


def test_a_void_column_that_is_missing_from_the_bronze_file_fails_the_build(load_with) -> None:
    settings = settings_with(load_with)
    write_bronze(settings, [line(8, "x")])
    path = next(settings.paths.bronze.glob("*.parquet"))
    import polars as pl

    pl.read_parquet(path).drop("Void").write_parquet(path)
    with pytest.raises(SilverError, match="Void"):
        run_silver(settings)


def test_the_logs_carry_counts_and_no_values(
    silver_settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    write_bronze(silver_settings, [line(8, "SECRET-VOID-VALUE")])
    with caplog.at_level(logging.DEBUG, logger="revint"):
        run_silver(silver_settings)
    assert "SECRET-VOID-VALUE" not in caplog.text


# Real file: runs only when data/ exists ----------


@pytest.mark.realdata
def test_ac1_real_file_void_counts_match_the_profiling(tmp_path: Path) -> None:
    """Counts only. The distinct Void values and counts were reported by the profiler (#31)."""
    import duckdb

    settings = load_settings(env={"REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb")})
    if not list(settings.paths.bronze.glob("*__RAW_SCJ_SALES.parquet")):
        pytest.skip("bronze not built: run `uv run revint build bronze` first")
    run_silver(settings)
    con = duckdb.connect(str(settings.paths.warehouse), read_only=True)
    try:
        blank, unmapped, voided, notvoid, null_flag, total, excluded = con.execute(
            "select count(*) filter (where f_blank_void), count(*) filter (where f_unmapped_void), "
            "count(*) filter (where void_flag = 1), count(*) filter (where void_flag = 0), "
            "count(*) filter (where void_flag is null), count(*), "
            "count(*) filter (where is_excluded) from silver_sales"
        ).fetchone()
        assert total == 662_128
        assert blank == 28_034, "profiling #31: 28,033 blank Void values plus the stray row"
        assert unmapped == 634_094, "profiling #31: the non-blank Void value, unmapped by default"
        assert (voided, notvoid, null_flag) == (0, 28_034, 634_094)
        assert excluded == 557, "void flags exclude nothing"
        assert blank + unmapped == total
    finally:
        con.close()
