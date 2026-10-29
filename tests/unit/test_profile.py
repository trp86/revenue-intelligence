"""Story #31: profiling the RAW SCJ SALES sheet (spec 01 section 10a).

All data here is synthetic. The profiler returns counts and aggregates only.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import polars as pl
import pytest

from revint.config import load_settings
from revint.ingest.excel import SheetData
from revint.ingest.profile import (
    ProfileError,
    format_report,
    main,
    profile_frame,
)

HEADER = ["Id", "Void", "Qty", "Amt", "Net Amount", "Ch", "Br", "Change to Ctn"]


def make_sheet(
    data_rows: list[list[str | None]],
    header: list[str] = HEADER,
    header_row: int = 7,
    lead_rows: dict[int, list[str | None]] | None = None,
    first_row: int = 5,
    tail_rows: list[list[str | None]] | None = None,
) -> SheetData:
    """A sheet shaped like the real one: a lone value above the header, then header, then data.

    Row `first_row` holds one stray value; rows up to the header are empty; `tail_rows`
    follow the data (for example the stray row).
    """
    width = len(header)
    rows: dict[int, list[str | None]] = {}
    rows[first_row] = [None] * (width - 1) + ["above"]
    rows[header_row] = list(header)
    for offset, row in enumerate(data_rows, start=1):
        rows[header_row + offset] = row
    last_data = header_row + len(data_rows)
    for offset, row in enumerate(tail_rows or [], start=1):
        rows[last_data + offset] = row
    rows.update(lead_rows or {})
    last = max(rows)
    frame_rows = [rows.get(r, [None] * width) for r in range(first_row, last + 1)]
    frame = pl.DataFrame(frame_rows, schema=[f"column_{i}" for i in range(width)], orient="row")
    return SheetData(
        name="RAW SCJ SALES", frame=frame, first_row=first_row, dimension=f"A4:H{last}"
    )


def row(
    id_: str = "1",
    void: str | None = None,
    qty: str | None = "1",
    amt: str | None = "10",
    net: str | None = "10",
    ch: str | None = "MT",
    br: str | None = "B1",
    ctn: str | None = "1",
) -> list[str | None]:
    return [id_, void, qty, amt, net, ch, br, ctn]


# AC1: header row, data start row, column count, data row count -----------------------


def test_ac1_reports_header_row_data_start_column_count_and_data_rows() -> None:
    sheet = make_sheet([row("1"), row("2"), row("3")])
    result = profile_frame(sheet, header_search_rows=30)
    assert result.header_row == 7
    assert result.data_start_row == 8
    assert result.column_count == 8
    assert result.data_row_count == 3
    assert result.first_data_row == 8 and result.last_data_row == 10


def test_ac1_header_is_the_row_with_the_most_filled_cells_in_the_search_range() -> None:
    sheet = make_sheet([row()], header_row=10, first_row=5)
    assert profile_frame(sheet, header_search_rows=30).header_row == 10


def test_ac1_header_search_is_limited_to_the_configured_rows() -> None:
    sheet = make_sheet([row()], header_row=40, first_row=5)
    with pytest.raises(ProfileError, match="header"):
        profile_frame(sheet, header_search_rows=30)


def test_ac1_data_rows_exclude_the_stray_row_and_trailing_empty_rows() -> None:
    stray = [None] * 7 + ["1"]
    sheet = make_sheet([row("1"), row("2")], tail_rows=[stray])
    result = profile_frame(sheet, header_search_rows=30)
    assert result.data_row_count == 2
    assert result.last_data_row == 9


def test_ac1_a_blank_data_row_between_rows_is_counted_as_a_data_row() -> None:
    blank = [None] * 8
    sheet = make_sheet([row("1"), blank, row("3")])
    result = profile_frame(sheet, header_search_rows=30)
    assert result.data_row_count == 3
    assert result.blank_data_rows == 1


def test_ac1_raw_header_names_are_returned_with_their_spaces() -> None:
    header = ["Id", "Void ", "Qty", "Amt", "Net Amount", "Ch", "Br", "Change to Ctn"]
    result = profile_frame(make_sheet([row()], header=header), header_search_rows=30)
    assert result.raw_header[1] == "Void "


def test_ac1_final_names_follow_the_naming_rule() -> None:
    header = ["Id", "Void ", "Qty", "Amt", "Net Amount", "Net AMOUNT", "Br", "Change to Ctn"]
    result = profile_frame(make_sheet([row()], header=header), header_search_rows=30)
    assert result.final_names == [
        "Id", "Void", "Qty", "Amt", "Net_Amount_1", "Net_AMOUNT_2", "Br", "Change_to_Ctn",
    ]


def test_ac1_expected_column_count_is_compared_when_given() -> None:
    result = profile_frame(make_sheet([row()]), header_search_rows=30, expected_columns=8)
    assert result.column_count_matches is True
    other = profile_frame(make_sheet([row()]), header_search_rows=30, expected_columns=75)
    assert other.column_count_matches is False


# AC2: stray row candidates -------------------------------------------------------------


def test_ac2_reports_the_exact_row_with_only_change_to_ctn() -> None:
    stray = [None] * 7 + ["1"]
    sheet = make_sheet([row("1"), row("2")], tail_rows=[stray])
    result = profile_frame(sheet, header_search_rows=30)
    assert result.stray_candidates == [10]  # header row 7, data rows 8 and 9, then the stray row
    assert result.stray_exactly_one is True


def test_ac2_a_row_with_other_cells_filled_is_not_a_candidate() -> None:
    almost = [None] * 6 + ["B1", "1"]
    result = profile_frame(make_sheet([row("1"), almost]), header_search_rows=30)
    assert result.stray_candidates == []
    assert result.stray_exactly_one is False


def test_ac2_change_to_ctn_other_than_one_is_not_a_candidate() -> None:
    zero = [None] * 7 + ["0"]
    result = profile_frame(make_sheet([row("1"), zero]), header_search_rows=30)
    assert result.stray_candidates == []


def test_ac2_a_whitespace_only_cell_counts_as_blank() -> None:
    stray = [" "] * 7 + ["1"]
    result = profile_frame(make_sheet([row("1")], tail_rows=[stray]), header_search_rows=30)
    assert result.stray_candidates == [9]


def test_ac2_two_candidates_are_both_reported() -> None:
    stray = [None] * 7 + ["1"]
    result = profile_frame(
        make_sheet([row("1"), stray, row("3")], tail_rows=[stray]), header_search_rows=30
    )
    assert result.stray_candidates == [9, 11]
    assert result.stray_exactly_one is False


def test_ac2_the_stray_row_is_not_counted_in_the_other_profiles() -> None:
    stray = [None] * 7 + ["1"]
    sheet = make_sheet([row(void="X"), row(void=None)], tail_rows=[stray])
    result = profile_frame(sheet, header_search_rows=30)
    assert sum(v.rows for v in result.void_values) == 2


# AC3: Void values ------------------------------------------------------------------------


def test_ac3_lists_distinct_void_values_with_row_counts_including_blank() -> None:
    rows = [row(void=None), row(void=None), row(void="1"), row(void=" "), row(void="Y")]
    result = profile_frame(make_sheet(rows), header_search_rows=30)
    counts = {v.value: v.rows for v in result.void_values}
    assert counts == {"(blank)": 3, "1": 1, "Y": 1}


def test_ac3_values_are_sorted_by_count_then_value() -> None:
    rows = [row(void="B"), row(void="A"), row(void="A"), row(void="C"), row(void="C")]
    values = [v.value for v in profile_frame(make_sheet(rows), header_search_rows=30).void_values]
    assert values == ["A", "C", "B"]


def test_ac3_nothing_is_mapped_or_guessed() -> None:
    result = profile_frame(make_sheet([row(void="1")]), header_search_rows=30)
    assert all(not hasattr(v, "flag") and not hasattr(v, "mapped") for v in result.void_values)
    assert result.void_mapping_note == "not mapped: a human supplies void.value_map"


def test_ac3_values_are_not_trimmed_beyond_blank_detection() -> None:
    rows = [row(void="1"), row(void="1 ")]
    counts = {
        v.value for v in profile_frame(make_sheet(rows), header_search_rows=30).void_values
    }
    assert counts == {"1", "1 "}


def test_ac3_a_missing_void_column_is_refused_naming_it() -> None:
    header = ["Id", "Qty", "Amt", "Net Amount", "Ch", "Br", "Change to Ctn"]
    sheet = make_sheet([[ "1", "1", "1", "1", "a", "b", "1"]], header=header)
    with pytest.raises(ProfileError, match="Void"):
        profile_frame(sheet, header_search_rows=30)


# AC4: duplicates, free goods, labels ------------------------------------------------------


def test_ac4_counts_exact_duplicate_extra_copies_ignoring_lineage() -> None:
    same = row("1")
    rows = [same, same, same, row("2"), row("2", amt="11")]
    result = profile_frame(make_sheet(rows), header_search_rows=30)
    assert result.duplicate_groups == 1
    assert result.duplicate_extra_rows == 2


def test_ac4_blank_cells_compare_equal_whatever_the_blank_is() -> None:
    a = row("1", void=None)
    b = row("1", void="")
    c = row("1", void="  ")
    result = profile_frame(make_sheet([a, b, c]), header_search_rows=30)
    assert result.duplicate_extra_rows == 2


def test_ac4_case_and_trailing_spaces_make_rows_different() -> None:
    rows = [row("A"), row("a"), row("A ")]
    assert profile_frame(make_sheet(rows), header_search_rows=30).duplicate_extra_rows == 0


def test_ac4_duplicates_are_compared_with_the_docs_figure() -> None:
    rows = [row("1"), row("1")]
    result = profile_frame(make_sheet(rows), header_search_rows=30, docs_duplicates=556)
    assert result.duplicate_docs_figure == 556
    assert result.duplicate_extra_rows == 1
    assert result.duplicate_difference_from_docs == 1 - 556


def test_ac4_free_goods_count_zero_value_with_quantity_per_amount_column() -> None:
    rows = [
        row(qty="3", amt="0", net="0"),
        row(qty="3", amt="5", net="0"),
        row(qty="0", amt="0", net="0"),
        row(qty="2", amt="0", net=None),
        row(qty="1", amt="9", net="9"),
    ]
    result = profile_frame(
        make_sheet(rows),
        header_search_rows=30,
        amount_columns=["Amt", "Net Amount"],
        quantity_column="Qty",
    )
    assert result.free_goods == {"Amt": 2, "Net_Amount": 2}


def test_ac4_free_goods_treats_a_dash_as_not_a_number_and_not_zero() -> None:
    rows = [row(qty="3", amt="0", net="-")]
    result = profile_frame(
        make_sheet(rows),
        header_search_rows=30,
        amount_columns=["Net Amount"],
        quantity_column="Qty",
    )
    assert result.free_goods == {"Net_Amount": 0}
    assert result.non_numeric_counts["Net_Amount"] == 1


def test_ac4_distinct_channel_and_branch_labels_are_counted_not_listed() -> None:
    rows = [row(ch="MT", br="B1"), row(ch="MT", br="B2"), row(ch="GT", br="B1"), row(ch=None)]
    result = profile_frame(
        make_sheet(rows), header_search_rows=30, channel_columns=["Ch"], branch_columns=["Br"]
    )
    by_column = {label.column: label for label in result.labels}
    assert by_column["Ch"].kind == "channel" and by_column["Br"].kind == "branch"
    assert by_column["Ch"].distinct == 3  # MT, GT, blank
    assert by_column["Br"].distinct == 2  # B1, B2
    assert by_column["Ch"].counts == {"MT": 2, "GT": 1, "(blank)": 1}
    assert by_column["Br"].counts == {"B1": 3, "B2": 1}


def test_ac4_every_channel_and_branch_column_given_is_profiled() -> None:
    header = ["Id", "Void", "Qty", "Amt", "Change to Ctn", "Channel Type", "Channel Category",
              "Branch Name"]
    rows = [["1", None, "1", "1", "1", "A", "X", "P"], ["2", None, "1", "1", "1", "B", "X", "Q"]]
    result = profile_frame(
        make_sheet(rows, header=header),
        header_search_rows=30,
        channel_columns=["Channel Type", "Channel Category"],
        branch_columns=["Branch Name"],
    )
    assert {(lab.column, lab.distinct) for lab in result.labels} == {
        ("Channel_Type", 2), ("Channel_Category", 1), ("Branch_Name", 2),
    }


def test_ac4_label_names_are_withheld_from_the_report_by_default() -> None:
    rows = [row(ch="Secret Channel", br="Secret Branch")]
    result = profile_frame(
        make_sheet(rows), header_search_rows=30, channel_columns=["Ch"], branch_columns=["Br"]
    )
    text = format_report(result)
    assert "Secret Channel" not in text and "Secret Branch" not in text
    assert "Ch: 1 distinct" in text and "Br: 1 distinct" in text
    shown = format_report(result, show_labels=True)
    assert "Secret Channel" in shown


# AC5: report is aggregates only ---------------------------------------------------------------


def test_ac5_report_contains_no_row_values_other_than_void_values() -> None:
    rows = [row(id_="CUST-SECRET-1", ch="ChanSecret", br="BranchSecret", amt="777.7")]
    result = profile_frame(
        make_sheet(rows), header_search_rows=30, channel_columns=["Ch"], branch_columns=["Br"]
    )
    text = format_report(result)
    for value in ("CUST-SECRET-1", "ChanSecret", "BranchSecret", "777.7"):
        assert value not in text


def test_ac5_report_lists_the_expected_columns_as_a_yaml_ready_block() -> None:
    header = ["Id", "Void ", "Qty", "Amt", "Net Amount", "Net AMOUNT", "Br", "Change to Ctn"]
    result = profile_frame(make_sheet([row()], header=header), header_search_rows=30)
    text = format_report(result)
    assert "expected_columns:" in text
    assert "  - Net_Amount_1" in text and "  - Net_AMOUNT_2" in text
    assert "  - Void\n" in text


def test_ac5_the_expected_columns_block_is_valid_yaml_that_round_trips() -> None:
    import yaml

    header = ["Id", "Void ", "Yes", "Amt", "Net Amount", "Net AMOUNT", "%odd", "Change to Ctn"]
    result = profile_frame(make_sheet([row()], header=header), header_search_rows=30)
    text = format_report(result)
    block = text[text.index("expected_columns:"):]
    assert yaml.safe_load(block)["expected_columns"] == result.final_names


def test_ac5_the_report_states_the_numbers_a_reader_needs() -> None:
    sheet = make_sheet([row(void="1"), row(void=None)])
    text = format_report(profile_frame(sheet, header_search_rows=30))
    for needle in ("header row: 7", "data starts: row 8", "columns: 8", "data rows: 2"):
        assert needle in text
    assert "stray row candidates: none" in text or "stray row candidates" in text


def test_ac5_the_profiler_logs_counts_only(caplog: pytest.LogCaptureFixture) -> None:
    rows = [row(id_="CUST-SECRET-1", ch="ChanSecret", amt="777.7")]
    with caplog.at_level(logging.DEBUG, logger="revint"):
        profile_frame(make_sheet(rows), header_search_rows=30)
    for value in ("CUST-SECRET-1", "ChanSecret", "777.7"):
        assert value not in caplog.text


# AC6: end to end on a synthetic workbook; real data test skips without data/ ---------------


def test_ac6_main_profiles_a_synthetic_workbook_through_the_raw_helper(
    tmp_path: Path, build_workbook, capsys: pytest.CaptureFixture[str]
) -> None:
    raw = tmp_path / "raw"
    build_workbook(
        raw / "sales.xlsx",
        {
            5: [None] * 7 + ["x"],
            7: list(HEADER),
            8: row("1", void="1"),
            9: row("2"),
            10: [None] * 7 + ["1"],
        },
        styled_blank=(4,),
    )
    code = main(["--raw-dir", str(raw), "--sheet", "RAW SCJ SALES"])
    out = capsys.readouterr().out
    assert code == 0
    assert "header row: 7" in out and "data rows: 2" in out
    assert "stray row candidates: row 10" in out
    assert "(blank)" in out


def test_ac6_main_can_write_the_report_as_json(tmp_path: Path, build_workbook) -> None:
    raw = tmp_path / "raw"
    build_workbook(raw / "sales.xlsx", {7: list(HEADER), 8: row("1")})
    target = tmp_path / "out" / "profile.json"
    assert main(["--raw-dir", str(raw), "--json", str(target)]) == 0
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["data_row_count"] == 1
    assert "CUST" not in target.read_text(encoding="utf-8")


def test_ac6_main_fails_clearly_when_the_sheet_is_not_found(
    tmp_path: Path, build_workbook, capsys: pytest.CaptureFixture[str]
) -> None:
    raw = tmp_path / "raw"
    build_workbook(raw / "sales.xlsx", {1: ["x"]}, sheet="Other")
    assert main(["--raw-dir", str(raw)]) != 0
    err = capsys.readouterr().err
    assert "no workbook" in err and "Traceback" not in err


def test_ac6_main_refuses_a_missing_raw_folder(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--raw-dir", str(tmp_path / "missing")]) != 0
    assert "raw folder" in capsys.readouterr().err


@pytest.mark.realdata
def test_ac6_real_file_matches_the_confirmed_structure() -> None:
    """Runs only when data/ exists. Counts and structure only; no values are asserted."""
    from revint.ingest.profile import profile_workbook

    settings = load_settings(env={})
    result = profile_workbook(settings)
    assert result.header_row == 7
    assert result.data_start_row == 8
    assert result.column_count == 75
    assert result.stray_candidates == [662135]
    assert result.data_row_count == 662_127
