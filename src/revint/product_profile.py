"""Profile the candidate brand and category columns of the built bronze file (spec 02 section 12).

Story #73 chooses the product hierarchy from evidence. For every candidate column this reports
three counts: how many distinct values it has, how many rows are blank, and how many product
codes map to more than one value. Run it with `uv run python -m revint.product_profile`.

It reads the bronze Parquet file only and writes nothing. Output is counts: no product, brand,
category or customer value is printed, logged or returned. A cell is blank the way silver
treats it (NULL, empty, or only spaces, tabs, line breaks or non-breaking spaces), and a value
is compared as trimmed text, which is what silver stores.
"""

from __future__ import annotations

import argparse
import itertools
import json
import logging
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

import duckdb

from revint.config import ConfigError, Settings, load_settings
from revint.silver import SilverError, find_bronze_file

logger = logging.getLogger(__name__)

CANDIDATE_COLUMNS = (
    "Internal_Category",
    "Actual_Brands_1",
    "Actual_Brands_2",
    "SCJ_SEGMENT",
    "FRAGRANCES",
    "Size",
)

# The rule dim_product (story E2-7) uses when one product code has several values in a column.
VALUE_RULE = (
    "A product code with several values in a column takes the most frequent value; a tie goes "
    "to the value on the lowest _source_row."
)

EXIT_PROFILE_FAILED = 4
_BLANKS = "' ' || chr(9) || chr(10) || chr(13) || chr(160)"


class ProfileError(Exception):
    """The product profile could not be made."""


@dataclass(frozen=True)
class CandidateProfile:
    column: str
    distinct: int
    blank_rows: int
    conflict_codes: int
    tied_codes: int
    codes_without_value: int


@dataclass(frozen=True)
class ProductProfile:
    code_column: str
    name_column: str
    rows: int
    codes: int
    blank_code_rows: int
    name_conflict_codes: int
    candidates: tuple[CandidateProfile, ...]
    identical_pairs: tuple[tuple[str, str], ...]

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["identical_pairs"] = [list(pair) for pair in self.identical_pairs]
        return data


def _text(column: str) -> str:
    """The trimmed text of a column, NULL when blank (the way silver stores it)."""
    return f"nullif(trim(\"{column}\", {_BLANKS}), '')"


def _check_columns(path: str, needed: Sequence[str]) -> None:
    con = duckdb.connect()
    try:
        have = {
            row[0]
            for row in con.execute("describe select * from read_parquet(?)", [path]).fetchall()
        }
    finally:
        con.close()
    missing = [column for column in needed if column not in have]
    if missing:
        raise ProfileError(f"bronze file lacks columns: {', '.join(missing)}")


def _candidate(
    con: duckdb.DuckDBPyConnection, path: str, code: str, column: str
) -> CandidateProfile:
    distinct, blank = con.execute(
        f"select count(distinct {_text(column)}), count(*) filter (where {_text(column)} is null) "
        "from read_parquet(?)",
        [path],
    ).fetchone()
    conflict, tied, without = con.execute(
        f"""
        with counted as (
            select {_text(code)} as code, {_text(column)} as value, count(*) as n
            from read_parquet(?)
            where {_text(code)} is not null
            group by 1, 2
        ),

        per_code as (
            select
                code,
                count(value) as values_present,
                max(n) filter (where value is not null) as top,
                count(*) filter (where value is not null) as distinct_values,
                count(*) filter (where value is not null and n = (
                    select max(c2.n) from counted as c2
                    where c2.code = counted.code and c2.value is not null
                )) as at_top
            from counted
            group by code
        )

        select
            count(*) filter (where distinct_values > 1),
            count(*) filter (where distinct_values > 1 and at_top > 1),
            count(*) filter (where values_present = 0)
        from per_code
        """,
        [path],
    ).fetchone()
    return CandidateProfile(
        column=column,
        distinct=int(distinct),
        blank_rows=int(blank),
        conflict_codes=int(conflict),
        tied_codes=int(tied),
        codes_without_value=int(without),
    )


def _identical_pairs(
    con: duckdb.DuckDBPyConnection, path: str, columns: Sequence[str]
) -> tuple[tuple[str, str], ...]:
    """Pairs of columns equal on every row (two blanks are equal) with at least one value."""
    pairs = list(itertools.combinations(columns, 2))
    if not pairs:
        return ()
    selects = []
    for number, (a, b) in enumerate(pairs):
        selects.append(
            f"count(*) filter (where {_text(a)} is distinct from {_text(b)}) as d{number}"
        )
        selects.append(
            f"count(*) filter (where {_text(a)} is not null or {_text(b)} is not null) as v{number}"
        )
    row = con.execute(f"select {', '.join(selects)} from read_parquet(?)", [path]).fetchone()
    return tuple(
        pair
        for number, pair in enumerate(pairs)
        if row[2 * number] == 0 and row[2 * number + 1] > 0
    )


def profile_products(settings: Settings) -> ProductProfile:
    """Profile the candidate columns on the bronze file for the configured sheet."""
    try:
        bronze = find_bronze_file(settings)
    except SilverError as exc:
        raise ProfileError(str(exc)) from exc
    path = bronze.as_posix()
    code = settings.product.code_column
    name = settings.product.name_column
    _check_columns(path, [code, name, *CANDIDATE_COLUMNS])
    con = duckdb.connect()
    try:
        rows, codes, blank_code = con.execute(
            f"select count(*), count(distinct {_text(code)}), "
            f"count(*) filter (where {_text(code)} is null) from read_parquet(?)",
            [path],
        ).fetchone()
        name_conflicts = con.execute(
            f"""
            select count(*) from (
                select {_text(code)} from read_parquet(?)
                where {_text(code)} is not null
                group by 1
                having count(distinct {_text(name)}) > 1
            )
            """,
            [path],
        ).fetchone()[0]
        candidates = tuple(_candidate(con, path, code, column) for column in CANDIDATE_COLUMNS)
        identical = _identical_pairs(con, path, CANDIDATE_COLUMNS)
    except duckdb.Error as exc:
        raise ProfileError(f"the profile query failed: {type(exc).__name__}") from exc
    finally:
        con.close()
    logger.info("product profile: %d rows, %d codes, %d candidates", rows, codes, len(candidates))
    return ProductProfile(
        code_column=code,
        name_column=name,
        rows=int(rows),
        codes=int(codes),
        blank_code_rows=int(blank_code),
        name_conflict_codes=int(name_conflicts),
        candidates=candidates,
        identical_pairs=identical,
    )


def format_profile(profile: ProductProfile) -> str:
    """The profile as plain text: labels and counts only."""
    lines = [
        f"Product profile: {profile.rows:,} rows, {profile.codes:,} product codes "
        f"({profile.code_column}), {profile.blank_code_rows:,} rows with a blank code",
        f"Names ({profile.name_column}): {profile.name_conflict_codes:,} codes have more than "
        "one name",
        "",
    ]
    for c in profile.candidates:
        lines.append(
            f"{c.column:<20} distinct {c.distinct:,}, blank rows {c.blank_rows:,}, "
            f"conflict codes {c.conflict_codes:,} (tied {c.tied_codes:,}), "
            f"codes without a value {c.codes_without_value:,}"
        )
    lines.append("")
    if profile.identical_pairs:
        pairs = "; ".join(f"{a} = {b}" for a, b in profile.identical_pairs)
        lines.append(f"Columns equal on every row: {pairs}")
    else:
        lines.append("No two candidate columns are equal on every row")
    lines += ["", VALUE_RULE]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m revint.product_profile",
        description="Profile the candidate brand and category columns (counts only).",
    )
    parser.add_argument("--json", action="store_true", help="print the counts as JSON")
    args = parser.parse_args(argv)
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"product profile: {exc}", file=sys.stderr)
        return 1
    try:
        profile = profile_products(settings)
    except ProfileError as exc:
        print(f"product profile failed: {exc}", file=sys.stderr)
        return EXIT_PROFILE_FAILED
    print(json.dumps(profile.as_dict(), indent=2) if args.json else format_profile(profile))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
