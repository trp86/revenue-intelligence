"""Story #73: profile the candidate brand and category columns (spec 02 section 12).

Synthetic bronze data only. The real-file test is marked `realdata` and asserts counts only.
Output is counts: no product, brand or category value is printed or stored.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from silver_helpers import EXPECTED, bronze_row, write_bronze

from revint.config import Settings, load_settings
from revint.product_profile import (
    CANDIDATE_COLUMNS,
    VALUE_RULE,
    ProductProfile,
    ProfileError,
    format_profile,
    main,
    profile_products,
)

SECRET = "SECRET-"
CODE = "SCJ_CODE_1"


@pytest.fixture
def settings(load_with) -> Settings:
    return load_with({"ingest": {"expected_columns": EXPECTED, "sheets": ["RAW SCJ SALES"]}})


def row(n: int, code: str | None, **cells: str | None) -> dict[str, str | None]:
    return bronze_row(n, **{CODE: code, **cells})


def by_column(profile: ProductProfile) -> dict:
    return {c.column: c for c in profile.candidates}


# AC1: distinct count, blank count and conflicting codes per candidate column -------------------


def test_ac1_every_candidate_column_is_reported(settings: Settings) -> None:
    write_bronze(settings, [row(8, "P1")])
    got = profile_products(settings)
    assert [c.column for c in got.candidates] == list(CANDIDATE_COLUMNS)
    assert set(CANDIDATE_COLUMNS) == {
        "Internal_Category",
        "Actual_Brands_1",
        "Actual_Brands_2",
        "SCJ_SEGMENT",
        "FRAGRANCES",
        "Size",
    }


def test_ac1_distinct_and_blank_counts(settings: Settings) -> None:
    rows = [
        row(8, "P1", Internal_Category=f"{SECRET}A"),
        row(9, "P1", Internal_Category=f"{SECRET}A"),
        row(10, "P2", Internal_Category=f"{SECRET}B"),
        row(11, "P3", Internal_Category=None),
        row(12, "P4", Internal_Category="   "),
    ]
    write_bronze(settings, rows)
    got = by_column(profile_products(settings))["Internal_Category"]
    assert got.distinct == 2
    assert got.blank_rows == 2  # a NULL and a whitespace-only cell are both blank


def test_ac1_whitespace_variants_of_blank_are_all_blank(settings: Settings) -> None:
    rows = [
        row(8, "P1", Size=" "),
        row(9, "P2", Size="\t"),
        row(10, "P3", Size=""),
        row(11, "P4", Size="10"),
    ]
    write_bronze(settings, rows)
    got = by_column(profile_products(settings))["Size"]
    assert (got.distinct, got.blank_rows) == (1, 3)


def test_ac1_a_value_is_counted_by_its_exact_text_after_nothing_but_blank_detection(
    settings: Settings,
) -> None:
    # 'A' and 'a' are different values, as in silver's duplicate rule
    write_bronze(settings, [row(8, "P1", Size="A"), row(9, "P2", Size="a")])
    assert by_column(profile_products(settings))["Size"].distinct == 2


def test_ac1_conflicting_codes_are_counted_per_column(settings: Settings) -> None:
    rows = [
        row(8, "P1", Internal_Category="A", Actual_Brands_1="X"),
        row(9, "P1", Internal_Category="B", Actual_Brands_1="X"),  # P1 conflicts on category only
        row(10, "P2", Internal_Category="A", Actual_Brands_1="X"),
        row(11, "P2", Internal_Category="A", Actual_Brands_1="Y"),  # P2 conflicts on brand only
        row(12, "P3", Internal_Category="A", Actual_Brands_1="X"),
    ]
    write_bronze(settings, rows)
    got = by_column(profile_products(settings))
    assert got["Internal_Category"].conflict_codes == 1
    assert got["Actual_Brands_1"].conflict_codes == 1
    assert got["Size"].conflict_codes == 0


def test_ac1_a_blank_beside_a_value_is_not_a_conflict(settings: Settings) -> None:
    rows = [row(8, "P1", Size="10"), row(9, "P1", Size=None), row(10, "P1", Size="  ")]
    write_bronze(settings, rows)
    assert by_column(profile_products(settings))["Size"].conflict_codes == 0


def test_ac1_codes_with_no_value_are_counted(settings: Settings) -> None:
    rows = [
        row(8, "P1", Size="10"),
        row(9, "P2", Size=None),
        row(10, "P2", Size=" "),
        row(11, "P3", Size="12"),
    ]
    write_bronze(settings, rows)
    assert by_column(profile_products(settings))["Size"].codes_without_value == 1


def test_ac1_product_code_totals(settings: Settings) -> None:
    rows = [row(8, "P1"), row(9, "P1"), row(10, "P2"), row(11, None), row(12, "  ")]
    write_bronze(settings, rows)
    got = profile_products(settings)
    assert got.rows == 5
    assert got.codes == 2
    assert got.blank_code_rows == 2


def test_ac1_name_conflicts_are_counted_for_the_name_column(settings: Settings) -> None:
    rows = [
        row(8, "P1", Product_Decription="One"),
        row(9, "P1", Product_Decription="Uno"),
        row(10, "P2", Product_Decription="Two"),
    ]
    write_bronze(settings, rows)
    got = profile_products(settings)
    assert got.name_column == "Product_Decription"
    assert got.name_conflict_codes == 1


def test_ac1_identical_candidate_columns_are_reported(settings: Settings) -> None:
    rows = [
        row(8, "P1", Actual_Brands_1="X", Actual_Brands_2="X"),
        row(9, "P2", Actual_Brands_1="Y", Actual_Brands_2="Y"),
        row(10, "P3", Actual_Brands_1=None, Actual_Brands_2="  "),
    ]
    write_bronze(settings, rows)
    got = profile_products(settings)
    assert ("Actual_Brands_1", "Actual_Brands_2") in got.identical_pairs
    assert ("Internal_Category", "Actual_Brands_1") not in got.identical_pairs


def test_ac1_columns_that_differ_on_one_row_are_not_identical(settings: Settings) -> None:
    rows = [
        row(8, "P1", Actual_Brands_1="X", Actual_Brands_2="X"),
        row(9, "P2", Actual_Brands_1="Y", Actual_Brands_2="Z"),
    ]
    write_bronze(settings, rows)
    assert ("Actual_Brands_1", "Actual_Brands_2") not in profile_products(settings).identical_pairs


def test_ac1_a_candidate_missing_from_bronze_fails_naming_it(settings: Settings) -> None:
    import polars as pl

    path = write_bronze(settings, [row(8, "P1")])
    pl.read_parquet(path).drop("FRAGRANCES").write_parquet(path)
    with pytest.raises(ProfileError, match="FRAGRANCES"):
        profile_products(settings)


def test_ac1_no_bronze_file_says_to_build_bronze(settings: Settings) -> None:
    with pytest.raises(ProfileError, match="revint build bronze"):
        profile_products(settings)


def test_ac1_an_empty_bronze_table_gives_zero_counts(settings: Settings) -> None:
    write_bronze(settings, [])
    got = profile_products(settings)
    assert (got.rows, got.codes) == (0, 0)
    assert all(c.distinct == 0 and c.conflict_codes == 0 for c in got.candidates)


def test_ac1_output_is_counts_only(
    settings: Settings, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    rows = [
        row(
            8,
            f"{SECRET}P1",
            Internal_Category=f"{SECRET}cat",
            Actual_Brands_1=f"{SECRET}brand",
            Product_Decription=f"{SECRET}name",
        ),
        row(9, f"{SECRET}P1", Internal_Category=f"{SECRET}other"),
    ]
    write_bronze(settings, rows)
    with caplog.at_level(logging.DEBUG):
        got = profile_products(settings)
        text = format_profile(got)
        as_json = json.dumps(got.as_dict())
    assert SECRET not in text + as_json + caplog.text
    assert SECRET not in capsys.readouterr().out


def test_ac1_the_text_report_lists_every_candidate_with_its_three_counts(
    settings: Settings,
) -> None:
    write_bronze(settings, [row(8, "P1", Size="10")])
    text = format_profile(profile_products(settings))
    for column in CANDIDATE_COLUMNS:
        line = next(line for line in text.splitlines() if line.startswith(column))
        assert "distinct" in line and "blank" in line and "conflict" in line


# AC3: conflicts are reported and the rule for choosing a value is stated ------------------------


def test_ac3_the_rule_is_the_most_frequent_value_with_a_stated_tie_break() -> None:
    assert "most frequent" in VALUE_RULE
    assert "lowest _source_row" in VALUE_RULE


def test_ac3_the_report_prints_the_rule(settings: Settings) -> None:
    write_bronze(settings, [row(8, "P1")])
    assert VALUE_RULE in format_profile(profile_products(settings))


def test_ac3_codes_whose_top_value_is_tied_are_counted(settings: Settings) -> None:
    rows = [
        row(8, "P1", Size="A"),
        row(9, "P1", Size="B"),  # tied 1-1
        row(10, "P2", Size="A"),
        row(11, "P2", Size="A"),
        row(12, "P2", Size="B"),  # not tied, A wins 2-1
    ]
    write_bronze(settings, rows)
    got = by_column(profile_products(settings))["Size"]
    assert (got.conflict_codes, got.tied_codes) == (2, 1)


def test_ac3_a_code_with_one_value_has_no_conflict_and_no_tie(settings: Settings) -> None:
    write_bronze(settings, [row(8, "P1", Size="A"), row(9, "P1", Size="A")])
    got = by_column(profile_products(settings))["Size"]
    assert (got.conflict_codes, got.tied_codes) == (0, 0)


# Command line ------


def test_main_prints_the_report_and_exits_zero(
    settings: Settings, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    write_bronze(settings, [row(8, f"{SECRET}P1", Size="10")])
    monkeypatch.setattr("revint.product_profile.load_settings", lambda *a, **k: settings)
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "Internal_Category" in out
    assert SECRET not in out


def test_main_json_is_valid_json_with_the_counts(
    settings: Settings, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    write_bronze(settings, [row(8, "P1", Size="10")])
    monkeypatch.setattr("revint.product_profile.load_settings", lambda *a, **k: settings)
    assert main(["--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["codes"] == 1
    assert {c["column"] for c in data["candidates"]} == set(CANDIDATE_COLUMNS)


def test_main_without_bronze_exits_non_zero_with_a_message(
    settings: Settings, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("revint.product_profile.load_settings", lambda *a, **k: settings)
    assert main([]) == 4
    assert "revint build bronze" in capsys.readouterr().err


# AC2: findings recorded in the spec; config names the chosen columns ------------------------------

SPEC = Path(__file__).resolve().parents[2] / "docs" / "specs" / "02-gold-layer.md"


def test_ac2_config_names_the_four_product_columns_in_the_sheet() -> None:
    s = load_settings(env={})
    chosen = {
        s.product.code_column,
        s.product.name_column,
        s.product.brand_column,
        s.product.category_column,
    }
    assert len(chosen) == 4
    assert chosen <= set(s.ingest.expected_columns)
    assert s.product.brand_column in CANDIDATE_COLUMNS
    assert s.product.category_column in CANDIDATE_COLUMNS


def test_ac2_the_chosen_columns_are_the_ones_the_spec_records() -> None:
    s = load_settings(env={})
    section = SPEC.read_text(encoding="utf-8").split("## 12. OPEN QUESTIONS")[1]
    assert "story #73" in section
    for column in (s.product.brand_column, s.product.category_column, s.product.code_column):
        assert column in section


def test_ac2_the_spec_states_the_rule_for_a_code_with_several_values() -> None:
    section = SPEC.read_text(encoding="utf-8").split("## 12. OPEN QUESTIONS")[1]
    assert VALUE_RULE in section


def test_ac2_the_product_hierarchy_question_is_no_longer_open_without_an_answer() -> None:
    section = SPEC.read_text(encoding="utf-8").split("## 12. OPEN QUESTIONS")[1]
    assert "- DECIDED (provisional" in section
    assert "OPEN QUESTION: Product hierarchy" not in section


# AC4 ---------------------------------------------------------------------------------------------


def test_ac4_every_ac_has_a_test_in_this_module() -> None:
    text = Path(__file__).read_text(encoding="utf-8")
    for ac in range(1, 4):
        assert f"def test_ac{ac}_" in text


@pytest.mark.realdata
def test_ac1_ac3_real_file_profile_counts() -> None:
    """Counts only. Reads the built bronze file; writes nothing."""
    real = load_settings(env={})
    if not list(real.paths.bronze.glob("*__RAW_SCJ_SALES.parquet")):
        pytest.skip("bronze not built: run `uv run revint build bronze` first")
    got = profile_products(real)
    cols = by_column(got)
    assert (got.rows, got.codes, got.blank_code_rows) == (662_128, 181, 1_107)
    assert cols["Actual_Brands_1"].distinct == 7
    assert ("Actual_Brands_1", "Actual_Brands_2") in got.identical_pairs
    assert cols["Internal_Category"].distinct == 40
    assert cols["Internal_Category"].blank_rows == 1_238
    assert cols["Internal_Category"].conflict_codes == 2
    assert cols["Internal_Category"].codes_without_value == 4
    assert cols["SCJ_SEGMENT"].distinct == 17
    assert got.name_conflict_codes == 12
