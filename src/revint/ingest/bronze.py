"""Bronze ingestion: one sheet to all-text Parquet with lineage (spec 01 B1, B4 to B7).

For every sheet in `ingest.sheets` the build finds the workbook under `paths.raw`, reads it
only through `open_raw`, finds the header (spec 01 B2), and writes
`<paths.bronze>/<source>__<sheet>.parquet`. Every column, lineage columns included, is text.
Source values are kept exactly as the Excel reader gives them: nothing is trimmed, cast or
cleaned. `bronze_column_map.parquet` records the raw and final name of every column.

All sheets are read and checked before any file is written, and each file is written to a
temporary name first, so a failure leaves no half-written output. Logs and messages hold
counts and file names, never cell values.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from revint.config import Settings
from revint.ingest.excel import SheetData, find_workbook, read_sheet
from revint.ingest.header import HeaderError, HeaderInfo, detect_header_from_settings
from revint.ingest.raw import RawAccessError, RawFileInUseError, open_raw

logger = logging.getLogger(__name__)

LINEAGE_COLUMNS = ("_source_file", "_sheet", "_source_row", "_ingested_at", "_file_hash")
COLUMN_MAP_FILE = "bronze_column_map.parquet"
EXIT_BRONZE_FAILED = 4
EXIT_RAW_FILE_IN_USE = 6


class BronzeError(Exception):
    """The bronze build could not be completed."""


@dataclass(frozen=True)
class BronzeFrame:
    frame: pl.DataFrame
    data_rows: int
    dropped_trailing_rows: int


@dataclass(frozen=True)
class SheetResult:
    sheet: str
    workbook: str
    output: Path
    header_row: int
    data_start_row: int
    data_rows: int
    dropped_trailing_rows: int
    columns: int  # source columns, without the lineage columns
    file_hash: str


@dataclass(frozen=True)
class BronzeResult:
    sheets: tuple[SheetResult, ...]
    column_map: Path


@dataclass(frozen=True)
class _Prepared:
    result: SheetResult
    frame: pl.DataFrame
    column_map: pl.DataFrame


def _safe(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_")


def bronze_filename(source_file: str, sheet: str) -> str:
    """`<source>__<sheet>.parquet` with anything but letters, digits and `._-` as `_`."""
    return f"{_safe(Path(source_file).stem)}__{_safe(sheet)}.parquet"


def excel_lock_file(workbook: Path) -> Path | None:
    """The `~$` owner file Excel keeps next to a workbook that is open, if present."""
    for name in (f"~${workbook.name}", f"~${workbook.name[2:]}"):
        candidate = workbook.with_name(name)
        if candidate.exists():
            return candidate
    return None


def build_bronze_frame(
    sheet: SheetData,
    info: HeaderInfo,
    source_file: str,
    file_hash: str,
    ingested_at: str,
) -> BronzeFrame:
    """The bronze table for one sheet: the data rows under the header, plus lineage.

    Rows are kept as read, including blank rows between data rows and the stray row.
    Only trailing rows that are completely empty (null or empty text in every cell) are
    dropped, and counted. A value to the right of the last header column is refused.
    """
    names = info.final_names
    clash = [n for n in names if n in LINEAGE_COLUMNS]
    if clash:
        raise BronzeError(f"column names clash with lineage columns: {', '.join(clash)}")
    width = len(names)
    body = sheet.frame.slice(info.header_row - sheet.first_row + 1)

    if sheet.frame.width > width:
        beyond = body.select(sheet.frame.columns[width:])
        filled = [
            (pl.col(c).is_not_null() & (pl.col(c) != "")).cast(pl.UInt32) for c in beyond.columns
        ]
        cells = beyond.select(pl.sum_horizontal(filled).sum()).item()
        if cells:
            raise BronzeError(
                f"{cells} cells hold values to the right of the last header column "
                f"(column {width}); they would be lost"
            )
    body = body.select(sheet.frame.columns[:width])
    body.columns = names

    empty = body.select(
        pl.all_horizontal([pl.col(c).is_null() | (pl.col(c) == "") for c in names]).alias("e")
    )["e"]
    filled = empty.not_().arg_true()
    keep = int(filled.max()) + 1 if len(filled) else 0
    dropped = body.height - keep
    body = body.slice(0, keep)

    frame = body.with_columns(
        pl.lit(source_file).alias("_source_file"),
        pl.lit(info.sheet).alias("_sheet"),
        (pl.int_range(pl.len(), dtype=pl.Int64) + info.data_start_row)
        .cast(pl.String)
        .alias("_source_row"),
        pl.lit(ingested_at).alias("_ingested_at"),
        pl.lit(file_hash).alias("_file_hash"),
    )
    return BronzeFrame(frame=frame, data_rows=keep, dropped_trailing_rows=dropped)


def _read_workbook(raw_dir: Path, sheet: str) -> tuple[Path, bytes]:
    try:
        workbook = find_workbook(raw_dir, sheet)
    except ValueError as exc:
        raise BronzeError(str(exc)) from exc
    lock = excel_lock_file(workbook)
    if lock is not None:
        raise RawFileInUseError(
            f"raw workbook {workbook.name} appears to be open in Excel "
            f"(lock file {lock.name} exists); close it and run the build again"
        )
    with open_raw(Path(workbook.name), raw_dir) as handle:
        return workbook, handle.read()


def _prepare(settings: Settings, sheet: str, ingested_at: str) -> _Prepared:
    workbook, data = _read_workbook(settings.paths.raw, sheet)
    file_hash = hashlib.sha256(data).hexdigest()
    try:
        loaded = read_sheet(data, sheet)
    except ValueError as exc:
        raise BronzeError(f"sheet '{sheet}' in {workbook.name}: {exc}") from exc
    del data
    info = detect_header_from_settings(loaded, settings)
    built = build_bronze_frame(loaded, info, workbook.name, file_hash, ingested_at)
    output = settings.paths.bronze / bronze_filename(workbook.name, sheet)
    column_map = info.to_frame().select(
        pl.lit(workbook.name).alias("source_file"),
        pl.lit(sheet).alias("sheet"),
        pl.all(),
    )
    result = SheetResult(
        sheet=sheet,
        workbook=workbook.name,
        output=output,
        header_row=info.header_row,
        data_start_row=info.data_start_row,
        data_rows=built.data_rows,
        dropped_trailing_rows=built.dropped_trailing_rows,
        columns=len(info.final_names),
        file_hash=file_hash,
    )
    logger.info(
        "bronze sheet %d rows, %d columns, %d trailing empty rows dropped",
        built.data_rows,
        len(info.final_names),
        built.dropped_trailing_rows,
    )
    return _Prepared(result=result, frame=built.frame, column_map=column_map)


def _write_parquet(frame: pl.DataFrame, target: Path) -> None:
    """Write through a temporary file so a failure never leaves a partial output."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    try:
        frame.write_parquet(temporary, compression="zstd")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def run_bronze(settings: Settings, now: datetime | None = None) -> BronzeResult:
    """Build bronze for every sheet in `ingest.sheets`.

    Raises `RawFileInUseError` for a locked or open workbook, `HeaderError` if a header is
    not found, and `BronzeError` for any other problem. Nothing is written unless every
    sheet could be read and checked.
    """
    raw_dir = settings.paths.raw
    bronze_dir = settings.paths.bronze
    if not raw_dir.is_dir():
        raise BronzeError(f"raw folder not found: {raw_dir}")
    resolved_raw = raw_dir.resolve()
    resolved_out = bronze_dir.resolve()
    if resolved_out == resolved_raw or resolved_out.is_relative_to(resolved_raw):
        raise BronzeError(f"paths.bronze must not be inside paths.raw: {bronze_dir}")

    stamp = (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    prepared = [_prepare(settings, sheet, stamp) for sheet in settings.ingest.sheets]
    outputs = [p.result.output.name for p in prepared]
    if len(set(outputs)) != len(outputs):
        raise BronzeError("two sheets would write the same bronze file name")

    for item in prepared:
        _write_parquet(item.frame, item.result.output)
    column_map = bronze_dir / COLUMN_MAP_FILE
    _write_parquet(pl.concat([p.column_map for p in prepared]), column_map)
    logger.info("bronze wrote %d sheets and the column map", len(prepared))
    return BronzeResult(sheets=tuple(p.result for p in prepared), column_map=column_map)


def execute_bronze(
    settings: Settings, now: datetime | None = None, sink: list[BronzeResult] | None = None
) -> int:
    """Run the bronze build for the command line: print the outcome, return an exit code.

    A caller that wants the counts passes a list as `sink`; the result is appended to it.
    """
    try:
        result = run_bronze(settings, now)
    except RawFileInUseError as exc:
        print(f"bronze: {exc}", file=sys.stderr)
        return EXIT_RAW_FILE_IN_USE
    except (BronzeError, HeaderError, RawAccessError, FileNotFoundError, OSError) as exc:
        print(f"bronze failed: {exc}; no bronze file was written", file=sys.stderr)
        return EXIT_BRONZE_FAILED
    except pl.exceptions.PolarsError as exc:
        print(f"bronze failed: {type(exc).__name__}; no bronze file was written", file=sys.stderr)
        return EXIT_BRONZE_FAILED
    if sink is not None:
        sink.append(result)
    for item in result.sheets:
        print(
            f"bronze: {item.sheet}: {item.data_rows:,} rows, {item.columns} columns, "
            f"{item.dropped_trailing_rows:,} trailing empty rows dropped -> {item.output.name}"
        )
    print(f"bronze: column map -> {result.column_map.name}")
    return 0
