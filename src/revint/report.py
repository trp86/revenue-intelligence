"""The data quality report, `revint report dq` (spec 01 section 5).

The report is markdown made from the three tables the silver build writes (`dq_rule_results`,
`dq_exclusion_effect`, `dq_void_effect`). They hold counts and sums only, and this module reads
nothing else of silver except its row count, so the report cannot hold a customer, label or
order value. The content depends only on those tables and the settings: a re-run differs in the
`Generated:` line alone. Messages and logs hold counts and file names.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import duckdb

from revint.config import RULE_IDS, Settings

logger = logging.getLogger(__name__)

REPORT_FILE = "data_quality.md"
EXIT_REPORT_FAILED = 4


class ReportError(Exception):
    """The report could not be built."""


def _count(value: int) -> str:
    return f"{value:,}"


def _amount(value: Decimal | None) -> str:
    return "n/a" if value is None else f"{value:,.2f}"


def _percent(value: Decimal | None) -> str:
    return "n/a" if value is None else f"{value:.2f}%"


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines.extend("| " + " | ".join(_cell(c) for c in row) + " |" for row in rows)
    return lines


def _read(settings: Settings) -> dict[str, list[tuple]]:
    """The rows of the quality tables and the silver row count, in a fixed order."""
    warehouse = settings.paths.warehouse
    if not warehouse.is_file():
        raise ReportError(f"warehouse not found: {warehouse}; build silver first")
    try:
        con = duckdb.connect(str(warehouse), read_only=True)
    except duckdb.IOException as exc:
        raise ReportError(
            f"the warehouse {warehouse} is in use by another process; stop it and run again"
        ) from exc
    try:
        present = {
            name
            for (name,) in con.execute(
                "select table_name from information_schema.tables"
            ).fetchall()
        }
        needed = ("silver_sales", "dq_rule_results", "dq_exclusion_effect", "dq_void_effect")
        missing = [name for name in needed if name not in present]
        if missing:
            raise ReportError(
                f"the warehouse has no table {', '.join(missing)}; build silver first"
            )
        return {
            "silver": con.execute("select count(*) from silver_sales").fetchall(),
            "rules": con.execute(
                "select rule_id, description, rows_affected, pct_rows, net_sales_impact, "
                "action_taken, severity from dq_rule_results"
            ).fetchall(),
            "exclusions": con.execute(
                "select exclusion_reason, amount_column, rows_excluded, excluded_amount, "
                "pct_of_column_total, pct_of_net_sales_total, is_net_sales_field "
                "from dq_exclusion_effect order by exclusion_reason, amount_column"
            ).fetchall(),
            "void": con.execute(
                "select voided_lines, voided_net_sales, blank_void_lines, unmapped_void_lines "
                "from dq_void_effect"
            ).fetchall(),
        }
    finally:
        con.close()


def _rule_rows(rows: list[tuple]) -> list[tuple]:
    by_id = {row[0]: row for row in rows}
    absent = [rule for rule in RULE_IDS if rule not in by_id]
    if absent:
        raise ReportError(f"dq_rule_results has no row for rule(s): {', '.join(absent)}")
    return [by_id[rule] for rule in RULE_IDS]


def build_report(settings: Settings, now: datetime | None = None) -> str:
    """The report as markdown text. `now` is the time shown on the `Generated:` line."""
    data = _read(settings)
    rules = _rule_rows(data["rules"])
    stamp = (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    silver_rows = data["silver"][0][0]
    field = settings.net_sales.field
    lines = [
        "# Data quality report",
        "",
        f"Generated: {stamp}",
        "",
        f"- Silver rows: {_count(silver_rows)}",
        f"- As-of date: {settings.asof.date.isoformat()}",
        f"- Net sales field: {field} (provisional)",
        "",
        "Counts and sums only: no customer, label or order value appears in this report.",
        "",
        "## Rules",
        "",
        "Rows affected counts the problem rows of each rule. Net sales impact is the sum of "
        f"{field} over those rows.",
        "",
    ]
    lines += _table(
        [
            "Rule",
            "Description",
            "Rows affected",
            "% of rows",
            "Net sales impact",
            "Action",
            "Severity",
        ],
        [
            [rule, desc, _count(n), _percent(pct), _amount(impact), action, severity]
            for rule, desc, n, pct, impact, action, severity in rules
        ],
    )

    excluded_total = next(row[2] for row in rules if row[0] == "S10")
    net = [row for row in data["exclusions"] if row[6]]
    lines += [
        "",
        "## Exclusions",
        "",
        f"Excluded rows, all reasons: {_count(excluded_total)} "
        f"{'row' if excluded_total == 1 else 'rows'}. Excluded rows stay in silver, are recorded "
        "in silver_excluded_rows and are left out of gold.",
        "",
    ]
    lines += _table(
        ["Reason", "Rows excluded", f"{field} excluded", f"% of {field} total"],
        [
            [reason, _count(n), _amount(amount), _percent(pct_net)]
            for reason, _, n, amount, _, pct_net, _ in net
        ],
    )

    lines += [
        "",
        "## Revenue effect",
        "",
        "The sum of each candidate amount column over the excluded rows, and its share of that "
        "column's total.",
        "",
    ]
    lines += _table(
        [
            "Reason",
            "Column",
            "Role",
            "Excluded amount",
            "% of column total",
            "% of net sales total",
        ],
        [
            [
                reason,
                column,
                "net sales field" if is_field else "candidate",
                _amount(amount),
                _percent(pct_col),
                _percent(pct_net),
            ]
            for reason, column, _, amount, pct_col, pct_net, is_field in data["exclusions"]
        ],
    )

    voided, voided_sales, blank, unmapped = data["void"][0]
    lines += [
        "",
        "## Void",
        "",
        f"- Voided lines (void_flag = 1): {_count(voided)}, net sales {_amount(voided_sales)}",
        f"- Lines with a blank Void: {_count(blank)}",
        f"- Lines with a Void value that is not in void.value_map: {_count(unmapped)}",
        "",
    ]
    return "\n".join(lines)


def write_report(settings: Settings, now: datetime | None = None) -> Path:
    """Write `<paths.reports>/data_quality.md` and return its path.

    The text is built first and written through a temporary file, so a failure leaves the
    previous report as it was.
    """
    text = build_report(settings, now)
    folder = settings.paths.reports
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / REPORT_FILE
    temporary = target.with_name(target.name + ".tmp")
    try:
        temporary.write_bytes(text.encode("utf-8"))
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    logger.info("data quality report: %d rules, %d characters", len(RULE_IDS), len(text))
    return target


def execute_report(settings: Settings, now: datetime | None = None) -> int:
    """Write the report for the command line: print the outcome, return an exit code."""
    try:
        path = write_report(settings, now)
    except (ReportError, OSError) as exc:
        print(f"report dq failed: {exc}", file=sys.stderr)
        return EXIT_REPORT_FAILED
    print(f"report dq: {path.name} written to {path.parent}")
    return 0
