"""Story #32: find the header row and name the columns (spec 01 B2, B3).

Synthetic sheets only: no client data. The sheets are built in code, either as a text
frame (`sheet_of`) or as a real .xlsx through the `build_workbook` fixture.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from revint.config import load_settings
from revint.ingest.columns import final_column_names
from revint.ingest.excel import SheetData, read_sheet
from revint.ingest.header import (
    HeaderError,
    HeaderInfo,
    HeaderNotFoundError,
    detect_header,
    detect_header_from_settings,
)

EXPECTED = ["Id", "Name", "Qty", "Amount", "Net_Amount"]
HEADER = ["Id", "Name", "Qty", "Amount", "Net Amount"]  # inner space becomes an underscore
DATA = ["1", "x", "2", "10", "10"]


def sheet_of(rows: dict[int, list[str | None]], name: str = "RAW SCJ SALES") -> SheetData:
    """A text frame laid out like `read_sheet` does: it starts at the first row with a value."""
    filled = [r for r, cells in rows.items() if any(c is not None for c in cells)]
    first, last = min(filled), max(rows)
    width = max(len(cells) for cells in rows.values())
    frame_rows = []
    for number in range(first, last + 1):
        cells = list(rows.get(number, []))
        frame_rows.append(cells + [None] * (width - len(cells)))
    frame = pl.DataFrame(frame_rows, schema=[f"column_{i}" for i in range(width)], orient="row")
    return SheetData(name=name, frame=frame, first_row=first, dimension=f"A{first}:A{last}")


def detect(
    sheet: SheetData,
    expected: list[str] = EXPECTED,
    rows: int = 30,
    share: float = 0.8,
) -> HeaderInfo:
    return detect_header(sheet, expected, search_rows=rows, min_match=share)


# AC1: 3 blank rows, header on row 7, data starts on row 8 ------------------------------


def test_ac1_header_on_row_7_gives_data_start_on_row_8() -> None:
    info = detect(sheet_of({7: HEADER, 8: DATA, 9: DATA}))
    assert info.header_row == 7
    assert info.data_start_row == 8
    assert info.sheet == "RAW SCJ SALES"


def test_ac1_a_lone_value_above_the_header_does_not_change_the_result() -> None:
    rows = {5: [None, None, None, None, "note"], 7: HEADER, 8: DATA}
    info = detect(sheet_of(rows))
    assert (info.header_row, info.data_start_row) == (7, 8)


def test_ac1_workbook_with_three_blank_rows_before_the_header(
    tmp_path: Path, build_workbook
) -> None:
    path = build_workbook(
        tmp_path / "a.xlsx", {7: HEADER, 8: DATA, 9: DATA}, styled_blank=(4, 5, 6)
    )
    sheet = read_sheet(path.read_bytes(), "RAW SCJ SALES")
    assert sheet.first_row == 7, "the reader starts at the first cell with a value"
    info = detect(sheet)
    assert (info.header_row, info.data_start_row) == (7, 8)


def test_ac1_workbook_laid_out_like_the_real_sheet(tmp_path: Path, build_workbook) -> None:
    rows: dict[int, list[Any]] = {5: [None, None, None, None, "note"], 7: HEADER, 8: DATA}
    path = build_workbook(tmp_path / "a.xlsx", rows, styled_blank=(4,))
    sheet = read_sheet(path.read_bytes(), "RAW SCJ SALES")
    assert sheet.first_row == 5, "the formatted empty cell on row 4 is not a value"
    info = detect(sheet)
    assert (info.header_row, info.data_start_row) == (7, 8)


def test_ac1_header_cells_with_surrounding_spaces_still_match() -> None:
    header = ["Id ", " Name", "Qty", "Amount ", "Net Amount "]
    info = detect(sheet_of({7: header, 8: DATA}))
    assert info.header_row == 7
    assert info.final_names == EXPECTED
    assert info.raw_names == header, "raw names keep their spaces"


def test_ac1_columns_are_matched_by_name_so_a_different_order_is_still_found() -> None:
    shuffled = ["Net Amount", "Id", "Amount", "Name", "Qty"]
    info = detect(sheet_of({7: shuffled, 8: DATA}))
    assert info.header_row == 7
    assert info.matched == 5


# AC2: header on row 1 ---------------------------------------------------------------------


def test_ac2_header_on_row_1_is_detected() -> None:
    info = detect(sheet_of({1: HEADER, 2: DATA, 3: DATA}))
    assert (info.header_row, info.data_start_row) == (1, 2)


def test_ac2_workbook_with_the_header_on_row_1(tmp_path: Path, build_workbook) -> None:
    path = build_workbook(tmp_path / "a.xlsx", {1: HEADER, 2: DATA, 3: DATA})
    info = detect(read_sheet(path.read_bytes(), "RAW SCJ SALES"))
    assert (info.header_row, info.data_start_row) == (1, 2)


def test_ac2_the_first_row_that_meets_the_threshold_wins_over_a_later_repeat() -> None:
    info = detect(sheet_of({3: HEADER, 4: DATA, 6: HEADER}))
    assert info.header_row == 3


def test_ac2_a_partial_row_above_the_header_is_skipped() -> None:
    decoy = ["Id", "Name", "other", "other", "other"]  # 2 of 5 expected names
    info = detect(sheet_of({2: decoy, 3: HEADER, 4: DATA}))
    assert info.header_row == 3


def test_ac2_the_threshold_boundary_is_inclusive() -> None:
    four_of_five = ["Id", "Name", "Qty", "Amount", "Other"]
    info = detect(sheet_of({2: four_of_five, 3: DATA}), share=0.8)
    assert (info.matched, info.expected, info.header_row) == (4, 5, 2)
    with pytest.raises(HeaderNotFoundError):
        detect(sheet_of({2: four_of_five, 3: DATA}), share=0.81)


def test_ac2_a_stricter_share_skips_a_row_that_a_looser_one_accepts() -> None:
    three_of_five = ["Id", "Name", "Qty", "x", "y"]
    assert detect(sheet_of({2: three_of_five, 4: HEADER}), share=0.5).header_row == 2
    assert detect(sheet_of({2: three_of_five, 4: HEADER}), share=0.8).header_row == 4


# AC3: no header in range fails loudly, listing the rows inspected ----------------------------


def test_ac3_no_header_raises_and_lists_the_rows_inspected() -> None:
    unrelated = ["a", "b", "c", "d", "e"]
    sheet = sheet_of({r: unrelated for r in range(1, 12)})
    with pytest.raises(HeaderNotFoundError) as info:
        detect(sheet, rows=5)
    assert info.value.rows_inspected == [1, 2, 3, 4, 5]
    assert "rows inspected: 1 to 5 (5 rows)" in str(info.value)


def test_ac3_a_header_just_beyond_the_search_range_is_not_found() -> None:
    sheet = sheet_of({1: ["a"] * 5, 9: HEADER, 10: DATA})
    with pytest.raises(HeaderNotFoundError, match=r"rows inspected: 1 to 5"):
        detect(sheet, rows=5)
    assert detect(sheet, rows=9).header_row == 9


def test_ac3_the_search_stops_at_the_last_row_of_a_short_sheet() -> None:
    sheet = sheet_of({1: ["a"] * 5, 2: ["b"] * 5, 3: ["c"] * 5})
    with pytest.raises(HeaderNotFoundError) as info:
        detect(sheet, rows=30)
    assert info.value.rows_inspected == [1, 2, 3]
    assert "rows inspected: 1 to 3 (3 rows)" in str(info.value)


def test_ac3_the_message_reports_the_best_match_and_the_requirement() -> None:
    sheet = sheet_of({1: ["x"] * 5, 4: ["Id", "Name", "Qty", "x", "y"]})
    with pytest.raises(HeaderNotFoundError) as info:
        detect(sheet, rows=10)
    message = str(info.value)
    assert "best match: 3 of 5 expected columns (60%) at row 4" in message
    assert "needs at least 80%" in message
    assert (info.value.best_row, info.value.best_matched) == (4, 3)


def test_ac3_a_sheet_with_no_expected_column_at_all_says_so() -> None:
    with pytest.raises(HeaderNotFoundError, match="no row had any expected column"):
        detect(sheet_of({1: ["x"] * 5, 2: ["y"] * 5}))


def test_ac3_the_error_is_raised_never_swallowed_into_a_none_result() -> None:
    result = None
    with pytest.raises(HeaderNotFoundError):
        result = detect(sheet_of({1: ["x"] * 5}))
    assert result is None


def test_ac3_the_error_message_is_one_line_without_cell_values() -> None:
    sheet = sheet_of({1: ["SECRET-VALUE-1", "b", "c", "d", "e"]})
    with pytest.raises(HeaderNotFoundError) as info:
        detect(sheet)
    assert "\n" not in str(info.value)
    assert "SECRET-VALUE-1" not in str(info.value)


def test_ac3_empty_expected_columns_is_a_configuration_error() -> None:
    with pytest.raises(HeaderError, match=r"ingest\.expected_columns") as info:
        detect(sheet_of({1: HEADER}), expected=[])
    assert not isinstance(info.value, HeaderNotFoundError)


# AC4: names and the source-position map ------------------------------------------------------


def test_ac4_duplicate_names_are_suffixed_in_source_order_and_unique_ones_are_not() -> None:
    header = ["A", "B", "B", "C"]
    expected = ["A", "B_1", "B_2", "C"]
    info = detect(sheet_of({1: header, 2: ["1"] * 4}), expected=expected)
    assert info.final_names == ["A", "B_1", "B_2", "C"]


def test_ac4_names_that_differ_only_by_case_are_suffixed_too() -> None:
    header = ["Id", "Net Amount", "NET AMOUNT", "Qty"]
    expected = ["Id", "Net_Amount_1", "NET_AMOUNT_2", "Qty"]
    info = detect(sheet_of({1: header, 2: ["1"] * 4}), expected=expected)
    assert info.final_names == expected
    assert [e.raw_name for e in info.column_map] == header


def test_ac4_the_map_gives_position_excel_column_raw_name_and_final_name() -> None:
    header = ["Id", "Net Amount ", "Net Amount", "Qty", "Name"]
    expected = ["Id", "Net_Amount_1", "Net_Amount_2", "Qty", "Name"]
    info = detect(sheet_of({7: header, 8: ["1"] * 5}), expected=expected)
    assert [e.position for e in info.column_map] == [1, 2, 3, 4, 5]
    assert [e.source_column for e in info.column_map] == ["A", "B", "C", "D", "E"]
    assert info.column_map[1].raw_name == "Net Amount "
    assert info.column_map[1].final_name == "Net_Amount_1"
    assert info.column_map[2].final_name == "Net_Amount_2"


def test_ac4_excel_column_letters_continue_past_z() -> None:
    header = [f"C{i}" for i in range(1, 30)]
    info = detect(sheet_of({1: header, 2: ["1"] * 29}), expected=header, share=1)
    assert info.column_map[25].source_column == "Z"
    assert info.column_map[26].source_column == "AA"
    assert info.column_map[28].source_column == "AC"


def test_ac4_the_map_can_be_written_as_a_table_for_bronze_column_map() -> None:
    info = detect(sheet_of({7: HEADER, 8: DATA}))
    frame = info.to_frame()
    assert frame.columns == ["position", "source_column", "raw_name", "final_name"]
    assert frame.height == 5
    assert frame["final_name"].to_list() == EXPECTED
    assert frame["position"].to_list() == [1, 2, 3, 4, 5]


def test_ac4_the_map_stops_at_the_last_filled_header_cell() -> None:
    header = [*HEADER, None, None]
    info = detect(sheet_of({1: header, 2: [*DATA, "1", "2"]}))
    assert len(info.column_map) == 5


def test_ac4_an_empty_header_cell_between_names_is_refused_naming_its_position() -> None:
    header = ["Id", "Name", None, "Amount", "Net Amount"]
    with pytest.raises(HeaderError, match="column 3"):
        detect(sheet_of({1: header, 2: DATA}), share=0.6)


def test_ac4_the_result_is_identical_when_detected_twice() -> None:
    sheet = sheet_of({5: [None, None, None, None, "note"], 7: HEADER, 8: DATA})
    assert detect(sheet) == detect(sheet)


def test_ac4_the_expected_columns_in_the_config_are_their_own_final_names() -> None:
    expected = load_settings(env={}).ingest.expected_columns
    assert len(expected) == 75
    assert final_column_names(expected) == expected, "the naming rule is idempotent"


def test_ac4_a_sheet_with_the_configured_columns_is_found_through_settings() -> None:
    expected = load_settings(env={}).ingest.expected_columns
    sheet = sheet_of({7: expected, 8: ["1"] * len(expected)})
    info = detect_header_from_settings(sheet, load_settings(env={}))
    assert (info.header_row, info.data_start_row) == (7, 8)
    assert (info.matched, info.expected) == (75, 75)
    assert info.final_names == expected
    assert info.column_map[45].final_name == "Net_Amount_2"
    assert info.column_map[45].source_column == "AT"


def test_ac4_settings_drive_the_search_range_and_the_threshold(load_with) -> None:
    settings = load_with(
        {"ingest": {"expected_columns": EXPECTED, "header_search_rows": 4, "header_min_match": 1}}
    )
    assert detect_header_from_settings(sheet_of({3: HEADER, 4: DATA}), settings).header_row == 3
    with pytest.raises(HeaderNotFoundError, match="1 to 4"):
        detect_header_from_settings(sheet_of({1: ["a"] * 5, 6: HEADER}), settings)
    four = ["Id", "Name", "Qty", "Amount", "Other"]
    with pytest.raises(HeaderNotFoundError):
        detect_header_from_settings(sheet_of({3: four, 4: DATA}), settings)


def test_ac4_settings_without_expected_columns_fail_with_a_clear_message(load_with) -> None:
    with pytest.raises(HeaderError, match=r"ingest\.expected_columns"):
        detect_header_from_settings(sheet_of({1: HEADER}), load_with())


# Logging carries counts only ---------------------------------------------------------------


def test_logs_carry_counts_and_no_column_names(caplog: pytest.LogCaptureFixture) -> None:
    header = ["SecretColumnA", "SecretColumnB"]
    with caplog.at_level(logging.DEBUG, logger="revint"):
        detect(sheet_of({1: header, 2: ["1", "2"]}), expected=header, share=1)
    assert "header row 1: 2 of 2 expected columns matched" in caplog.text
    assert "SecretColumn" not in caplog.text


# Real file: runs only when data/ exists ------------------------------------------------------


@pytest.mark.realdata
def test_ac1_real_file_header_is_row_7_and_the_map_has_75_entries() -> None:
    """Structure only: no cell values are asserted or printed."""
    from pathlib import Path as _Path

    from revint.ingest.excel import find_workbook
    from revint.ingest.raw import open_raw

    settings = load_settings(env={})
    raw = settings.paths.raw
    workbook = find_workbook(raw, "RAW SCJ SALES")
    with open_raw(_Path(workbook.name), raw) as handle:
        sheet = read_sheet(handle.read(), "RAW SCJ SALES")
    info = detect_header_from_settings(sheet, settings)
    assert (info.header_row, info.data_start_row) == (7, 8)
    assert (info.matched, info.expected) == (75, 75)
    assert len(info.column_map) == 75
    assert info.final_names == settings.ingest.expected_columns
    assert (info.column_map[45].raw_name, info.column_map[45].source_column) == ("Net Amount", "AT")
    assert (info.column_map[74].final_name, info.column_map[74].source_column) == ("Region", "BW")
