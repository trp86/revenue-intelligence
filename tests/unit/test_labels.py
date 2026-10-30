"""Story #37: label normalisation (spec 01 S3).

Synthetic bronze data only. The real-file test is marked `realdata` and asserts counts, never
a label value. Channel labels come from `Channel_Category`, branch labels from `Branch_Name`.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from silver_helpers import (
    COLUMN_TYPES_SQL,
    EXPECTED,
    bronze_row,
    build,
    query,
    silver_columns,
    write_bronze,
)

from revint.config import Settings, load_settings
from revint.silver import SILVER_DIR, SilverError, run_silver

CHANNEL = "Channel_Category"
BRANCH = "Branch_Name"


def settings_with(load_with, name: str = "cfg", **labels: object) -> Settings:
    extra: dict = {"ingest": {"expected_columns": EXPECTED, "sheets": ["RAW SCJ SALES"]}}
    if labels:
        extra["labels"] = labels
    return load_with(extra, name=name)


@pytest.fixture
def mapped(load_with) -> Settings:
    return settings_with(
        load_with,
        channel_map={"MODERN TRADE": "Modern Trade", "MT": "Modern Trade"},
        branch_map={"MAGWAY": "Magway", "Hpa-an": "Hpa-An"},
    )


def line(source_row: int, channel: str | None, branch: str | None = "Yangon", **cells):
    """An order line made different from every other by its order reference, so the duplicate
    rule never fires and the label rule is what is under test."""
    base = {"OrderReference": f"O{source_row}", CHANNEL: channel, BRANCH: branch}
    base.update(cells)
    return bronze_row(source_row, **base)


def labels(settings: Settings, source_row: int) -> tuple:
    return query(
        settings,
        'select "Channel_Category", "Channel_Category_normalised", "Branch_Name", '
        '"Branch_Name_normalised", f_unmapped_label, is_excluded '
        "from silver_sales where _source_row = ?",
        source_row,
    )[0]


# AC1: a mapped label is normalised from the map, and the original is kept ----------


def test_ac1_a_mapped_channel_label_is_normalised_and_the_original_is_kept(mapped) -> None:
    build(mapped, [line(8, "MT"), line(9, "MODERN TRADE")])
    for row, original in ((8, "MT"), (9, "MODERN TRADE")):
        got = labels(mapped, row)
        assert (got[0], got[1]) == (original, "Modern Trade")


def test_ac1_a_mapped_branch_label_is_normalised_and_the_original_is_kept(mapped) -> None:
    build(mapped, [line(8, "GT", "MAGWAY"), line(9, "GT", "Hpa-an")])
    assert labels(mapped, 8)[2:4] == ("MAGWAY", "Magway")
    assert labels(mapped, 9)[2:4] == ("Hpa-an", "Hpa-An")


def test_ac1_the_original_columns_are_never_changed(mapped) -> None:
    values = [("MT", "MAGWAY"), ("GT", "Yangon"), (None, None), ("  ", " x ")]
    build(mapped, [line(8 + i, c, b) for i, (c, b) in enumerate(values)])
    got = query(
        mapped, 'select "Channel_Category", "Branch_Name" from silver_sales order by _source_row'
    )
    assert got == values


def test_ac1_matching_ignores_spaces_at_both_ends_but_the_original_keeps_them(mapped) -> None:
    build(mapped, [line(8, " MT "), line(9, "MT\t"), line(10, " MT")])
    for row in (8, 9, 10):
        assert labels(mapped, row)[1] == "Modern Trade"
    assert labels(mapped, 8)[0] == " MT "


def test_ac1_matching_is_exact_and_case_sensitive(mapped) -> None:
    build(mapped, [line(8, "mt"), line(9, "Mt"), line(10, "Modern trade")])
    for row in (8, 9, 10):
        got = labels(mapped, row)
        assert got[1] == got[0], "an unlisted spelling is kept as it is"


def test_ac1_the_normalised_value_comes_from_the_map_not_from_the_code(load_with) -> None:
    settings = settings_with(load_with, channel_map={"MT": "A very different name"})
    build(settings, [line(8, "MT")])
    assert labels(settings, 8)[1] == "A very different name"


def test_ac1_each_listed_column_gets_its_own_normalised_twin(load_with) -> None:
    settings = settings_with(
        load_with,
        channel_columns=["Channel_Category", "Channel_Type"],
        channel_map={"MT": "Modern Trade"},
    )
    rows = [line(8, "MT", Channel_Type="MT"), line(9, "GT", Channel_Type="MT")]
    build(settings, rows)
    got = query(
        settings,
        'select _source_row, "Channel_Category_normalised", "Channel_Type_normalised" '
        "from silver_sales order by 1",
    )
    assert got == [(8, "Modern Trade", "Modern Trade"), (9, "GT", "Modern Trade")]


def test_ac1_the_twin_columns_are_text_and_the_flag_is_boolean(mapped) -> None:
    build(mapped, [line(8, "MT")])
    types = dict(query(mapped, COLUMN_TYPES_SQL))
    assert types["Channel_Category_normalised"] == "VARCHAR"
    assert types["Branch_Name_normalised"] == "VARCHAR"
    assert types["f_unmapped_label"] == "BOOLEAN"


def test_ac1_a_label_that_maps_to_itself_is_mapped(load_with) -> None:
    settings = settings_with(load_with, channel_map={"GT": "GT"}, branch_map={"Yangon": "Yangon"})
    build(settings, [line(8, "GT", "Yangon")])
    assert labels(settings, 8)[1] == "GT" and labels(settings, 8)[4] is False


# AC2: an unmapped label is kept as it is and flagged ----------


def test_ac2_an_unmapped_label_is_kept_as_it_is_and_flagged(mapped) -> None:
    build(mapped, [line(8, "GT", "MAGWAY")])
    got = labels(mapped, 8)
    assert (got[0], got[1]) == ("GT", "GT")
    assert got[4] is True


def test_ac2_the_flag_is_true_when_any_listed_column_is_unmapped(mapped) -> None:
    build(
        mapped,
        [
            line(8, "MT", "MAGWAY"),  # both mapped
            line(9, "MT", "Yangon"),  # branch unmapped
            line(10, "GT", "MAGWAY"),  # channel unmapped
            line(11, "GT", "Yangon"),  # both unmapped
        ],
    )
    assert [labels(mapped, r)[4] for r in (8, 9, 10, 11)] == [False, True, True, True]


def test_ac2_a_blank_label_is_not_unmapped(mapped) -> None:
    build(mapped, [line(8, None, None), line(9, "", "  "), line(10, "MT", None)])
    assert [labels(mapped, r)[4] for r in (8, 9, 10)] == [False, False, False]


def test_ac2_a_blank_label_is_kept_as_it_is(mapped) -> None:
    build(mapped, [line(8, None, "  ")])
    got = labels(mapped, 8)
    assert got[1] is None and got[3] == "  "


def test_ac2_with_empty_maps_every_non_blank_label_is_unmapped(load_with) -> None:
    settings = settings_with(load_with)
    build(settings, [line(8, "GT", "Yangon"), line(9, None, None), line(10, "MT", None)])
    assert [labels(settings, r)[4] for r in (8, 9, 10)] == [True, False, True]
    assert labels(settings, 8)[1] == "GT" and labels(settings, 8)[3] == "Yangon"


def test_ac2_the_flag_is_never_null(mapped) -> None:
    build(mapped, [line(8, "MT"), line(9, None, None), line(10, "x", "y")])
    assert query(
        mapped, "select count(*) filter (where f_unmapped_label is null) from silver_sales"
    ) == [(0,)]


def test_ac2_an_unmapped_label_is_never_guessed(mapped) -> None:
    build(mapped, [line(8, "Modern Trade"), line(9, "M T")])
    # "Modern Trade" is already the canonical name but is not a key, so it is not "mapped"
    assert labels(mapped, 8)[1] == "Modern Trade" and labels(mapped, 8)[4] is True
    assert labels(mapped, 9)[1] == "M T"


def test_ac2_the_flag_never_excludes_a_row(mapped) -> None:
    build(mapped, [line(8, "GT"), line(9, "xx")])
    assert query(mapped, "select count(*) filter (where is_excluded) from silver_sales") == [(0,)]
    assert query(mapped, "select count(*) from silver_excluded_rows") == [(0,)]
    assert query(mapped, "select count(*) from silver_sales") == [(2,)]


# AC3: changing a map changes the output with no code edit ----------


def test_ac3_a_changed_map_changes_the_output(load_with) -> None:
    rows = [line(8, "MT"), line(9, "GT")]
    one = settings_with(load_with, name="one", channel_map={"MT": "Modern Trade"})
    two = settings_with(load_with, name="two", channel_map={"MT": "Supermarket", "GT": "General"})
    build(one, rows)
    build(two, rows)
    assert [labels(one, r)[1] for r in (8, 9)] == ["Modern Trade", "GT"]
    assert [labels(two, r)[1] for r in (8, 9)] == ["Supermarket", "General"]
    assert [labels(one, r)[4] for r in (8, 9)] == [True, True]  # branch Yangon is unmapped
    assert [labels(two, r)[4] for r in (8, 9)] == [True, True]


def test_ac3_a_changed_column_list_changes_which_columns_are_normalised(load_with) -> None:
    rows = [line(8, "GT", "MAGWAY", Channel_Type="MT")]
    channel_type = settings_with(
        load_with, name="a", channel_columns=["Channel_Type"], channel_map={"MT": "Modern Trade"}
    )
    build(channel_type, rows)
    names = silver_columns(channel_type)
    assert "Channel_Type_normalised" in names and "Channel_Category_normalised" not in names


def test_ac3_a_map_key_with_a_quote_is_data_not_sql(load_with) -> None:
    key = "a'; drop table silver_sales; --"
    settings = settings_with(load_with, channel_map={key: "Safe"})
    build(settings, [line(8, key), line(9, "other")])
    assert labels(settings, 8)[1] == "Safe"
    assert query(settings, "select count(*) from silver_sales") == [(2,)]


def test_ac3_a_map_key_with_special_characters_matches(load_with) -> None:
    key = "Café (A/B) 100%"
    settings = settings_with(load_with, channel_map={key: "Cafe"})
    build(settings, [line(8, key)])
    assert labels(settings, 8)[1] == "Cafe"


def test_ac3_no_silver_sql_file_hard_codes_a_label_column_or_value() -> None:
    text = (SILVER_DIR / "07_label_normalisation.sql").read_text(encoding="utf-8")
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("--"))
    for forbidden in ("Channel_Category", "Branch_Name", "Modern Trade", "MAGWAY"):
        assert forbidden not in code, forbidden
    for parameter in (
        "$labels_channel_columns",
        "$labels_branch_columns",
        "$labels_channel_map_keys",
        "$labels_branch_map_values",
    ):
        assert parameter in text, parameter


# The build guards ----------


def test_a_label_column_that_is_typed_is_refused(load_with) -> None:
    settings = settings_with(load_with, channel_columns=["Date"])
    write_bronze(settings, [line(8, "MT")])
    with pytest.raises(SilverError, match=r"labels\.channel_columns.*Date"):
        run_silver(settings)


def test_a_column_in_both_lists_is_refused(load_with) -> None:
    settings = settings_with(load_with, channel_columns=["Region"], branch_columns=["Region"])
    write_bronze(settings, [line(8, "MT")])
    with pytest.raises(SilverError, match=r"labels.*Region"):
        run_silver(settings)


def test_a_label_column_missing_from_the_bronze_file_fails_the_build(load_with) -> None:
    settings = settings_with(load_with)
    write_bronze(settings, [line(8, "MT")])
    path = next(settings.paths.bronze.glob("*.parquet"))
    import polars as pl

    pl.read_parquet(path).drop("Channel_Category").write_parquet(path)
    with pytest.raises(SilverError, match="Channel_Category"):
        run_silver(settings)


# The stage and the rest of silver ----------


def test_the_stage_runs_the_label_rule_before_the_tables_built_from_silver() -> None:
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


def test_every_row_and_every_earlier_column_survives_the_rebuild(mapped) -> None:
    rows = [line(8 + i, "MT" if i % 2 else "GT") for i in range(6)]
    build(mapped, rows)
    assert query(mapped, "select count(*) from silver_sales") == [(6,)]
    names = silver_columns(mapped)
    for expected in (
        "is_excluded",
        "void_flag",
        "f_zero_value_with_qty",
        "duplicate_of_source_row",
    ):
        assert expected in names


def test_the_earlier_flags_keep_their_values_after_the_rebuild(mapped) -> None:
    same = {
        "OrderReference": "O1",
        CHANNEL: "MT",
        BRANCH: "MAGWAY",
        "Net_Amount_2": "0",
        "Quantity(PCS)": "3",
    }
    build(mapped, [bronze_row(8, **same), bronze_row(9, **same), bronze_row(10, Change_to_Ctn="1")])
    got = query(
        mapped,
        "select _source_row, is_excluded, exclusion_reason, f_zero_value_with_qty, f_stray_row "
        "from silver_sales order by 1",
    )
    assert got == [
        (8, False, None, True, False),
        (9, True, "exact_duplicate", True, False),
        (10, True, "stray_row", False, True),
    ]
    assert query(mapped, "select count(*) from silver_excluded_rows") == [(2,)]


def test_a_duplicate_pair_gets_the_same_normalised_label(mapped) -> None:
    same = {"OrderReference": "O1", CHANNEL: "MT", BRANCH: "MAGWAY"}
    build(mapped, [bronze_row(8, **same), bronze_row(9, **same)])
    assert {labels(mapped, r)[1] for r in (8, 9)} == {"Modern Trade"}


def test_the_customer_table_is_unaffected_by_the_label_rule(mapped) -> None:
    build(
        mapped,
        [line(8, "MT", "MAGWAY", CustomerCode="C1"), line(9, "GT", "Yangon", CustomerCode="C1")],
    )
    assert query(
        mapped, "select customer_code, order_lines, branch_count from silver_customer_codes"
    ) == [("C1", 2, 2)]


def test_the_build_is_repeatable_with_identical_content(mapped) -> None:
    build(mapped, [line(8, "MT"), line(9, "GT", "MAGWAY"), line(10, None, None)])
    sql = (
        'select _source_row, "Channel_Category_normalised", "Branch_Name_normalised", '
        "f_unmapped_label from silver_sales order by 1"
    )
    first = query(mapped, sql)
    run_silver(mapped)
    assert query(mapped, sql) == first


def test_the_logs_carry_counts_and_no_labels(mapped, caplog: pytest.LogCaptureFixture) -> None:
    write_bronze(mapped, [line(8, "SECRET-CHANNEL", "SECRET-BRANCH")])
    with caplog.at_level(logging.DEBUG, logger="revint"):
        run_silver(mapped)
    assert "SECRET" not in caplog.text


# Real file: runs only when data/ exists ----------


@pytest.mark.realdata
def test_ac1_real_file_label_counts_match_an_independent_count(tmp_path: Path) -> None:
    """Counts only. The expected figures are counted straight from bronze, not from silver."""
    import duckdb

    settings = load_settings(env={"REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb")})
    bronze = list(settings.paths.bronze.glob("*__RAW_SCJ_SALES.parquet"))
    if not bronze:
        pytest.skip("bronze not built: run `uv run revint build bronze` first")
    run_silver(settings)
    con = duckdb.connect(str(settings.paths.warehouse), read_only=True)
    try:
        channel_keys = list(settings.labels.channel_map)
        branch_keys = list(settings.labels.branch_map)
        independent = con.execute(
            "select count(*) filter (where "
            "(trim(coalesce(\"Channel_Category\", '')) <> '' "
            'and trim("Channel_Category") not in (select unnest(?::varchar[]))) '
            "or (trim(coalesce(\"Branch_Name\", '')) <> '' "
            'and trim("Branch_Name") not in (select unnest(?::varchar[])))), '
            'count(*) filter (where trim("Channel_Category") in (select unnest(?::varchar[]))), '
            'count(*) filter (where trim("Branch_Name") in (select unnest(?::varchar[]))) '
            "from read_parquet(?)",
            [channel_keys, branch_keys, channel_keys, branch_keys, bronze[0].as_posix()],
        ).fetchone()
        unmapped, mapped_channel, mapped_branch = independent
        got = con.execute(
            "select count(*) filter (where f_unmapped_label), "
            'count(*) filter (where "Channel_Category_normalised" <> "Channel_Category"), '
            'count(*) filter (where "Branch_Name_normalised" <> "Branch_Name"), count(*), '
            "count(*) filter (where f_unmapped_label is null) from silver_sales"
        ).fetchone()
        assert got[0] == unmapped
        assert got[1] == mapped_channel == 532, "profiling: MODERN TRADE 348 + MT 184"
        assert got[2] == mapped_branch == 2422, (
            "profiling: MAGWAY 1534, Hpa-an 700, PyinooLwin 184, PYAY 3, DAWEI 1"
        )
        assert got[3] == 662_128 and got[4] == 0
    finally:
        con.close()
