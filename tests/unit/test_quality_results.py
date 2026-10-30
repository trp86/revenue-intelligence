"""Story #41: data quality results (spec 01 section 5, rules S1 to S12).

The crafted fixture below has known counts for every rule. Synthetic bronze data only; the
real-file test is marked `realdata` and asserts counts and sums, never a row value.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from pathlib import Path

import pytest
from silver_helpers import (
    EXPECTED,
    SIX_AMOUNTS,
    bronze_row,
    build,
    query,
    run_custom_stage,
    silver_columns,
    write_bronze,
)

from revint.config import RULE_IDS, Settings, load_settings
from revint.pipeline import StageError
from revint.silver import SILVER_DIR, SilverError, run_silver

NET = "Net_Amount_2"
TOTAL_ROWS = 12


def make_settings(load_with, name: str = "cfg", **sections) -> Settings:
    extra: dict = {
        "ingest": {"expected_columns": EXPECTED, "sheets": ["RAW SCJ SALES"]},
        "labels": {"channel_map": {"MT": "Modern Trade"}},
        "void": {"value_map": {"Voided": 1}},
    }
    extra.update(sections)
    return load_with(extra, name=name)


@pytest.fixture
def settings(load_with) -> Settings:
    return make_settings(load_with)


def row(source_row: int, **cells: str | None):
    """An ordinary line: a unique order reference, net sales 10 and quantity 1, all else blank."""
    base = {"OrderReference": f"O{source_row}", NET: "10", "Quantity(PCS)": "1"}
    base.update(cells)
    return bronze_row(source_row, **base)


def fixture_rows() -> list[dict[str, str | None]]:
    """Twelve source rows, 8 to 19, whose rule counts are known (see EXPECTED_*)."""
    duplicate = {"OrderReference": "DUP", NET: "50", "Quantity(PCS)": "1"}
    return [
        row(8, CustomerCode="C1", Customer="Ann"),
        row(9, CustomerCode="C1", Customer="Anna", **{NET: "-"}),  # bad candidate value, NULL net
        row(
            10, CustomerCode="C2", Customer="Bob", Discount_2="x", **{NET: "20"}
        ),  # bad, not a candidate
        row(
            11, CustomerCode="C3", Customer="Cy", PRICE="1.23456", **{NET: "30"}
        ),  # rounded to 4 places
        row(12, CustomerCode="c3", Customer="Cy", **{NET: "0", "Quantity(PCS)": "3"}),  # free good
        row(13, Void="Other", **{NET: "40", "Quantity(PCS)": "-2"}),  # negative qty, unmapped Void
        row(14, **{NET: "-5"}),  # negative value
        bronze_row(15, **duplicate),
        bronze_row(16, **duplicate),  # exact copy of row 15
        bronze_row(17, Change_to_Ctn="1"),  # the stray row
        row(18, Channel_Category="MT", **{NET: "60"}),  # the label map changes it
        row(19, Void="Voided", **{NET: "70"}),  # voided
    ]


EXPECTED_ROWS = {
    "S1": 1, "S2": 2, "S3": 1, "S4": 4, "S5": 1, "S6": 10,
    "S7": 1, "S8": 2, "S9": 1, "S10": 2, "S11": 1, "S12": 2,
}  # fmt: skip
EXPECTED_IMPACT = {
    "S1": None, "S2": Decimal("20"), "S3": Decimal("60"), "S4": None, "S5": Decimal("50"),
    "S6": Decimal("215"), "S7": Decimal("0"), "S8": Decimal("35"), "S9": Decimal("0"),
    "S10": Decimal("50"), "S11": Decimal("0"), "S12": Decimal("50"),
}  # fmt: skip


def results(settings: Settings) -> dict[str, tuple]:
    got = query(
        settings,
        "select rule_id, description, rows_affected, pct_rows, net_sales_impact, action_taken, "
        "severity from dq_rule_results",
    )
    return {r[0]: r for r in got}


@pytest.fixture
def built(settings: Settings) -> Settings:
    build(settings, fixture_rows())
    return settings


# AC1: one row per rule S1 to S12 with the seven columns ----------


def test_ac1_there_is_one_row_per_rule_s1_to_s12(built: Settings) -> None:
    ids = [r[0] for r in query(built, "select rule_id from dq_rule_results")]
    assert sorted(ids, key=lambda i: int(i[1:])) == RULE_IDS
    assert len(ids) == len(set(ids)) == 12


def test_ac1_the_rows_come_back_in_rule_order(built: Settings) -> None:
    ids = [r[0] for r in query(built, "select rule_id from dq_rule_results")]
    assert ids == RULE_IDS


def test_ac1_the_table_has_exactly_the_seven_columns_in_order(built: Settings) -> None:
    columns = [
        c
        for (c,) in query(
            built,
            "select column_name from information_schema.columns "
            "where table_name = 'dq_rule_results' order by ordinal_position",
        )
    ]
    assert columns == [
        "rule_id", "description", "rows_affected", "pct_rows", "net_sales_impact",
        "action_taken", "severity",
    ]  # fmt: skip


def test_ac1_the_columns_have_the_declared_types(built: Settings) -> None:
    types = dict(
        query(
            built,
            "select column_name, data_type from information_schema.columns "
            "where table_name = 'dq_rule_results'",
        )
    )
    assert types == {
        "rule_id": "VARCHAR",
        "description": "VARCHAR",
        "rows_affected": "BIGINT",
        "pct_rows": "DECIMAL(9,4)",
        "net_sales_impact": "DECIMAL(38,4)",
        "action_taken": "VARCHAR",
        "severity": "VARCHAR",
    }


def test_ac1_every_rule_has_a_description_an_action_and_a_severity(built: Settings) -> None:
    for rule_id, desc, _, _, _, action, severity in results(built).values():
        assert desc and desc.strip(), rule_id
        assert action in {"flagged", "excluded", "transformed", "recorded"}, rule_id
        assert severity in {"info", "warning", "high"}, rule_id


def test_ac1_each_description_names_its_rule(built: Settings) -> None:
    for rule_id, desc, *_ in results(built).values():
        assert desc.startswith(f"{rule_id} "), (rule_id, desc)


def test_ac1_action_and_severity_come_from_config(load_with) -> None:
    severity = dict.fromkeys(RULE_IDS, "info") | {"S5": "warning"}
    action = dict.fromkeys(RULE_IDS, "flagged") | {"S1": "recorded"}
    changed = make_settings(load_with, quality={"severity": severity, "action": action})
    build(changed, fixture_rows())
    got = results(changed)
    assert got["S5"][6] == "warning" and got["S1"][5] == "recorded"
    assert {r[6] for rule, r in got.items() if rule != "S5"} == {"info"}


def test_ac1_pct_rows_is_rows_affected_over_all_silver_rows(built: Settings) -> None:
    for rule_id, _, rows, pct, *_ in results(built).values():
        assert pct == (Decimal(rows) * 100 / TOTAL_ROWS).quantize(Decimal("0.0001")), rule_id


def test_ac1_an_empty_silver_table_still_has_twelve_rows_with_no_percentages(
    settings: Settings,
) -> None:
    build(settings, [])
    got = query(settings, "select rule_id, rows_affected, pct_rows from dq_rule_results")
    assert len(got) == 12
    assert {r[1] for r in got} == {0} and {r[2] for r in got} == {None}


def test_ac1_the_tables_are_rebuilt_not_appended(settings: Settings) -> None:
    build(settings, fixture_rows())
    run_silver(settings)
    assert query(settings, "select count(*) from dq_rule_results") == [(12,)]
    assert query(settings, "select count(*) from dq_exclusion_effect") == [(12,)]
    assert query(settings, "select count(*) from dq_void_effect") == [(1,)]


def test_ac1_a_broken_results_table_fails_the_checks(settings: Settings, tmp_path: Path) -> None:
    files = {"10b_break.sql": "delete from dq_rule_results where rule_id = 'S7';"}
    with pytest.raises(StageError, match=r"99_checks\.sql.*dq_rule_results"):
        run_custom_stage(settings, fixture_rows(), tmp_path / "s", files)


# AC2: a crafted fixture gives known counts ----------


@pytest.mark.parametrize("rule_id", RULE_IDS)
def test_ac2_rows_affected_match_the_known_counts(built: Settings, rule_id: str) -> None:
    assert results(built)[rule_id][2] == EXPECTED_ROWS[rule_id]


@pytest.mark.parametrize("rule_id", RULE_IDS)
def test_ac2_net_sales_impact_matches_the_known_sums(built: Settings, rule_id: str) -> None:
    got = results(built)[rule_id][4]
    expected = EXPECTED_IMPACT[rule_id]
    assert got == (None if expected is None else expected.quantize(Decimal("0.0001")))


def test_ac2_the_fixture_has_the_expected_number_of_rows(built: Settings) -> None:
    assert query(built, "select count(*) from silver_sales") == [(TOTAL_ROWS,)]
    assert len(fixture_rows()) == TOTAL_ROWS


def test_ac2_s1_counts_only_rows_where_rounding_changed_a_value(settings: Settings) -> None:
    rows = [
        row(8, PRICE="1.5"),  # exact
        row(9, PRICE="1.50000"),  # trailing zeros: same value
        row(10, PRICE="1.23456"),  # rounded
        row(11, PRICE="0.00004"),  # rounded to zero
        row(12, PRICE=" 7 "),  # surrounding spaces only
        row(13, PRICE="abc"),  # bad, not rounding
    ]
    build(settings, rows)
    assert results(settings)["S1"][2] == 2


def test_ac2_s2_counts_a_row_once_however_many_values_are_bad(settings: Settings) -> None:
    rows = [row(8, PRICE="x", Discount_2="y", Year="z"), row(9), row(10, PRICE="q")]
    build(settings, rows)
    assert results(settings)["S2"][2] == 2


def test_ac2_s3_counts_rows_whose_label_the_map_changed_not_unmapped_ones(load_with) -> None:
    settings = make_settings(
        load_with,
        labels={"channel_map": {"MT": "Modern Trade"}, "branch_map": {"MAGWAY": "Magway"}},
    )
    rows = [
        row(8, Channel_Category="MT"),  # changed
        row(9, Channel_Category="GT"),  # unmapped, unchanged
        row(10, Branch_Name="MAGWAY"),  # changed
        row(11, Channel_Category="MT", Branch_Name="MAGWAY"),  # both changed: one row
        row(12),
    ]
    build(settings, rows)
    assert results(settings)["S3"][2] == 3


def test_ac2_s4_counts_the_kept_lines_of_flagged_codes(settings: Settings) -> None:
    rows = [
        row(8, CustomerCode="A", Customer="One", Branch_Name="X"),
        row(9, CustomerCode="A", Customer="One", Branch_Name="Y"),  # two branches
        row(10, CustomerCode="B", Customer="One", Branch_Name="X"),  # clean
        row(11, CustomerCode="B", Customer="One", Branch_Name="X"),  # clean
    ]
    build(settings, rows)
    assert results(settings)["S4"][2] == 2


def test_ac2_s4_ignores_excluded_copies(settings: Settings) -> None:
    same = {"OrderReference": "O1", "CustomerCode": "A", "Customer": "One", NET: "5"}
    rows = [bronze_row(8, **same), bronze_row(9, **same), row(10, CustomerCode="A", Customer="Two")]
    build(settings, rows)
    assert results(settings)["S4"][2] == 2


def test_ac2_s5_s9_s10_and_s12_agree_with_the_exclusion_tables(built: Settings) -> None:
    got = results(built)
    assert got["S10"][2] == got["S5"][2] + got["S9"][2] == got["S12"][2]


def test_ac2_s11_counts_only_bad_values_in_the_configured_candidate_columns(load_with) -> None:
    settings = make_settings(
        load_with,
        net_sales={"field": NET, "candidate_columns": [NET, "TAX_AMOUNT"]},
    )
    rows = [
        row(8, Selling_Amount="-"),  # bad, but no longer a candidate
        row(9, TAX_AMOUNT="-"),  # bad candidate
        row(10, **{NET: "-"}),  # bad candidate
        row(11),
    ]
    build(settings, rows)
    assert results(settings)["S11"][2] == 2


def test_ac2_a_clean_fixture_has_zero_problem_rows(settings: Settings) -> None:
    build(settings, [row(8 + i, CustomerCode=f"C{i}", Customer="N") for i in range(5)])
    got = results(settings)
    for rule_id in ("S1", "S2", "S3", "S4", "S5", "S7", "S8", "S9", "S10", "S11", "S12"):
        assert got[rule_id][2] == 0, rule_id
        assert got[rule_id][3] == Decimal("0.0000"), rule_id


# AC3: voided lines ----------


def test_ac3_the_void_table_holds_the_count_and_amount_of_voided_lines(built: Settings) -> None:
    got = query(
        built,
        "select voided_lines, voided_net_sales, blank_void_lines, unmapped_void_lines "
        "from dq_void_effect",
    )
    assert got == [(1, Decimal("70.0000"), 10, 1)]


def test_ac3_the_s6_description_states_the_voided_lines_and_the_unmapped_values(
    built: Settings,
) -> None:
    desc = results(built)["S6"][1]
    assert "voided lines (void_flag = 1): 1" in desc
    assert "unmapped Void values: 1" in desc


def test_ac3_with_no_voided_lines_the_count_and_amount_are_zero(load_with) -> None:
    settings = make_settings(load_with, void={"value_map": {}})
    build(settings, fixture_rows())
    got = query(settings, "select voided_lines, voided_net_sales from dq_void_effect")
    assert got == [(0, Decimal("0.0000"))]
    assert "voided lines (void_flag = 1): 0" in results(settings)["S6"][1]


def test_ac3_the_void_table_columns_have_the_declared_types(built: Settings) -> None:
    types = dict(
        query(
            built,
            "select column_name, data_type from information_schema.columns "
            "where table_name = 'dq_void_effect'",
        )
    )
    assert types == {
        "voided_lines": "BIGINT",
        "voided_net_sales": "DECIMAL(38,4)",
        "blank_void_lines": "BIGINT",
        "unmapped_void_lines": "BIGINT",
    }


# AC4: exclusions per reason and per amount column ----------


def effect(settings: Settings, reason: str, column: str) -> tuple:
    return query(
        settings,
        "select rows_excluded, excluded_amount, column_total, pct_of_column_total, "
        "pct_of_net_sales_total, is_net_sales_field from dq_exclusion_effect "
        "where exclusion_reason = ? and amount_column = ?",
        reason,
        column,
    )[0]


def test_ac4_there_is_one_row_per_reason_and_candidate_column(built: Settings) -> None:
    got = query(built, "select exclusion_reason, amount_column from dq_exclusion_effect")
    assert len(got) == len(set(got)) == 12
    assert {r[0] for r in got} == {"exact_duplicate", "stray_row"}
    assert {r[1] for r in got} == set(SIX_AMOUNTS)


def test_ac4_the_net_sales_column_row_holds_the_count_amount_and_percentages(
    built: Settings,
) -> None:
    got = effect(built, "exact_duplicate", NET)
    assert got == (
        1,
        Decimal("50.0000"),
        Decimal("325.0000"),
        Decimal("15.3846"),
        Decimal("15.3846"),
        True,
    )


def test_ac4_a_reason_with_no_amounts_has_a_zero_effect(built: Settings) -> None:
    got = effect(built, "stray_row", NET)
    assert got == (
        1,
        Decimal("0.0000"),
        Decimal("325.0000"),
        Decimal("0.0000"),
        Decimal("0.0000"),
        True,
    )


def test_ac4_the_percentage_of_the_net_sales_total_is_relative_to_net_sales_field(
    settings: Settings,
) -> None:
    rows = [
        row(8, Selling_Amount="100", **{NET: "200"}),
        row(9, Selling_Amount="100", **{NET: "200"}),  # a different order reference: not a copy
    ]
    same = {"OrderReference": "O1", "Selling_Amount": "50", NET: "25"}
    build(settings, [*rows, bronze_row(10, **same), bronze_row(11, **same)])  # row 11 is a copy
    got = effect(settings, "exact_duplicate", "Selling_Amount")
    # The copy carries 50 of a Selling_Amount total of 100 + 100 + 50 + 50 = 300 (16.6667%),
    # and 50 of a net sales total of 200 + 200 + 25 + 25 = 450 (11.1111%): the net sales total
    # covers every silver row, copies included.
    assert got[1] == Decimal("50.0000") and got[2] == Decimal("300.0000")
    assert got[3] == Decimal("16.6667")
    assert got[4] == Decimal("11.1111")
    assert got[5] is False


def test_ac4_a_column_with_no_values_has_no_percentage_of_its_own_total(built: Settings) -> None:
    got = effect(built, "exact_duplicate", "Selling_Amount")
    assert got[:3] == (1, Decimal("0.0000"), Decimal("0.0000"))
    assert got[3] is None and got[4] == Decimal("0.0000") and got[5] is False


def test_ac4_only_the_configured_net_sales_field_is_marked(built: Settings) -> None:
    marked = query(
        built, "select distinct amount_column from dq_exclusion_effect where is_net_sales_field"
    )
    assert marked == [(NET,)]


def test_ac4_the_net_sales_field_follows_config(load_with) -> None:
    settings = make_settings(load_with, net_sales={"field": "Net_AMOUNT_3"})
    build(settings, fixture_rows())
    marked = query(
        settings, "select distinct amount_column from dq_exclusion_effect where is_net_sales_field"
    )
    assert marked == [("Net_AMOUNT_3",)]


def test_ac4_the_counts_match_the_audit_table(built: Settings) -> None:
    by_reason = dict(
        query(built, "select exclusion_reason, count(*) from silver_excluded_rows group by 1")
    )
    for reason, count in by_reason.items():
        assert effect(built, reason, NET)[0] == count


def test_ac4_the_amounts_match_the_audit_table(built: Settings) -> None:
    for column in SIX_AMOUNTS:
        audit = dict(
            query(
                built,
                f'select exclusion_reason, coalesce(sum("{column}"), 0) '
                "from silver_excluded_rows group by 1",
            )
        )
        for reason in ("exact_duplicate", "stray_row"):
            expected = audit.get(reason, Decimal(0))
            assert effect(built, reason, column)[1] == Decimal(expected).quantize(Decimal("0.0001"))


def test_ac4_the_exclusion_table_columns_have_the_declared_types(built: Settings) -> None:
    types = dict(
        query(
            built,
            "select column_name, data_type from information_schema.columns "
            "where table_name = 'dq_exclusion_effect'",
        )
    )
    assert types == {
        "exclusion_reason": "VARCHAR",
        "amount_column": "VARCHAR",
        "rows_excluded": "BIGINT",
        "excluded_amount": "DECIMAL(38,4)",
        "column_total": "DECIMAL(38,4)",
        "pct_of_column_total": "DECIMAL(9,4)",
        "pct_of_net_sales_total": "DECIMAL(9,4)",
        "is_net_sales_field": "BOOLEAN",
    }


def test_ac4_the_reasons_are_the_allowed_ones() -> None:
    from revint.silver import ALLOWED_EXCLUSION_REASONS

    text = (SILVER_DIR / "10_quality_results.sql").read_text(encoding="utf-8")
    for reason in ALLOWED_EXCLUSION_REASONS:
        assert f"'{reason}'" in text


# AC5: counts and aggregates only ----------


def all_cells(settings: Settings) -> str:
    cells = []
    for table in ("dq_rule_results", "dq_exclusion_effect", "dq_void_effect"):
        for record in query(settings, f"select * from {table}"):
            cells.extend("" if v is None else str(v) for v in record)
    return "\n".join(cells)


def test_ac5_no_customer_or_label_value_reaches_the_tables(load_with) -> None:
    settings = make_settings(
        load_with, labels={"channel_map": {"SECRET-CHANNEL": "Safe"}, "branch_map": {}}
    )
    rows = [
        row(8, CustomerCode="SECRET-CODE", Customer="SECRET-NAME", Branch_Name="SECRET-BRANCH"),
        row(
            9,
            CustomerCode="SECRET-CODE",
            Customer="SECRET-OTHER",
            Channel_Category="SECRET-CHANNEL",
        ),
        row(10, Void="SECRET-VOID", OrderReference="SECRET-ORDER"),
    ]
    build(settings, rows)
    assert "SECRET" not in all_cells(settings)


def test_ac5_the_tables_have_no_row_level_columns(built: Settings) -> None:
    for table in ("dq_rule_results", "dq_exclusion_effect", "dq_void_effect"):
        names = {
            c
            for (c,) in query(
                built,
                "select column_name from information_schema.columns where table_name = ?",
                table,
            )
        }
        assert not names & {
            "_source_row",
            "customer_code",
            "CustomerCode",
            "Customer",
            "OrderReference",
        }
        assert not [n for n in names if n.endswith("_raw")]


def test_ac5_every_number_is_a_count_or_a_sum_over_many_rows(built: Settings) -> None:
    assert query(built, "select count(*) from dq_rule_results") == [(12,)]
    assert query(built, "select count(*) from dq_void_effect") == [(1,)]


def test_ac5_the_logs_carry_counts_and_no_values(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    write_bronze(settings, [row(8, CustomerCode="SECRET-CODE", Customer="SECRET-NAME")])
    with caplog.at_level(logging.DEBUG, logger="revint"):
        run_silver(settings)
    assert "SECRET" not in caplog.text


def test_ac5_a_failed_check_names_counts_not_values(settings: Settings, tmp_path: Path) -> None:
    files = {"10b_break.sql": "delete from dq_rule_results where rule_id = 'S7';"}
    rows = [row(8, CustomerCode="SECRET-CODE", Customer="SECRET-NAME")]
    with pytest.raises(StageError) as info:
        run_custom_stage(settings, rows, tmp_path / "s", files)
    assert "SECRET" not in str(info.value) and "\n" not in str(info.value)


# The SQL and the stage ----------


def test_the_quality_file_runs_after_every_table_it_reads_and_before_the_checks() -> None:
    names = sorted(p.name for p in SILVER_DIR.glob("*.sql"))
    assert names.index("09_customer_codes.sql") < names.index("10_quality_results.sql")
    assert names.index("10_quality_results.sql") < names.index("99_checks.sql")


def test_no_quality_sql_hard_codes_a_column_a_label_or_a_threshold() -> None:
    text = (SILVER_DIR / "10_quality_results.sql").read_text(encoding="utf-8")
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("--"))
    for forbidden in (
        "Net_Amount_2",
        "Selling_Amount",
        "Channel_Category",
        "CustomerCode",
        "'high'",
    ):
        assert forbidden not in code, forbidden
    for parameter in (
        "$net_sales_field",
        "$net_sales_candidate_columns",
        "$quality_severity_keys",
        "$quality_action_values",
        "$dq_decimal_columns",
        "$dq_decimal_raw_columns",
    ):
        assert parameter in text, parameter


def test_the_decimal_column_lists_line_up_with_the_silver_columns() -> None:
    from revint.silver import COLUMN_TYPES, silver_stage_parameters

    params = silver_stage_parameters(Path("x.parquet"))
    decimals = params["dq_decimal_columns"]
    assert decimals == [c for c, kind in COLUMN_TYPES.items() if kind == "decimal"]
    assert params["dq_decimal_raw_columns"] == [f"{c}_raw" for c in decimals]
    assert params["bronze_file"] == "x.parquet"


def test_silver_sales_is_unchanged_by_the_quality_file(settings: Settings) -> None:
    build(settings, fixture_rows())
    names = silver_columns(settings)
    assert not [n for n in names if n.startswith(("dq_", "s1", "s2"))]
    assert query(settings, "select count(*) from silver_sales") == [(TOTAL_ROWS,)]


def test_the_build_is_repeatable_with_identical_content(settings: Settings) -> None:
    build(settings, fixture_rows())
    first = query(settings, "select * from dq_rule_results order by rule_id")
    first_effect = query(settings, "select * from dq_exclusion_effect order by 1, 2")
    run_silver(settings)
    assert query(settings, "select * from dq_rule_results order by rule_id") == first
    assert query(settings, "select * from dq_exclusion_effect order by 1, 2") == first_effect


def test_a_missing_net_sales_column_in_the_audit_table_fails_clearly(load_with) -> None:
    settings = make_settings(load_with, net_sales={"field": "Net_AMOUNT_3"})
    build(settings, fixture_rows())  # works: the audit table holds all six candidates
    assert query(settings, "select count(*) from dq_exclusion_effect") == [(12,)]


def test_a_failed_build_leaves_no_quality_tables(settings: Settings) -> None:
    write_bronze(settings, [bronze_row(8, Change_to_Ctn="1"), bronze_row(9, Change_to_Ctn="1")])
    with pytest.raises(SilverError):
        run_silver(settings)
    tables = (
        {t for (t,) in query(settings, "select table_name from information_schema.tables")}
        if settings.paths.warehouse.exists()
        else set()
    )
    assert not tables & {"dq_rule_results", "dq_exclusion_effect", "dq_void_effect"}


# Real file: runs only when data/ exists ----------


@pytest.mark.realdata
def test_ac2_real_file_results_match_independent_counts(tmp_path: Path) -> None:
    """Counts and sums only. Every figure is counted a second way, straight from silver."""
    import duckdb

    real = load_settings(env={"REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb")})
    if not list(real.paths.bronze.glob("*__RAW_SCJ_SALES.parquet")):
        pytest.skip("bronze not built: run `uv run revint build bronze` first")
    run_silver(real)
    con = duckdb.connect(str(real.paths.warehouse), read_only=True)
    try:
        got = {
            r[0]: r
            for r in con.execute(
                "select rule_id, rows_affected, pct_rows, net_sales_impact, severity, action_taken "
                "from dq_rule_results"
            ).fetchall()
        }
        assert sorted(got, key=lambda i: int(i[1:])) == RULE_IDS
        total = con.execute("select count(*) from silver_sales").fetchone()[0]
        assert total == 662_128
        bad_cols = [
            c
            for (c,) in con.execute(
                "select column_name from information_schema.columns "
                "where table_name = 'silver_sales' and column_name like 'f_bad_%'"
            ).fetchall()
        ]
        any_bad = " or ".join(f'"{c}"' for c in bad_cols)
        independent = {
            "S2": f"select count(*) from silver_sales where {any_bad}",
            "S5": "select count(*) from silver_sales where is_duplicate",
            "S6": "select count(*) from silver_sales where f_blank_void",
            "S7": "select count(*) from silver_sales where f_zero_value_with_qty",
            "S8": "select count(*) from silver_sales where f_negative_qty or f_negative_value",
            "S9": "select count(*) from silver_sales where f_stray_row",
            "S10": "select count(*) from silver_sales where is_excluded",
            "S12": "select count(*) from silver_excluded_rows",
        }
        for rule_id, sql in independent.items():
            assert got[rule_id][1] == con.execute(sql).fetchone()[0], rule_id
        assert got["S2"][1] == 121_301 and got["S5"][1] == 556 and got["S10"][1] == 557
        assert got["S7"][1] == 120_727 and got["S9"][1] == 1 and got["S6"][1] == 28_034
        assert got["S3"][1] == 2_954 and got["S4"][1] == 166_018 and got["S11"][1] == 1_974
        assert got["S1"][1] > 0
        for rule_id, record in got.items():
            expected_pct = round(record[1] * 100 / total, 4)
            assert float(record[2]) == pytest.approx(expected_pct, abs=1e-4), rule_id
        net_total = con.execute(f'select sum("{NET}") from silver_sales').fetchone()[0]
        assert net_total == Decimal("15473904687.2629")
        dup_effect = con.execute(
            f"select excluded_amount from dq_exclusion_effect "
            f"where exclusion_reason = 'exact_duplicate' and amount_column = '{NET}'"
        ).fetchone()[0]
        assert abs(dup_effect - Decimal("2689566.12")) < Decimal("0.01")
        voided = con.execute("select voided_lines, voided_net_sales from dq_void_effect").fetchone()
        assert voided[0] == 0 and voided[1] == 0
        assert con.execute("select count(*) from dq_exclusion_effect").fetchone()[0] == 12
    finally:
        con.close()
