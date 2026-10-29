"""Profile the RAW SCJ SALES sheet (spec 01 section 10a).

Reads the workbook through `open_raw` and reports counts and aggregates only: header and
data rows, the stray row, distinct Void values, exact duplicates, free goods and the
number of distinct channel and branch labels. Nothing is mapped, guessed or written to
bronze. Run it with `uv run python -m revint.ingest.profile`.

Row values are never printed except the distinct Void values with their row counts
(spec 10a asks for them); label names stay hidden unless `--show-labels` is given.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

import polars as pl

from revint.config import ConfigError, Settings, load_settings
from revint.ingest.columns import final_column_names, normalise_name
from revint.ingest.excel import SheetData, find_workbook, read_sheet
from revint.ingest.raw import open_raw

logger = logging.getLogger(__name__)

BLANK = "(blank)"
VOID_COLUMN = "Void"  # spec 01 S6
STRAY_COLUMN = "Change_to_Ctn"  # spec 01 D1: the stray row has only this cell filled, with 1
QUANTITY_COLUMN = "Quantity(PCS)"  # decided on issue #31 (S7 free goods)
EXPECTED_COLUMN_COUNT = 75  # spec 01 D2
DOCS_DUPLICATES = 556  # the figure quoted in the docs (spec 01 S5)
MAX_VALUES_SHOWN = 50
_ROW = "_excel_row"
_FILLED = "_filled"
_PLAIN_YAML = re.compile(r"[A-Za-z_][A-Za-z0-9_()/%.\-]*")
_YAML_SPECIAL = {"y", "n", "yes", "no", "on", "off", "true", "false", "null"}


class ProfileError(Exception):
    """The sheet could not be profiled."""


@dataclass(frozen=True)
class VoidValue:
    value: str
    rows: int


@dataclass(frozen=True)
class LabelProfile:
    column: str
    kind: str
    distinct: int
    counts: dict[str, int]


@dataclass(frozen=True)
class ProfileResult:
    sheet: str
    header_row: int
    data_start_row: int
    last_data_row: int
    column_count: int
    expected_column_count: int | None
    column_count_matches: bool | None
    data_row_count: int
    blank_data_rows: int
    raw_header: list[str]
    final_names: list[str]
    stray_candidates: list[int]
    stray_exactly_one: bool
    void_values: list[VoidValue]
    void_mapping_note: str
    duplicate_groups: int
    duplicate_extra_rows: int
    duplicate_docs_figure: int | None
    duplicate_difference_from_docs: int | None
    quantity_column: str | None
    free_goods: dict[str, int]
    blank_value_with_qty: dict[str, int]
    non_numeric_counts: dict[str, int]
    labels: list[LabelProfile]

    @property
    def first_data_row(self) -> int:
        return self.data_start_row


def _is_blank(value: object) -> bool:
    return value is None or str(value).strip() == ""


def locate_header(sheet: SheetData, search_rows: int) -> tuple[int, list[str]]:
    """The header row: the fullest row among Excel rows 1 to `search_rows`.

    It must fill at least half of the sheet's columns, so a lone value above the header
    is not mistaken for it. Returns the Excel row number and the raw header cells (with
    their spaces) up to the last filled one.
    """
    width = sheet.frame.width
    needed = (width + 1) // 2
    best_row, best_count = None, 0
    for excel_row in range(sheet.first_row, min(sheet.last_row, search_rows) + 1):
        count = sum(1 for v in sheet.frame.row(excel_row - sheet.first_row) if not _is_blank(v))
        if count > best_count:
            best_row, best_count = excel_row, count
    if best_row is None or best_count < max(needed, 1):
        raise ProfileError(
            f"no header row found in the first {search_rows} rows "
            f"(a header fills at least half of the {width} columns)"
        )
    cells = list(sheet.frame.row(best_row - sheet.first_row))
    while cells and _is_blank(cells[-1]):
        cells.pop()
    return best_row, [str(c) for c in cells]


def _resolve(names: list[str], wanted: str) -> str:
    """The final name for `wanted`, given either as a final or a raw name."""
    if wanted in names:
        return wanted
    normal = normalise_name(wanted)
    if normal in names:
        return normal
    raise ProfileError(f"column '{wanted}' not found in the header")


def _value_counts(frame: pl.DataFrame, column: str) -> dict[str, int]:
    counts = (
        frame.select(pl.col(column).fill_null(BLANK).alias("v"))
        .group_by("v")
        .len()
        .sort(["len", "v"], descending=[True, False])
    )
    return dict(zip(counts["v"].to_list(), counts["len"].to_list(), strict=True))


def _numeric(column: str) -> pl.Expr:
    return pl.col(column).str.strip_chars().cast(pl.Float64, strict=False)


def profile_frame(
    sheet: SheetData,
    header_search_rows: int,
    expected_columns: int | None = None,
    docs_duplicates: int | None = None,
    amount_columns: Sequence[str] = (),
    quantity_column: str | None = None,
    channel_columns: Sequence[str] = (),
    branch_columns: Sequence[str] = (),
    void_column: str = VOID_COLUMN,
    stray_column: str = STRAY_COLUMN,
) -> ProfileResult:
    """Profile a sheet that is already loaded as text. Counts and aggregates only."""
    header_row, raw_header = locate_header(sheet, header_search_rows)
    try:
        names = final_column_names(raw_header)
    except ValueError as exc:
        raise ProfileError(str(exc)) from exc
    void = _resolve(names, void_column)
    stray = _resolve(names, stray_column)

    body = sheet.frame.slice(header_row - sheet.first_row + 1).select(
        sheet.frame.columns[: len(names)]
    )
    body.columns = names
    body = body.with_columns(
        [
            pl.when(pl.col(c).is_null() | (pl.col(c).str.strip_chars() == ""))
            .then(None)
            .otherwise(pl.col(c))
            .alias(c)
            for c in names
        ]
    ).with_columns(
        (pl.int_range(pl.len(), dtype=pl.Int64) + header_row + 1).alias(_ROW),
        pl.sum_horizontal([pl.col(c).is_not_null().cast(pl.UInt32) for c in names]).alias(_FILLED),
    )

    is_stray = ((pl.col(_FILLED) == 1) & (_numeric(stray) == 1.0)).fill_null(False)
    candidates = body.filter(is_stray)[_ROW].to_list()
    rest = body.filter(~is_stray)
    filled_rows = rest.filter(pl.col(_FILLED) > 0)
    last_data_row = int(filled_rows[_ROW].max()) if filled_rows.height else header_row
    analysed = rest.filter(pl.col(_ROW) <= last_data_row)

    void_counts = _value_counts(analysed, void)
    void_values = [VoidValue(value, rows) for value, rows in void_counts.items()]

    groups = analysed.select(names).group_by(names).len().filter(pl.col("len") > 1)
    duplicate_groups = groups.height
    duplicate_extra = int(groups["len"].sum() or 0) - duplicate_groups if groups.height else 0

    free_goods: dict[str, int] = {}
    blank_with_qty: dict[str, int] = {}
    non_numeric: dict[str, int] = {}
    resolved_quantity = _resolve(names, quantity_column) if quantity_column else None
    for wanted in amount_columns:
        amount = _resolve(names, wanted)
        non_numeric[amount] = analysed.filter(
            pl.col(amount).is_not_null() & _numeric(amount).is_null()
        ).height
        if resolved_quantity is not None:
            has_qty = _numeric(resolved_quantity) > 0
            free_goods[amount] = analysed.filter(has_qty & (_numeric(amount) == 0)).height
            blank_with_qty[amount] = analysed.filter(has_qty & pl.col(amount).is_null()).height

    labels = [
        LabelProfile(column, kind, len(counts), counts)
        for kind, wanted_columns in (("channel", channel_columns), ("branch", branch_columns))
        for column in (_resolve(names, w) for w in wanted_columns)
        for counts in (_value_counts(analysed, column),)
    ]

    result = ProfileResult(
        sheet=sheet.name,
        header_row=header_row,
        data_start_row=header_row + 1,
        last_data_row=last_data_row,
        column_count=len(names),
        expected_column_count=expected_columns,
        column_count_matches=None if expected_columns is None else len(names) == expected_columns,
        data_row_count=analysed.height,
        blank_data_rows=analysed.filter(pl.col(_FILLED) == 0).height,
        raw_header=raw_header,
        final_names=names,
        stray_candidates=[int(r) for r in candidates],
        stray_exactly_one=len(candidates) == 1,
        void_values=void_values,
        void_mapping_note="not mapped: a human supplies void.value_map",
        duplicate_groups=duplicate_groups,
        duplicate_extra_rows=duplicate_extra,
        duplicate_docs_figure=docs_duplicates,
        duplicate_difference_from_docs=(
            None if docs_duplicates is None else duplicate_extra - docs_duplicates
        ),
        quantity_column=resolved_quantity,
        free_goods=free_goods,
        blank_value_with_qty=blank_with_qty,
        non_numeric_counts=non_numeric,
        labels=labels,
    )
    logger.info(
        "profiled %d data rows, %d columns, %d stray candidates, %d duplicate copies",
        result.data_row_count,
        result.column_count,
        len(candidates),
        duplicate_extra,
    )
    return result


def profile_workbook(
    settings: Settings,
    raw_dir: Path | None = None,
    sheet: str | None = None,
    expected_columns: int | None = EXPECTED_COLUMN_COUNT,
    docs_duplicates: int | None = DOCS_DUPLICATES,
) -> ProfileResult:
    """Find the workbook that has the sheet under the raw folder and profile the sheet.

    Amount columns are every column with AMOUNT in its name, so the result does not depend
    on which six are chosen; channel and branch columns are those with `channel` or `branch`
    in the name.
    """
    folder = raw_dir if raw_dir is not None else settings.paths.raw
    sheet_name = sheet if sheet is not None else settings.ingest.sheets[0]
    workbook = find_workbook(folder, sheet_name)
    with open_raw(Path(workbook.name), folder) as handle:
        data = handle.read()
    loaded = read_sheet(data, sheet_name)
    search_rows = settings.ingest.header_search_rows
    _, raw_header = locate_header(loaded, search_rows)
    try:
        names = final_column_names(raw_header)
    except ValueError as exc:
        raise ProfileError(str(exc)) from exc
    return profile_frame(
        loaded,
        search_rows,
        expected_columns=expected_columns,
        docs_duplicates=docs_duplicates,
        amount_columns=[n for n in names if "amount" in n.casefold()],
        quantity_column=QUANTITY_COLUMN if QUANTITY_COLUMN in names else None,
        channel_columns=[n for n in names if "channel" in n.casefold()],
        branch_columns=[n for n in names if "branch" in n.casefold()],
    )


def _yaml_item(name: str) -> str:
    plain = _PLAIN_YAML.fullmatch(name) and name.casefold() not in _YAML_SPECIAL
    return name if plain else json.dumps(name, ensure_ascii=False)


def format_report(result: ProfileResult, show_labels: bool = False) -> str:
    """The profile as text: counts and aggregates, plus the expected_columns YAML block."""
    out = [f"{result.sheet} profile (counts and aggregates only)"]
    out.append(f"header row: {result.header_row}")
    out.append(f"data starts: row {result.data_start_row}")
    match = {True: "match", False: "MISMATCH", None: "not checked"}[result.column_count_matches]
    suffix = (
        f" (expected {result.expected_column_count}: {match})"
        if result.expected_column_count is not None
        else ""
    )
    out.append(f"columns: {result.column_count:,}{suffix}")
    out.append(
        f"data rows: {result.data_row_count:,} "
        f"(rows {result.data_start_row} to {result.last_data_row}; "
        f"{result.blank_data_rows:,} blank rows between)"
    )
    if not result.stray_candidates:
        out.append("stray row candidates: none")
    else:
        rows = ", ".join(str(r) for r in result.stray_candidates)
        noun = "row" if len(result.stray_candidates) == 1 else "rows"
        found = len(result.stray_candidates)
        verdict = "exactly one" if result.stray_exactly_one else f"{found} found"
        out.append(f"stray row candidates: {noun} {rows} ({verdict})")
    line = (
        f"exact duplicates: {result.duplicate_extra_rows:,} extra copies "
        f"in {result.duplicate_groups:,} groups"
    )
    if result.duplicate_docs_figure is not None:
        line += (
            f" (docs: about {result.duplicate_docs_figure:,}; "
            f"difference {result.duplicate_difference_from_docs:+,})"
        )
    out.append(line)

    out.append(
        f"Void values ({len(result.void_values):,} distinct; {result.void_mapping_note}):"
    )
    for item in result.void_values[:MAX_VALUES_SHOWN]:
        out.append(f"  {item.value}: {item.rows:,}")
    if len(result.void_values) > MAX_VALUES_SHOWN:
        out.append(f"  ... {len(result.void_values) - MAX_VALUES_SHOWN} more values not shown")

    if result.quantity_column is None:
        out.append("free goods: not counted (no quantity column found)")
    else:
        out.append(f"free goods (amount = 0 and {result.quantity_column} > 0), rows per column:")
        for column, count in result.free_goods.items():
            out.append(
                f"  {column}: {count:,} "
                f"(blank with quantity: {result.blank_value_with_qty[column]:,}; "
                f"not a number: {result.non_numeric_counts[column]:,})"
            )

    for kind in ("channel", "branch"):
        profiles = [lab for lab in result.labels if lab.kind == kind]
        if not profiles:
            continue
        out.append(f"{kind} columns:")
        for lab in profiles:
            out.append(f"  {lab.column}: {lab.distinct:,} distinct labels")
            if show_labels:
                for value, rows in list(lab.counts.items())[:MAX_VALUES_SHOWN]:
                    out.append(f"    {value}: {rows:,}")

    out.append("expected_columns:")
    out.extend(f"  - {_yaml_item(name)}" for name in result.final_names)
    return "\n".join(out) + "\n"


def result_to_dict(result: ProfileResult, show_labels: bool = False) -> dict[str, object]:
    payload = asdict(result)
    if not show_labels:
        for label in payload["labels"]:
            label["counts"] = {}
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m revint.ingest.profile",
        description="Profile the RAW SCJ SALES sheet: counts and aggregates only.",
    )
    parser.add_argument(
        "--raw-dir", type=Path, help="folder with the workbooks (default: paths.raw)"
    )
    parser.add_argument("--sheet", help="sheet name (default: the first of ingest.sheets)")
    parser.add_argument("--json", type=Path, help="also write the result to this JSON file")
    parser.add_argument(
        "--show-labels", action="store_true", help="print channel and branch label names"
    )
    parser.add_argument("--expect-columns", type=int, default=EXPECTED_COLUMN_COUNT)
    parser.add_argument("--docs-duplicates", type=int, default=DOCS_DUPLICATES)
    args = parser.parse_args(argv)

    stdout = sys.stdout
    if hasattr(stdout, "reconfigure"):
        stdout.reconfigure(encoding="utf-8")  # column names include non-ASCII text
    try:
        settings = load_settings()
        folder = args.raw_dir if args.raw_dir is not None else settings.paths.raw
        if not folder.is_dir():
            raise ProfileError(f"raw folder not found: {folder}")
        result = profile_workbook(
            settings, folder, args.sheet, args.expect_columns, args.docs_duplicates
        )
    except (ConfigError, ProfileError, ValueError) as exc:
        print(f"profile: {exc}", file=sys.stderr)
        return 1
    print(format_report(result, args.show_labels), end="")
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(result_to_dict(result, args.show_labels), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
