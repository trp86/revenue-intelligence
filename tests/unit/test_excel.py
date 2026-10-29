"""Story #31: reading one Excel sheet as text, with true Excel row numbers."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from revint.ingest.excel import (
    column_letter,
    find_workbook,
    first_value_row,
    read_sheet,
    sheet_dimension,
    sheet_names,
    sheet_xml_path,
)


def open_zip(path: Path) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(path.read_bytes()))


# column_letter ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("number", "letter"),
    [(1, "A"), (26, "Z"), (27, "AA"), (42, "AP"), (46, "AT"), (48, "AV"), (75, "BW"), (702, "ZZ")],
)
def test_column_letter(number: int, letter: str) -> None:
    assert column_letter(number) == letter


# sheet names ------------------------------------------------------------------------


def test_sheet_names_are_listed_in_workbook_order(tmp_path: Path, build_workbook) -> None:
    path = build_workbook(tmp_path / "a.xlsx", {1: ["x"]}, "First", extra_sheets=("Second",))
    assert sheet_names(open_zip(path)) == ["First", "Second"]


def test_sheet_names_unescape_xml_entities(tmp_path: Path, build_workbook) -> None:
    path = build_workbook(tmp_path / "a.xlsx", {1: ["x"]}, "Sales & Target")
    assert sheet_names(open_zip(path)) == ["Sales & Target"]
    assert sheet_xml_path(open_zip(path), "Sales & Target").endswith(".xml")


def test_an_unknown_sheet_is_refused_naming_the_sheets(tmp_path: Path, build_workbook) -> None:
    path = build_workbook(tmp_path / "a.xlsx", {1: ["x"]}, "Only")
    with pytest.raises(ValueError, match=r"no sheet named 'Missing'.*Only"):
        sheet_xml_path(open_zip(path), "Missing")


# first_value_row: fastexcel starts at the first cell with a value --------------------


def first_row_of(path: Path, sheet: str = "RAW SCJ SALES") -> int:
    zf = open_zip(path)
    return first_value_row(zf, sheet_xml_path(zf, sheet))


def test_a_formatted_empty_cell_does_not_count_as_the_first_row(
    tmp_path: Path, build_workbook
) -> None:
    path = build_workbook(
        tmp_path / "a.xlsx", {5: [None] * 5 + ["note"], 7: ["H1", "H2"]}, styled_blank=(4,)
    )
    assert first_row_of(path) == 5


def test_a_whitespace_only_text_cell_counts_as_a_value(tmp_path: Path, build_workbook) -> None:
    path = build_workbook(tmp_path / "a.xlsx", {5: [" "], 6: ["x"], 7: ["y"]})
    assert first_row_of(path) == 5


def test_the_first_row_is_row_one_when_data_starts_there(tmp_path: Path, build_workbook) -> None:
    assert first_row_of(build_workbook(tmp_path / "a.xlsx", {1: ["h"], 2: ["d"]})) == 1


def test_a_number_counts_as_a_value(tmp_path: Path, build_workbook) -> None:
    assert first_row_of(build_workbook(tmp_path / "a.xlsx", {3: [0], 4: ["x"]})) == 3


def test_a_sheet_with_no_values_is_refused(tmp_path: Path, build_workbook) -> None:
    path = build_workbook(tmp_path / "a.xlsx", {}, styled_blank=(2,))
    with pytest.raises(ValueError, match="no cell with a value"):
        first_row_of(path)


def test_dimension_is_read_from_the_sheet(tmp_path: Path, build_workbook) -> None:
    path = build_workbook(
        tmp_path / "a.xlsx", {5: [None] * 5 + ["note"], 9: ["x"]}, styled_blank=(4,)
    )
    zf = open_zip(path)
    assert sheet_dimension(zf, sheet_xml_path(zf, "RAW SCJ SALES")) == "A4:F9"


# read_sheet: text values aligned to real Excel rows -----------------------------------


def test_rows_line_up_with_excel_rows_across_gaps_and_styled_cells(
    tmp_path: Path, build_workbook
) -> None:
    path = build_workbook(
        tmp_path / "a.xlsx",
        {5: [None] * 5 + ["note"], 7: ["H1", "H2"], 8: ["1", "x"], 9: ["2", "y"]},
        styled_blank=(4,),
    )
    sheet = read_sheet(path.read_bytes(), "RAW SCJ SALES")
    assert sheet.first_row == 5
    assert sheet.frame.height == 5
    assert sheet.last_row == 9
    assert sheet.dimension == "A4:F9"
    assert sheet.frame.row(2) == ("H1", "H2", None, None, None, None)
    assert sheet.frame.row(0)[5] == "note"


def test_every_value_is_text_and_numbers_are_not_converted_to_other_types(
    tmp_path: Path, build_workbook
) -> None:
    path = build_workbook(tmp_path / "a.xlsx", {1: ["h1", "h2"], 2: ["001", 5]})
    frame = read_sheet(path.read_bytes(), "RAW SCJ SALES").frame
    assert {str(t) for t in frame.dtypes} == {"String"}
    assert frame.row(1)[0] == "001"
    assert float(frame.row(1)[1]) == 5.0


def test_a_fully_empty_row_between_rows_is_kept(tmp_path: Path, build_workbook) -> None:
    path = build_workbook(tmp_path / "a.xlsx", {1: ["a"], 2: ["b"], 4: ["d"]})
    sheet = read_sheet(path.read_bytes(), "RAW SCJ SALES")
    assert sheet.frame.height == 4
    assert sheet.frame.row(2) == (None,)
    assert sheet.frame.row(3) == ("d",)


def test_trailing_formatted_empty_rows_are_not_loaded(tmp_path: Path, build_workbook) -> None:
    path = build_workbook(tmp_path / "a.xlsx", {3: ["x"], 4: ["y"]}, styled_blank=(10,))
    sheet = read_sheet(path.read_bytes(), "RAW SCJ SALES")
    assert sheet.frame.height == 2
    assert sheet.last_row == 4
    assert sheet.dimension == "A3:A10"


def test_spaces_in_text_cells_are_kept_exactly(tmp_path: Path, build_workbook) -> None:
    path = build_workbook(tmp_path / "a.xlsx", {1: ["QTR ", " A  B "]})
    assert read_sheet(path.read_bytes(), "RAW SCJ SALES").frame.row(0) == ("QTR ", " A  B ")


# find_workbook ---------------------------------------------------------------------------


def test_find_workbook_returns_the_one_file_holding_the_sheet(
    tmp_path: Path, build_workbook
) -> None:
    raw = tmp_path / "raw"
    build_workbook(raw / "other.xlsx", {1: ["x"]}, "Other")
    wanted = build_workbook(
        raw / "sales.xlsx", {1: ["x"]}, "RAW SCJ SALES", extra_sheets=("Sheet1",)
    )
    assert find_workbook(raw, "RAW SCJ SALES") == wanted


def test_find_workbook_ignores_files_that_are_not_xlsx(tmp_path: Path, build_workbook) -> None:
    raw = tmp_path / "raw"
    build_workbook(raw / "sales.xlsx", {1: ["x"]}, "S")
    (raw / "notes.txt").write_text("no", encoding="utf-8")
    (raw / "broken.xlsx").write_bytes(b"not a zip")
    assert find_workbook(raw, "S").name == "sales.xlsx"


def test_find_workbook_fails_when_no_file_has_the_sheet(tmp_path: Path, build_workbook) -> None:
    raw = tmp_path / "raw"
    build_workbook(raw / "a.xlsx", {1: ["x"]}, "Other")
    with pytest.raises(ValueError, match="no workbook in the raw folder has a sheet named 'S'"):
        find_workbook(raw, "S")


def test_find_workbook_fails_when_two_files_have_the_sheet(tmp_path: Path, build_workbook) -> None:
    raw = tmp_path / "raw"
    build_workbook(raw / "a.xlsx", {1: ["x"]}, "S")
    build_workbook(raw / "b.xlsx", {1: ["x"]}, "S")
    with pytest.raises(ValueError, match=r"more than one workbook.*a\.xlsx.*b\.xlsx"):
        find_workbook(raw, "S")


def test_a_sheet_that_does_not_start_in_column_a_is_refused(tmp_path: Path, build_workbook) -> None:
    path = build_workbook(tmp_path / "a.xlsx", {1: [None, None, "x"], 2: [None, None, "y"]})
    with pytest.raises(ValueError, match="column A"):
        read_sheet(path.read_bytes(), "RAW SCJ SALES")
