"""Find the header row of a sheet and name its columns (spec 01 B2, B3).

The header is the first row within the first `ingest.header_search_rows` Excel rows in which
at least `ingest.header_min_match` of the expected column names (`ingest.expected_columns`)
are present. Names are compared after the naming rule, so surrounding spaces and the
`_1`, `_2` suffixes are accounted for. Nothing about the layout is hard-coded: the known
layout of RAW SCJ SALES (header on row 7, data from row 8) is only asserted in tests.

The result carries the source-position to final-name map that `bronze_column_map` will
store. This module reads a sheet that is already loaded; it writes nothing. Messages and
logs hold row numbers and counts, never cell values.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

import polars as pl

from revint.config import Settings
from revint.ingest.columns import final_column_names
from revint.ingest.excel import SheetData, column_letter

logger = logging.getLogger(__name__)


class HeaderError(Exception):
    """The header could not be determined, or the configuration cannot find one."""


class HeaderNotFoundError(HeaderError):
    """No row within the search range matched enough of the expected columns."""

    def __init__(
        self,
        message: str,
        rows_inspected: list[int],
        best_row: int | None,
        best_matched: int,
    ) -> None:
        super().__init__(message)
        self.rows_inspected = rows_inspected
        self.best_row = best_row
        self.best_matched = best_matched


@dataclass(frozen=True)
class ColumnEntry:
    """One header cell: its 1-based position, Excel column letter, raw and final name."""

    position: int
    source_column: str
    raw_name: str
    final_name: str


@dataclass(frozen=True)
class HeaderInfo:
    sheet: str
    header_row: int
    data_start_row: int
    matched: int
    expected: int
    column_map: tuple[ColumnEntry, ...]

    @property
    def raw_names(self) -> list[str]:
        return [entry.raw_name for entry in self.column_map]

    @property
    def final_names(self) -> list[str]:
        return [entry.final_name for entry in self.column_map]

    def to_frame(self) -> pl.DataFrame:
        """The map as a table: the content of `bronze_column_map`."""
        return pl.DataFrame(
            {
                "position": [e.position for e in self.column_map],
                "source_column": [e.source_column for e in self.column_map],
                "raw_name": [e.raw_name for e in self.column_map],
                "final_name": [e.final_name for e in self.column_map],
            },
            schema={
                "position": pl.Int64,
                "source_column": pl.String,
                "raw_name": pl.String,
                "final_name": pl.String,
            },
        )


def _cells(sheet: SheetData, excel_row: int) -> list[str]:
    """The cells of one Excel row as text; empty cells are empty strings."""
    row = sheet.frame.row(excel_row - sheet.first_row)
    return ["" if value is None else str(value) for value in row]


def _trim_trailing_blanks(cells: list[str]) -> list[str]:
    end = len(cells)
    while end and not cells[end - 1].strip():
        end -= 1
    return cells[:end]


def _match_count(cells: Sequence[str], expected: Sequence[str]) -> int:
    """How many expected names occur among the row's cells (names compared case-sensitively
    after the naming rule, with `_1`, `_2` suffixes applied to repeats)."""
    named = [c for c in cells if c.strip()]
    if not named:
        return 0
    present = set(final_column_names(named))
    return sum(1 for name in expected if name in present)


def _percent(matched: int, expected: int) -> int:
    return round(matched * 100 / expected)


def _not_found(
    sheet: SheetData, inspected: list[int], best_row: int | None, best: int, expected: int,
    min_match: float,
) -> HeaderNotFoundError:
    rows = (
        f"rows inspected: {inspected[0]} to {inspected[-1]} ({len(inspected)} rows)"
        if inspected
        else "rows inspected: none"
    )
    if best_row is None or best == 0:
        detail = "no row had any expected column"
    else:
        detail = (
            f"best match: {best} of {expected} expected columns "
            f"({_percent(best, expected)}%) at row {best_row}"
        )
    message = (
        f"no header found in sheet '{sheet.name}': {rows}; {detail}; "
        f"needs at least {round(min_match * 100)}%"
    )
    return HeaderNotFoundError(message, inspected, best_row, best)


def detect_header(
    sheet: SheetData,
    expected_columns: Sequence[str],
    search_rows: int,
    min_match: float,
) -> HeaderInfo:
    """Find the header row of `sheet`.

    Rows are numbered as in Excel. Only rows 1 to `search_rows` that exist in the sheet are
    inspected. Raises `HeaderNotFoundError` (listing the rows inspected) if no row has at
    least `min_match` of `expected_columns`, and `HeaderError` if the configuration gives no
    expected columns or the header has an empty cell between names.
    """
    expected = list(expected_columns)
    if not expected:
        raise HeaderError(
            "ingest.expected_columns is empty: run the profiler (python -m "
            "revint.ingest.profile) and set it before detecting a header"
        )
    needed = min_match * len(expected)
    last_row = min(sheet.last_row, search_rows)
    inspected = list(range(sheet.first_row, last_row + 1)) if last_row >= sheet.first_row else []

    best_row: int | None = None
    best = 0
    for excel_row in inspected:
        matched = _match_count(_cells(sheet, excel_row), expected)
        if matched > best:
            best_row, best = excel_row, matched
        if matched >= needed and matched > 0:
            return _build(sheet, excel_row, matched, len(expected))
    raise _not_found(sheet, inspected, best_row, best, len(expected), min_match)


def _build(sheet: SheetData, header_row: int, matched: int, expected: int) -> HeaderInfo:
    raw = _trim_trailing_blanks(_cells(sheet, header_row))
    try:
        names = final_column_names(raw)
    except ValueError as exc:
        raise HeaderError(f"header row {header_row}: {exc}") from exc
    entries = tuple(
        ColumnEntry(position, column_letter(position), raw_name, final)
        for position, (raw_name, final) in enumerate(zip(raw, names, strict=True), start=1)
    )
    logger.info(
        "header row %d: %d of %d expected columns matched, %d columns",
        header_row,
        matched,
        expected,
        len(entries),
    )
    return HeaderInfo(
        sheet=sheet.name,
        header_row=header_row,
        data_start_row=header_row + 1,
        matched=matched,
        expected=expected,
        column_map=entries,
    )


def detect_header_from_settings(sheet: SheetData, settings: Settings) -> HeaderInfo:
    """`detect_header` with the search range, threshold and expected names from config."""
    return detect_header(
        sheet,
        settings.ingest.expected_columns,
        settings.ingest.header_search_rows,
        settings.ingest.header_min_match,
    )


__all__ = [
    "ColumnEntry",
    "HeaderError",
    "HeaderInfo",
    "HeaderNotFoundError",
    "detect_header",
    "detect_header_from_settings",
]
