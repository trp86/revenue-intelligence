"""Story #40: the customer-code table (spec 01 S4, FR-D1; customer identity is an open question).

Synthetic bronze data only. The real-file test is marked `realdata` and asserts counts, never
a customer code or name.
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
    run_custom_stage,
    write_bronze,
)

from revint.config import Settings, load_settings
from revint.pipeline import StageError
from revint.silver import SILVER_DIR, SilverError, run_silver

CODE = "CustomerCode"
NAME = "Customer"
BRANCH = "Branch_Name"


@pytest.fixture
def silver_settings(load_with) -> Settings:
    return load_with({"ingest": {"expected_columns": EXPECTED, "sheets": ["RAW SCJ SALES"]}})


def line(source_row: int, code: str | None, name: str | None = "N", branch: str | None = "B", **c):
    """An order line made different from every other by its order reference, so the duplicate
    rule never fires unless a test wants it to."""
    cells = {"OrderReference": f"O{source_row}", CODE: code, NAME: name, BRANCH: branch}
    cells.update(c)
    return bronze_row(source_row, **cells)


def table(settings: Settings) -> list[tuple]:
    return query(
        settings,
        "select customer_code, order_lines, name_count, branch_count, near_duplicate_count, "
        "f_multiple_names, f_multiple_branches from silver_customer_codes order by customer_code",
    )


# AC1: one row per code with counts of distinct names and branches ----------


def test_ac1_one_row_per_code_with_the_counts(silver_settings: Settings) -> None:
    rows = [
        line(8, "C1", "Anna", "North"),
        line(9, "C1", "Anna", "North"),
        line(10, "C1", "Anne", "South"),  # a second spelling and a second branch
        line(11, "C2", "Bob", "North"),
        line(12, "C3", "Cy", "East"),
        line(13, "C3", "Cy", "East"),
    ]
    build(silver_settings, rows)
    assert table(silver_settings) == [
        ("C1", 3, 2, 2, 0, True, True),
        ("C2", 1, 1, 1, 0, False, False),
        ("C3", 2, 1, 1, 0, False, False),
    ]


def test_ac1_the_row_count_is_the_number_of_distinct_codes(silver_settings: Settings) -> None:
    rows = [line(8 + i, f"C{i % 4}") for i in range(12)]
    build(silver_settings, rows)
    assert query(silver_settings, "select count(*) from silver_customer_codes") == [(4,)]
    assert query(
        silver_settings, "select count(distinct customer_code) from silver_customer_codes"
    ) == [(4,)]


def test_ac1_a_name_that_differs_by_case_or_a_space_is_another_spelling(
    silver_settings: Settings,
) -> None:
    rows = [
        line(8, "C1", "Anna"),
        line(9, "C1", "ANNA"),
        line(10, "C1", "Anna "),
        line(11, "C1", " Anna"),
    ]
    build(silver_settings, rows)
    assert table(silver_settings)[0][2] == 4


def test_ac1_blank_names_and_branches_are_not_counted(silver_settings: Settings) -> None:
    rows = [
        line(8, "C1", "Anna", "North"),
        line(9, "C1", None, None),
        line(10, "C1", "", ""),
        line(11, "C1", "   ", "\t"),
    ]
    build(silver_settings, rows)
    assert table(silver_settings) == [("C1", 4, 1, 1, 0, False, False)]


def test_ac1_a_code_with_no_name_at_all_has_a_zero_count(silver_settings: Settings) -> None:
    build(silver_settings, [line(8, "C1", None, "North")])
    assert table(silver_settings) == [("C1", 1, 0, 1, 0, False, False)]


@pytest.mark.parametrize("blank", [None, "", " ", "  ", "\t", " "])
def test_ac1_rows_with_a_blank_code_get_no_row(
    silver_settings: Settings, blank: str | None
) -> None:
    build(silver_settings, [line(8, "C1"), line(9, blank)])
    assert [r[0] for r in table(silver_settings)] == ["C1"]
    assert query(silver_settings, "select count(*) from silver_sales") == [(2,)]


def test_ac1_order_lines_count_the_kept_rows_not_the_excluded_copies(
    silver_settings: Settings,
) -> None:
    same = {"OrderReference": "O1", CODE: "C1", NAME: "Anna", BRANCH: "North"}
    build(
        silver_settings,
        [bronze_row(8, **same), bronze_row(9, **same), line(10, "C1", "Anna", "North")],
    )
    assert query(
        silver_settings, "select count(*) filter (where is_duplicate) from silver_sales"
    ) == [(1,)]
    assert table(silver_settings) == [("C1", 2, 1, 1, 0, False, False)]


def test_ac1_the_stray_row_adds_no_customer(silver_settings: Settings) -> None:
    build(silver_settings, [line(8, "C1"), bronze_row(9, Change_to_Ctn="1")])
    assert [r[0] for r in table(silver_settings)] == ["C1"]


def test_ac1_the_flags_follow_the_counts(silver_settings: Settings) -> None:
    build(
        silver_settings,
        [line(8, "C1", "A", "X"), line(9, "C1", "B", "X"), line(10, "C2", "A", "X")],
    )
    got = query(
        silver_settings,
        "select customer_code, f_multiple_names, f_multiple_branches "
        "from silver_customer_codes order by 1",
    )
    assert got == [("C1", True, False), ("C2", False, False)]


def test_ac1_the_columns_have_the_declared_types(silver_settings: Settings) -> None:
    build(silver_settings, [line(8, "C1")])
    types = dict(
        query(
            silver_settings,
            "select column_name, data_type from information_schema.columns "
            "where table_name = 'silver_customer_codes'",
        )
    )
    assert types == {
        "customer_code": "VARCHAR",
        "order_lines": "BIGINT",
        "name_count": "BIGINT",
        "branch_count": "BIGINT",
        "near_duplicate_count": "BIGINT",
        "f_multiple_names": "BOOLEAN",
        "f_multiple_branches": "BOOLEAN",
    }


def test_ac1_an_empty_silver_table_gives_an_empty_customer_table(silver_settings: Settings) -> None:
    build(silver_settings, [])
    assert query(silver_settings, "select count(*) from silver_customer_codes") == [(0,)]


def test_ac1_the_table_is_rebuilt_not_appended(silver_settings: Settings) -> None:
    build(silver_settings, [line(8, "C1"), line(9, "C2")])
    build(silver_settings, [line(8, "C3")])
    assert [r[0] for r in table(silver_settings)] == ["C3"]


def test_ac1_the_lines_add_up_to_the_kept_rows_with_a_code(silver_settings: Settings) -> None:
    rows = [line(8 + i, f"C{i % 3}") for i in range(9)] + [line(20, None)]
    build(silver_settings, rows)
    total = query(silver_settings, "select sum(order_lines) from silver_customer_codes")
    assert total == [(9,)], "nine lines have a code; the tenth has none"


def test_ac1_a_broken_customer_table_fails_the_checks(
    silver_settings: Settings, tmp_path: Path
) -> None:
    files = {"09b_break.sql": "delete from silver_customer_codes where customer_code = 'C1';"}
    with pytest.raises(StageError, match=r"99_checks\.sql.*customer"):
        run_custom_stage(silver_settings, [line(8, "C1"), line(9, "C2")], tmp_path / "s", files)


def test_ac1_the_check_does_not_fire_on_a_good_build(silver_settings: Settings) -> None:
    build(silver_settings, [line(8, "C1"), line(9, "C2"), line(10, None)])
    assert query(silver_settings, "select count(*) from silver_customer_codes") == [(2,)]


# AC2: near-duplicate codes are not merged ----------


def test_ac2_codes_that_differ_only_by_case_stay_separate(silver_settings: Settings) -> None:
    rows = [line(8, "ABC-1", "Anna"), line(9, "abc-1", "Anna"), line(10, "Abc-1", "Bob")]
    build(silver_settings, rows)
    assert table(silver_settings) == [
        ("ABC-1", 1, 1, 1, 2, False, False),
        ("Abc-1", 1, 1, 1, 2, False, False),
        ("abc-1", 1, 1, 1, 2, False, False),
    ]


def test_ac2_codes_that_differ_only_by_a_surrounding_space_stay_separate(
    silver_settings: Settings,
) -> None:
    build(silver_settings, [line(8, "ABC-1"), line(9, "ABC-1 "), line(10, " ABC-1")])
    got = table(silver_settings)
    assert len(got) == 3
    assert {r[4] for r in got} == {2}


def test_ac2_the_counts_are_never_added_across_near_duplicates(silver_settings: Settings) -> None:
    rows = [line(8, "ABC-1", "Anna", "North"), line(9, "abc-1", "Bob", "South")]
    build(silver_settings, rows)
    for row in table(silver_settings):
        assert (row[1], row[2], row[3]) == (1, 1, 1)


def test_ac2_codes_that_merely_look_alike_are_not_even_marked(silver_settings: Settings) -> None:
    rows = [line(8, "ABC.1"), line(9, "ABC-1"), line(10, "ABC1"), line(11, "ABC-01")]
    build(silver_settings, rows)
    assert {r[4] for r in table(silver_settings)} == {0}
    assert len(table(silver_settings)) == 4


def test_ac2_a_code_with_no_near_duplicate_has_a_zero_count(silver_settings: Settings) -> None:
    build(silver_settings, [line(8, "ABC-1"), line(9, "XYZ-9")])
    assert {r[4] for r in table(silver_settings)} == {0}


def test_ac2_silver_sales_keeps_every_code_exactly_as_it_was(silver_settings: Settings) -> None:
    codes = ["ABC-1", "abc-1", "ABC-1 ", None, ""]
    build(silver_settings, [line(8 + i, c) for i, c in enumerate(codes)])
    got = query(silver_settings, 'select "CustomerCode" from silver_sales order by _source_row')
    assert [r[0] for r in got] == codes


def test_ac2_no_sql_file_rewrites_a_customer_code() -> None:
    for path in SILVER_DIR.glob("*.sql"):
        text = path.read_text(encoding="utf-8").lower()
        assert 'set "customercode"' not in text and "set customercode" not in text, path.name


# AC3: logs and error messages hold no customer names or codes ----------


def test_ac3_the_logs_hold_no_codes_or_names(
    silver_settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    write_bronze(
        silver_settings,
        [
            line(8, "SECRET-CODE-1", "SECRET-NAME-A", "SECRET-BRANCH"),
            line(9, "secret-code-1", "SECRET-NAME-B"),
        ],
    )
    with caplog.at_level(logging.DEBUG, logger="revint"):
        run_silver(silver_settings)
    for secret in ("SECRET-CODE", "secret-code", "SECRET-NAME", "SECRET-BRANCH"):
        assert secret not in caplog.text


def test_ac3_a_failed_check_names_counts_never_a_code_or_name(
    silver_settings: Settings, tmp_path: Path
) -> None:
    files = {
        "09b_break.sql": "delete from silver_customer_codes where customer_code = 'SECRET-CODE';"
    }
    rows = [line(8, "SECRET-CODE", "SECRET-NAME"), line(9, "C2")]
    with pytest.raises(StageError) as info:
        run_custom_stage(silver_settings, rows, tmp_path / "s", files)
    assert "SECRET" not in str(info.value)
    assert "\n" not in str(info.value)


def test_ac3_the_printed_summary_is_counts_only(silver_settings: Settings) -> None:
    write_bronze(silver_settings, [line(8, "SECRET-CODE", "SECRET-NAME")])
    result = run_silver(silver_settings)
    assert "SECRET" not in repr(result)


# The columns come from config ----------


def test_the_code_name_and_branch_columns_come_from_config(load_with) -> None:
    settings = load_with(
        {
            "ingest": {"expected_columns": EXPECTED, "sheets": ["RAW SCJ SALES"]},
            "customers": {
                "code_column": "VoucherNo",
                "name_column": "KAM",
                "branch_column": "Region",
            },
        }
    )
    rows = [
        line(8, "C1", "Anna", "North", VoucherNo="V1", KAM="K1", Region="R1"),
        line(9, "C1", "Anna", "North", VoucherNo="V1", KAM="K2", Region="R1"),
        line(10, "C1", "Anna", "North", VoucherNo="V2", KAM="K1", Region="R2"),
    ]
    build(settings, rows)
    assert table(settings) == [
        ("V1", 2, 2, 1, 0, True, False),
        ("V2", 1, 1, 1, 0, False, False),
    ]


def test_no_silver_sql_file_hard_codes_the_customer_columns() -> None:
    text = (SILVER_DIR / "09_customer_codes.sql").read_text(encoding="utf-8")
    code_lines = [line for line in text.splitlines() if not line.lstrip().startswith("--")]
    body = "\n".join(code_lines)
    # the source column names are never written in the SQL itself, only the config parameters
    for name in ("CustomerCode", '"Customer"', "Branch_Name", "'Customer'"):
        assert name not in body, name
    text = text.lower()
    assert "$customers_code_column" in text
    assert "$customers_name_column" in text and "$customers_branch_column" in text


def test_a_customer_column_missing_from_the_bronze_file_fails_the_build(load_with) -> None:
    settings = load_with({"ingest": {"expected_columns": EXPECTED, "sheets": ["RAW SCJ SALES"]}})
    write_bronze(settings, [line(8, "C1")])
    path = next(settings.paths.bronze.glob("*.parquet"))
    import polars as pl

    pl.read_parquet(path).drop("Branch_Name").write_parquet(path)
    with pytest.raises(SilverError, match="Branch_Name"):
        run_silver(settings)


# The stage and the rest of silver ----------


def test_the_customer_table_is_built_after_the_audit_table_and_before_the_checks() -> None:
    names = sorted(p.name for p in SILVER_DIR.glob("*.sql"))
    assert names.index("08_excluded_rows.sql") < names.index("09_customer_codes.sql")
    assert names.index("09_customer_codes.sql") < names.index("99_checks.sql")


def test_silver_sales_is_unchanged_by_the_customer_table(silver_settings: Settings) -> None:
    build(silver_settings, [line(8, "C1"), line(9, "c1")])
    types = dict(query(silver_settings, COLUMN_TYPES_SQL))
    assert not [
        name for name in types if "customer_code" in name.lower() and name != "CustomerCode"
    ]


def test_the_build_is_repeatable_with_identical_content(silver_settings: Settings) -> None:
    rows = [line(8 + i, f"C{i % 3}", f"N{i % 2}") for i in range(9)]
    build(silver_settings, rows)
    first = table(silver_settings)
    run_silver(silver_settings)
    assert table(silver_settings) == first


# Real file: runs only when data/ exists ----------


@pytest.mark.realdata
def test_ac1_real_file_customer_table_matches_the_profiling(tmp_path: Path) -> None:
    """Counts only. No code or name is read into the test output."""
    import duckdb

    settings = load_settings(env={"REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb")})
    if not list(settings.paths.bronze.glob("*__RAW_SCJ_SALES.parquet")):
        pytest.skip("bronze not built: run `uv run revint build bronze` first")
    run_silver(settings)
    con = duckdb.connect(str(settings.paths.warehouse), read_only=True)
    try:
        codes, lines, multi_names, multi_branches, near = con.execute(
            "select count(*), sum(order_lines), count(*) filter (where f_multiple_names), "
            "count(*) filter (where f_multiple_branches), "
            "count(*) filter (where near_duplicate_count > 0) from silver_customer_codes"
        ).fetchone()
        assert codes == 12_239, "profiling: distinct non-blank CustomerCode values"
        kept_with_code = con.execute(
            "select count(*) from silver_sales where not is_excluded "
            "and trim(coalesce(\"CustomerCode\", '')) <> ''"
        ).fetchone()[0]
        assert lines == kept_with_code
        assert multi_names == 437 and multi_branches == 87
        assert near > 0, "55 codes differ from another only by case or surrounding space"
        folded = con.execute(
            "select count(distinct upper(trim(customer_code))) from silver_customer_codes"
        ).fetchone()[0]
        assert folded == 12_184 and codes - folded == 55
    finally:
        con.close()
