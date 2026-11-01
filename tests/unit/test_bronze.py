"""Story #33: bronze ingestion to all-text Parquet with lineage (spec 01 B1, B4 to B7).

Synthetic workbooks only. The real-file test is marked `realdata` and asserts counts and
structure, never values.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from typer.testing import CliRunner

from revint import config
from revint.cli import app
from revint.config import Settings, load_settings
from revint.ingest.bronze import (
    COLUMN_MAP_FILE,
    EXIT_BRONZE_FAILED,
    EXIT_RAW_FILE_IN_USE,
    LINEAGE_COLUMNS,
    BronzeError,
    bronze_filename,
    build_bronze_frame,
    excel_lock_file,
    execute_bronze,
    run_bronze,
)
from revint.ingest.excel import SheetData
from revint.ingest.header import HeaderInfo, detect_header
from revint.ingest.raw import RawFileInUseError

EXPECTED = ["Id", "Name", "Qty", "Amount", "Net_Amount"]
HEADER = ["Id", "Name", "Qty", "Amount", "Net Amount"]  # the inner space becomes an underscore
NOW = datetime(2026, 10, 30, 9, 30, 0, tzinfo=UTC)
LATER = datetime(2026, 10, 31, 11, 0, 0, tzinfo=UTC)
SheetFactory = Callable[..., Settings]


@pytest.fixture
def settings_for(load_with, build_workbook) -> SheetFactory:
    """Settings whose raw folder holds one synthetic workbook `sales.xlsx`."""

    def _make(
        rows: dict[int, list[Any]],
        sheet: str = "RAW SCJ SALES",
        styled_blank: tuple[int, ...] = (),
        extra: dict[str, Any] | None = None,
    ) -> Settings:
        settings = load_with(
            {"ingest": {"expected_columns": EXPECTED, "sheets": [sheet], **(extra or {})}}
        )
        build_workbook(
            settings.paths.raw / "sales.xlsx", rows, sheet=sheet, styled_blank=styled_blank
        )
        return settings

    return _make


def bronze_file(settings: Settings, sheet: str = "RAW SCJ SALES") -> Path:
    return settings.paths.bronze / bronze_filename("sales.xlsx", sheet)


def read_bronze(settings: Settings, sheet: str = "RAW SCJ SALES") -> pl.DataFrame:
    return pl.read_parquet(bronze_file(settings, sheet))


LAYOUT = {
    5: [None, None, None, None, "note"],  # a lone value above the header, like the real sheet
    7: HEADER,
    8: ["001", "A ", 3, 10.5, 10.5],
    9: ["002", "B", 4, 20, 20],
    10: ["003", "C", 5, 30, 30],
}


# bronze_filename -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "sheet", "expected"),
    [
        ("sales.xlsx", "RAW SCJ SALES", "sales__RAW_SCJ_SALES.parquet"),
        ("SCJ SALES MASTER DATA YTD HP 2.xlsx", "RAW SCJ SALES",
         "SCJ_SALES_MASTER_DATA_YTD_HP_2__RAW_SCJ_SALES.parquet"),
        ("a&b.xlsx", "Sales & Target", "a_b__Sales_Target.parquet"),
        ("x.xlsx", "Sheet1", "x__Sheet1.parquet"),
    ],
)
def test_filename_is_source_double_underscore_sheet(source: str, sheet: str, expected: str) -> None:
    assert bronze_filename(source, sheet) == expected


# AC1: every column is text, no inference ---------------------------------------------------------


def test_ac1_every_column_is_text_including_lineage(settings_for: SheetFactory) -> None:
    settings = settings_for(LAYOUT)
    run_bronze(settings, NOW)
    frame = read_bronze(settings)
    assert {str(t) for t in frame.dtypes} == {"String"}
    assert frame.columns == [*EXPECTED, *LINEAGE_COLUMNS]


def test_ac1_leading_zeros_and_trailing_zeros_stay_as_written(settings_for: SheetFactory) -> None:
    rows = {7: HEADER, 8: ["001", "1.50", 3, 1.5, 100], 9: ["0", "007", 1, 0, 0]}
    settings = settings_for(rows)
    run_bronze(settings, NOW)
    frame = read_bronze(settings)
    assert frame["Id"].to_list() == ["001", "0"]
    assert frame["Name"].to_list() == ["1.50", "007"]
    assert frame["Amount"].to_list() == ["1.5", "0"]  # a number cell is written as its number


def test_ac1_spaces_in_text_are_kept(settings_for: SheetFactory) -> None:
    settings = settings_for({7: HEADER, 8: ["A ", " B", "x  y", 1, 2]})
    run_bronze(settings, NOW)
    row = read_bronze(settings).row(0, named=True)
    assert (row["Id"], row["Name"], row["Qty"]) == ("A ", " B", "x  y")


def test_ac1_dates_are_text_and_blank_cells_are_null(settings_for: SheetFactory) -> None:
    rows = {7: HEADER, 8: [datetime(2019, 8, 1), None, 3, 1, 1], 9: ["x", "y", None, None, None]}
    settings = settings_for(rows)
    run_bronze(settings, NOW)
    frame = read_bronze(settings)
    assert frame["Id"].to_list() == ["2019-08-01 00:00:00", "x"]
    assert frame["Name"].to_list() == [None, "y"]
    assert frame["Qty"].to_list() == ["3", None]


def test_ac1_nothing_is_trimmed_cast_or_cleaned_in_the_frame_builder() -> None:
    sheet, info = synthetic_sheet([["  001 ", "1.50", None, "x", "-"]])
    built = build_bronze_frame(sheet, info, "s.xlsx", "h" * 64, "2026-10-30T09:30:00Z")
    assert built.frame.row(0)[:5] == ("  001 ", "1.50", None, "x", "-")


# AC2: lineage ------------------------------------------------------------------------------------


def test_ac2_header_on_row_7_gives_source_row_8_for_the_first_data_row(
    settings_for: SheetFactory,
) -> None:
    settings = settings_for(LAYOUT, styled_blank=(4,))
    run_bronze(settings, NOW)
    frame = read_bronze(settings)
    assert frame["_source_row"].to_list() == ["8", "9", "10"]


def test_ac2_header_on_row_1_gives_source_row_2(settings_for: SheetFactory) -> None:
    settings = settings_for({1: HEADER, 2: ["a", "b", 1, 2, 3], 3: ["c", "d", 4, 5, 6]})
    run_bronze(settings, NOW)
    assert read_bronze(settings)["_source_row"].to_list() == ["2", "3"]


def test_ac2_lineage_columns_are_present_and_filled(settings_for: SheetFactory) -> None:
    settings = settings_for(LAYOUT)
    run_bronze(settings, NOW)
    frame = read_bronze(settings)
    digest = hashlib.sha256((settings.paths.raw / "sales.xlsx").read_bytes()).hexdigest()
    assert frame["_source_file"].unique().to_list() == ["sales.xlsx"]
    assert frame["_sheet"].unique().to_list() == ["RAW SCJ SALES"]
    assert frame["_file_hash"].unique().to_list() == [digest]
    assert frame["_ingested_at"].unique().to_list() == ["2026-10-30T09:30:00Z"]
    for column in LINEAGE_COLUMNS:
        assert frame[column].null_count() == 0


def test_ac2_ingested_at_is_utc_whatever_the_clock_zone(settings_for: SheetFactory) -> None:
    from datetime import timedelta, timezone

    settings = settings_for(LAYOUT)
    local = datetime(2026, 10, 30, 15, 0, 0, tzinfo=timezone(timedelta(hours=6, minutes=30)))
    run_bronze(settings, local)
    assert read_bronze(settings)["_ingested_at"][0] == "2026-10-30T08:30:00Z"


def test_ac2_a_blank_row_between_data_rows_keeps_the_numbering(settings_for: SheetFactory) -> None:
    rows = {7: HEADER, 8: ["a", "b", 1, 2, 3], 10: ["c", "d", 4, 5, 6]}
    settings = settings_for(rows)
    result = run_bronze(settings, NOW)
    frame = read_bronze(settings)
    assert frame["_source_row"].to_list() == ["8", "9", "10"]
    assert frame["Id"].to_list() == ["a", None, "c"]
    assert result.sheets[0].data_rows == 3


def test_ac2_a_lineage_name_clash_is_refused() -> None:
    header = ["Id", "_sheet", "Qty", "Amount", "Net Amount"]
    sheet, info = synthetic_sheet([["a", "b", "c", "d", "e"]], header=header)
    with pytest.raises(BronzeError, match="_sheet"):
        build_bronze_frame(sheet, info, "s.xlsx", "h" * 64, "t")


# AC3: trailing empty rows -------------------------------------------------------------------------


def synthetic_sheet(
    data_rows: list[list[str | None]],
    header: list[str] = HEADER,
    extra_columns: int = 0,
    expected: list[str] = EXPECTED,
) -> tuple[SheetData, HeaderInfo]:
    """A text frame with the header on Excel row 7 and data rows from row 8."""
    width = len(header) + extra_columns
    rows: list[list[str | None]] = [[None] * width for _ in range(2)]  # rows 5 and 6
    rows[0][-1] = "note"
    rows.append([*header, *([None] * extra_columns)])  # row 7
    rows.extend([*r, *([None] * (width - len(r)))] for r in data_rows)
    frame = pl.DataFrame(rows, schema=[f"column_{i}" for i in range(width)], orient="row")
    sheet = SheetData("S", frame, first_row=5, dimension="A4:Z99")
    return sheet, detect_header(sheet, expected, search_rows=30, min_match=0.8)


def test_ac3_trailing_fully_empty_rows_are_dropped_and_counted() -> None:
    sheet, info = synthetic_sheet(
        [["a", "b", "1", "2", "3"], ["c", "d", "4", "5", "6"],
         [None] * 5, ["", None, "", None, ""], [None] * 5]
    )
    built = build_bronze_frame(sheet, info, "s.xlsx", "h" * 64, "t")
    assert built.data_rows == 2
    assert built.dropped_trailing_rows == 3
    assert built.frame.height == 2
    assert built.frame["_source_row"].to_list() == ["8", "9"]


def test_ac3_a_blank_row_between_data_is_kept_not_dropped() -> None:
    sheet, info = synthetic_sheet(
        [["a", "b", "1", "2", "3"], [None] * 5, ["c", "d", "4", "5", "6"], [None] * 5]
    )
    built = build_bronze_frame(sheet, info, "s.xlsx", "h" * 64, "t")
    assert (built.data_rows, built.dropped_trailing_rows) == (3, 1)
    assert built.frame["_source_row"].to_list() == ["8", "9", "10"]


def test_ac3_a_row_of_spaces_is_data_not_an_empty_row() -> None:
    sheet, info = synthetic_sheet([["a", "b", "1", "2", "3"], [" ", " ", " ", " ", " "]])
    built = build_bronze_frame(sheet, info, "s.xlsx", "h" * 64, "t")
    assert (built.data_rows, built.dropped_trailing_rows) == (2, 0)


def test_ac3_a_sheet_with_no_data_rows_gives_an_empty_table() -> None:
    sheet, info = synthetic_sheet([[None] * 5, [None] * 5])
    built = build_bronze_frame(sheet, info, "s.xlsx", "h" * 64, "t")
    assert built.data_rows == 0 and built.frame.height == 0
    assert built.frame.columns == [*EXPECTED, *LINEAGE_COLUMNS]


def test_ac3_the_stray_row_is_kept_in_bronze(settings_for: SheetFactory) -> None:
    stray = [None, None, None, None, None]
    rows = {7: [*HEADER, "Change to Ctn"], 8: ["a", "b", 1, 2, 3, None], 9: [*stray, 1]}
    settings = settings_for(
        rows, extra={"expected_columns": [*EXPECTED, "Change_to_Ctn"]}
    )
    result = run_bronze(settings, NOW)
    frame = read_bronze(settings)
    assert frame.height == 2 == result.sheets[0].data_rows
    assert frame.row(1, named=True)["Change_to_Ctn"] == "1"
    assert frame["_source_row"].to_list() == ["8", "9"]


def test_ac3_bronze_rows_equal_the_data_rows_in_the_sheet(settings_for: SheetFactory) -> None:
    settings = settings_for(LAYOUT, styled_blank=(4, 12))
    result = run_bronze(settings, NOW)
    item = result.sheets[0]
    assert read_bronze(settings).height == item.data_rows == 3
    assert (item.header_row, item.data_start_row, item.dropped_trailing_rows) == (7, 8, 0)


def test_ac3_a_value_beyond_the_last_header_column_is_refused() -> None:
    sheet, info = synthetic_sheet([["a", "b", "1", "2", "3", "stray"]], extra_columns=1)
    with pytest.raises(BronzeError, match="to the right of the last header column"):
        build_bronze_frame(sheet, info, "s.xlsx", "h" * 64, "t")


def test_ac3_empty_extra_columns_beyond_the_header_are_ignored() -> None:
    sheet, info = synthetic_sheet([["a", "b", "1", "2", "3", None]], extra_columns=1)
    built = build_bronze_frame(sheet, info, "s.xlsx", "h" * 64, "t")
    assert built.frame.columns == [*EXPECTED, *LINEAGE_COLUMNS]


# AC4: re-run is idempotent ---------------------------------------------------------------------


def test_ac4_a_rerun_gives_identical_content_apart_from_ingested_at(
    settings_for: SheetFactory,
) -> None:
    settings = settings_for(LAYOUT, styled_blank=(4,))
    run_bronze(settings, NOW)
    first = read_bronze(settings)
    first_map = pl.read_parquet(settings.paths.bronze / COLUMN_MAP_FILE)
    run_bronze(settings, LATER)
    second = read_bronze(settings)
    assert first["_ingested_at"][0] != second["_ingested_at"][0]
    assert first.drop("_ingested_at").equals(second.drop("_ingested_at"))
    assert first_map.equals(pl.read_parquet(settings.paths.bronze / COLUMN_MAP_FILE))


def test_ac4_with_the_same_clock_the_files_are_identical_bytes(settings_for: SheetFactory) -> None:
    settings = settings_for(LAYOUT)
    run_bronze(settings, NOW)
    first = bronze_file(settings).read_bytes()
    run_bronze(settings, NOW)
    assert bronze_file(settings).read_bytes() == first


def test_ac4_a_rerun_replaces_the_file_and_leaves_no_temporary_files(
    settings_for: SheetFactory,
) -> None:
    settings = settings_for(LAYOUT)
    run_bronze(settings, NOW)
    run_bronze(settings, LATER)
    names = sorted(p.name for p in settings.paths.bronze.iterdir())
    assert names == [COLUMN_MAP_FILE, bronze_filename("sales.xlsx", "RAW SCJ SALES")]


def test_ac4_a_changed_source_gives_a_new_hash(settings_for: SheetFactory, build_workbook) -> None:
    settings = settings_for(LAYOUT)
    run_bronze(settings, NOW)
    before = read_bronze(settings)["_file_hash"][0]
    build_workbook(settings.paths.raw / "sales.xlsx", {**LAYOUT, 11: ["d", "e", 1, 2, 3]})
    run_bronze(settings, LATER)
    after = read_bronze(settings)
    assert after["_file_hash"][0] != before
    assert after.height == 4


# AC5: source unchanged, sheets from config, column map --------------------------------------------


def test_ac5_the_source_file_is_unchanged_by_the_build(settings_for: SheetFactory) -> None:
    settings = settings_for(LAYOUT)
    source = settings.paths.raw / "sales.xlsx"
    before = (hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns)
    run_bronze(settings, NOW)
    after = (hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns)
    assert after == before
    assert sorted(p.name for p in settings.paths.raw.iterdir()) == ["sales.xlsx"]


def test_ac5_bronze_is_never_written_inside_the_raw_folder(
    load_with, build_workbook
) -> None:
    settings = load_with(
        {
            "ingest": {"expected_columns": EXPECTED},
        }
    )
    build_workbook(settings.paths.raw / "sales.xlsx", LAYOUT)
    inside = settings.model_copy(
        update={"paths": settings.paths.model_copy(update={"bronze": settings.paths.raw / "out"})}
    )
    with pytest.raises(BronzeError, match="must not be inside paths.raw"):
        run_bronze(inside, NOW)
    assert sorted(p.name for p in settings.paths.raw.iterdir()) == ["sales.xlsx"]


def test_ac5_sheets_come_from_ingest_sheets(load_with, build_workbook) -> None:
    settings = load_with(
        {"ingest": {"expected_columns": EXPECTED, "sheets": ["Alpha", "Beta"]}}
    )
    build_workbook(settings.paths.raw / "a.xlsx", LAYOUT, sheet="Alpha")
    build_workbook(settings.paths.raw / "b.xlsx", LAYOUT, sheet="Beta")
    build_workbook(settings.paths.raw / "c.xlsx", LAYOUT, sheet="Gamma")
    result = run_bronze(settings, NOW)
    assert [s.sheet for s in result.sheets] == ["Alpha", "Beta"]
    assert sorted(p.name for p in settings.paths.bronze.glob("*__*.parquet")) == [
        "a__Alpha.parquet",
        "b__Beta.parquet",
    ]


def test_ac5_the_column_map_is_saved_for_every_sheet(load_with, build_workbook) -> None:
    settings = load_with({"ingest": {"expected_columns": EXPECTED, "sheets": ["Alpha", "Beta"]}})
    build_workbook(settings.paths.raw / "a.xlsx", LAYOUT, sheet="Alpha")
    build_workbook(settings.paths.raw / "b.xlsx", LAYOUT, sheet="Beta")
    run_bronze(settings, NOW)
    column_map = pl.read_parquet(settings.paths.bronze / COLUMN_MAP_FILE)
    assert column_map.columns == [
        "source_file", "sheet", "position", "source_column", "raw_name", "final_name",
    ]
    assert column_map.height == 10
    alpha = column_map.filter(pl.col("sheet") == "Alpha")
    assert alpha["source_file"].unique().to_list() == ["a.xlsx"]
    assert alpha["position"].to_list() == [1, 2, 3, 4, 5]
    assert alpha["source_column"].to_list() == ["A", "B", "C", "D", "E"]
    assert alpha["raw_name"].to_list() == HEADER
    assert alpha["final_name"].to_list() == EXPECTED


def test_ac5_nothing_is_written_when_a_later_sheet_fails(load_with, build_workbook) -> None:
    settings = load_with({"ingest": {"expected_columns": EXPECTED, "sheets": ["Alpha", "Missing"]}})
    build_workbook(settings.paths.raw / "a.xlsx", LAYOUT, sheet="Alpha")
    with pytest.raises(BronzeError, match="Missing"):
        run_bronze(settings, NOW)
    assert not settings.paths.bronze.exists() or not any(settings.paths.bronze.iterdir())


def test_ac5_a_sheet_without_the_expected_header_fails_and_writes_nothing(
    settings_for: SheetFactory,
) -> None:
    from revint.ingest.header import HeaderNotFoundError

    settings = settings_for({7: ["x", "y", "z", "u", "v"], 8: ["1"] * 5})
    with pytest.raises(HeaderNotFoundError, match="rows inspected"):
        run_bronze(settings, NOW)
    assert not settings.paths.bronze.exists() or not any(settings.paths.bronze.iterdir())


def test_ac5_a_missing_raw_folder_is_a_clear_error(load_with) -> None:
    settings = load_with({"ingest": {"expected_columns": EXPECTED}})
    with pytest.raises(BronzeError, match="raw folder not found"):
        run_bronze(settings, NOW)


# AC6: a locked or open Excel file is a clear error ---------------------------------------------


def test_ac6_an_excel_lock_file_is_detected(settings_for: SheetFactory) -> None:
    settings = settings_for(LAYOUT)
    workbook = settings.paths.raw / "sales.xlsx"
    assert excel_lock_file(workbook) is None
    (settings.paths.raw / "~$sales.xlsx").write_bytes(b"owner")
    assert excel_lock_file(workbook) == settings.paths.raw / "~$sales.xlsx"


def test_ac6_excel_shortens_the_lock_name_for_long_file_names(tmp_path: Path) -> None:
    # Excel replaces the first two characters of a long name with "~$".
    workbook = tmp_path / "FMCG SALES ANALYSIS.xlsx"
    workbook.write_bytes(b"x")
    (tmp_path / "~$CG SALES ANALYSIS.xlsx").write_bytes(b"owner")
    assert excel_lock_file(workbook) == tmp_path / "~$CG SALES ANALYSIS.xlsx"


def test_ac6_an_open_workbook_raises_a_clear_error_and_writes_nothing(
    settings_for: SheetFactory,
) -> None:
    settings = settings_for(LAYOUT)
    (settings.paths.raw / "~$sales.xlsx").write_bytes(b"owner")
    with pytest.raises(RawFileInUseError, match=r"sales\.xlsx.*open in Excel.*close it"):
        run_bronze(settings, NOW)
    assert not settings.paths.bronze.exists() or not any(settings.paths.bronze.iterdir())


def test_ac6_the_lock_file_is_not_mistaken_for_a_workbook(settings_for: SheetFactory) -> None:
    settings = settings_for(LAYOUT)
    (settings.paths.raw / "~$other.xlsx").write_bytes(b"owner")  # not the sales workbook's lock
    assert run_bronze(settings, NOW).sheets[0].data_rows == 3


def test_ac6_a_file_that_cannot_be_opened_is_reported_as_in_use(
    settings_for: SheetFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = settings_for(LAYOUT)
    real_open = Path.open

    def locked_open(self: Path, *args: Any, **kwargs: Any):
        if self.suffix == ".xlsx":
            raise PermissionError(13, "The process cannot access the file")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", locked_open)
    with pytest.raises(RawFileInUseError, match=r"locked by another process.*close it"):
        run_bronze(settings, NOW)


def test_ac6_execute_bronze_prints_a_message_with_no_traceback(
    settings_for: SheetFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = settings_for(LAYOUT)
    (settings.paths.raw / "~$sales.xlsx").write_bytes(b"owner")
    code = execute_bronze(settings, NOW)
    captured = capsys.readouterr()
    assert code == EXIT_RAW_FILE_IN_USE != 0
    assert "open in Excel" in captured.err and "sales.xlsx" in captured.err
    assert "Traceback" not in captured.err + captured.out
    assert captured.out == ""


def test_ac6_other_failures_exit_with_their_own_code_and_a_one_line_message(
    settings_for: SheetFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = settings_for({7: ["x", "y", "z", "u", "v"], 8: ["1"] * 5})
    code = execute_bronze(settings, NOW)
    captured = capsys.readouterr()
    assert code == EXIT_BRONZE_FAILED
    assert code != EXIT_RAW_FILE_IN_USE
    assert "no bronze file was written" in captured.err
    assert "Traceback" not in captured.err
    assert captured.err.count("\n") == 1


def test_ac6_a_successful_run_prints_counts_only(
    settings_for: SheetFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    secret = {7: HEADER, 8: ["SECRET-ID-777", "SECRET-NAME", 1, 2, 3]}
    settings = settings_for(secret)
    assert execute_bronze(settings, NOW) == 0
    out = capsys.readouterr().out
    assert "1 rows, 5 columns, 0 trailing empty rows dropped" in out
    assert "SECRET" not in out


# AC7: the CLI -------------------------------------------------------------------------------------


runner = CliRunner()


def test_ac7_build_bronze_runs_the_build(
    settings_for: SheetFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = settings_for(LAYOUT)
    settings_file = settings.paths.raw.parents[1] / "config" / "settings.yaml"
    monkeypatch.setattr(config, "DEFAULT_SETTINGS_FILE", settings_file)
    result = runner.invoke(app, ["build", "bronze"])
    assert result.exit_code == 0, result.output + str(result.exception)
    assert "bronze: RAW SCJ SALES: 3 rows, 5 columns" in result.output
    assert bronze_file(settings).is_file()
    assert (settings.paths.bronze / COLUMN_MAP_FILE).is_file()


def test_ac7_build_bronze_with_an_open_workbook_exits_non_zero(
    settings_for: SheetFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = settings_for(LAYOUT)
    (settings.paths.raw / "~$sales.xlsx").write_bytes(b"owner")
    monkeypatch.setattr(
        config, "DEFAULT_SETTINGS_FILE", settings.paths.raw.parents[1] / "config" / "settings.yaml"
    )
    result = runner.invoke(app, ["build", "bronze"])
    assert result.exit_code == EXIT_RAW_FILE_IN_USE
    assert "open in Excel" in result.output
    assert not settings.paths.bronze.exists()


@pytest.mark.parametrize("command", ["serve"])
def test_ac7_the_other_commands_stay_stubs(
    settings_for: SheetFactory, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    settings = settings_for(LAYOUT)
    monkeypatch.setattr(
        config, "DEFAULT_SETTINGS_FILE", settings.paths.raw.parents[1] / "config" / "settings.yaml"
    )
    result = runner.invoke(app, [command])
    assert result.exit_code == 3
    assert "not implemented" in result.output.lower()
    assert not settings.paths.bronze.exists(), "a stub must not build anything"


def test_ac7_invalid_settings_stop_build_bronze(
    settings_for: SheetFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = settings_for(LAYOUT)
    settings_file = settings.paths.raw.parents[1] / "config" / "settings.yaml"
    settings_file.write_text(settings_file.read_text(encoding="utf-8") + "typo_section: 1\n")
    monkeypatch.setattr(config, "DEFAULT_SETTINGS_FILE", settings_file)
    result = runner.invoke(app, ["build", "bronze"])
    assert result.exit_code == 1
    assert "typo_section" in result.output
    assert not settings.paths.bronze.exists()


# Logs hold counts only ---------------------------------------------------------------------------


def test_logs_carry_counts_and_no_cell_values(
    settings_for: SheetFactory, caplog: pytest.LogCaptureFixture
) -> None:
    settings = settings_for({7: HEADER, 8: ["SECRET-ID-777", "SECRET-NAME", 1, 2, 3]})
    with caplog.at_level(logging.DEBUG, logger="revint"):
        run_bronze(settings, NOW)
    assert "bronze sheet 1 rows, 5 columns, 0 trailing empty rows dropped" in caplog.text
    assert "SECRET" not in caplog.text


# Real file: runs only when data/ exists -----------------------------------------------------------


@pytest.mark.realdata
def test_ac1_real_file_bronze_has_the_confirmed_shape(tmp_path: Path) -> None:
    """Counts and structure only; no cell value is asserted or printed."""
    base = load_settings(env={})
    settings = load_settings(env={"REVINT_PATHS_BRONZE": str(tmp_path / "bronze")})
    assert settings.paths.raw == base.paths.raw
    workbook = next(settings.paths.raw.glob("SCJ SALES MASTER DATA YTD HP 2.xlsx"))
    before = (hashlib.sha256(workbook.read_bytes()).hexdigest(), workbook.stat().st_mtime_ns)

    result = run_bronze(settings, NOW)
    item = result.sheets[0]
    assert (item.header_row, item.data_start_row, item.columns) == (7, 8, 75)
    assert item.data_rows == 662_128, "rows 8 to 662135, the stray row included"
    assert item.dropped_trailing_rows == 0

    frame = pl.read_parquet(item.output)
    assert frame.height == 662_128
    assert frame.width == 75 + len(LINEAGE_COLUMNS)
    assert {str(t) for t in frame.dtypes} == {"String"}
    assert frame["_source_row"][0] == "8" and frame["_source_row"][-1] == "662135"
    assert frame["_file_hash"].n_unique() == 1
    assert frame.columns[:75] == settings.ingest.expected_columns
    after = (hashlib.sha256(workbook.read_bytes()).hexdigest(), workbook.stat().st_mtime_ns)
    assert after == before, "the source workbook is unchanged"
    assert pl.read_parquet(result.column_map).height == 75
