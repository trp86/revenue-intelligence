"""Story #42: the data quality report, `revint report dq` (spec 01 section 5).

Synthetic data only. The real-file test is marked `realdata` and asserts counts and structure,
never a value. The silver build runs once per module; a test that changes data works on its own
copy of the warehouse.
"""

from __future__ import annotations

import logging
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest
from silver_helpers import SIX_AMOUNTS, bronze_row, build, query
from typer.testing import CliRunner

from revint.cli import app
from revint.config import RULE_IDS, Settings, load_settings
from revint.report import (
    EXIT_REPORT_FAILED,
    REPORT_FILE,
    ReportError,
    build_report,
    execute_report,
    write_report,
)
from revint.silver import AMOUNT_COLUMNS, run_silver

runner = CliRunner()
SECRET = "SECRET-"
NOW = datetime(2026, 10, 31, 9, 30, 0, tzinfo=UTC)
LATER = datetime(2026, 11, 1, 17, 45, 0, tzinfo=UTC)
STAMP = re.compile(r"^Generated: .*$", re.MULTILINE)


def rows() -> list[dict[str, str | None]]:
    """Six order lines: two plain, an exact copy, a stray row, a free-goods line, a bad amount."""
    plain = {
        "CustomerCode": f"{SECRET}C1",
        "Customer": f"{SECRET}Name 1",
        "Channel_Category": f"{SECRET}channel",
        "Branch_Name": f"{SECRET}branch",
        "Void": f"{SECRET}void",
        "Quantity(PCS)": "2",
        "Net_Amount_2": "40.5",
        "Selling_Amount": "50",
        "Date": "2019-03-01",
    }
    return [
        bronze_row(8, OrderReference="O1", **plain),
        bronze_row(9, OrderReference="O2", **{**plain, "Net_Amount_2": "10"}),
        bronze_row(10, OrderReference="O2", **{**plain, "Net_Amount_2": "10"}),
        bronze_row(11, Change_to_Ctn="1"),
        bronze_row(12, OrderReference="O3", **{**plain, "Net_Amount_2": "0"}),
        bronze_row(13, OrderReference="O4", **{**plain, "Net_Amount_2": "abc"}),
    ]


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    root = tmp_path_factory.mktemp("report")
    env = {
        "REVINT_PATHS_RAW": str(root / "raw"),
        "REVINT_PATHS_BRONZE": str(root / "bronze"),
        "REVINT_PATHS_WAREHOUSE": str(root / "warehouse.duckdb"),
        "REVINT_PATHS_APP_DB": str(root / "app.duckdb"),
        "REVINT_PATHS_REPORTS": str(root / "reports"),
    }
    settings = load_settings(env=env)
    build(settings, rows())
    return settings


@pytest.fixture
def work(built: Settings, tmp_path: Path) -> Settings:
    """A private copy of the warehouse and its own reports folder."""
    shutil.copy(built.paths.warehouse, tmp_path / "warehouse.duckdb")
    env = {
        "REVINT_PATHS_RAW": str(built.paths.raw),
        "REVINT_PATHS_BRONZE": str(built.paths.bronze),
        "REVINT_PATHS_WAREHOUSE": str(tmp_path / "warehouse.duckdb"),
        "REVINT_PATHS_APP_DB": str(tmp_path / "app.duckdb"),
        "REVINT_PATHS_REPORTS": str(tmp_path / "reports"),
    }
    return load_settings(env=env)


def table_rows(text: str, first_cell: str) -> list[list[str]]:
    """The cells of every markdown table row whose first cell is in `first_cell`'s family."""
    found = []
    for line in text.splitlines():
        if line.startswith("|") and not set(line) <= set("|- :"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if re.fullmatch(first_cell, cells[0]):
                found.append(cells)
    return found


def section(text: str, heading: str) -> str:
    """The text under a `## heading` up to the next `## ` heading."""
    match = re.search(rf"^## {re.escape(heading)}\s*$(.*?)(?=^## |\Z)", text, re.M | re.S)
    assert match, f"no section {heading}"
    return match.group(1)


# AC1: a table with every rule S1 to S12 and its counts ------------------------------------------


def test_ac1_report_goes_to_the_reports_folder_as_data_quality_md(work: Settings) -> None:
    path = write_report(work, NOW)
    assert path == work.paths.reports / "data_quality.md"
    assert REPORT_FILE == "data_quality.md"
    assert path.read_text(encoding="utf-8").startswith("# Data quality report")


def test_ac1_the_report_folder_is_created_when_missing(work: Settings) -> None:
    assert not work.paths.reports.exists()
    write_report(work, NOW)
    assert work.paths.reports.is_dir()


def test_ac1_table_lists_every_rule_in_order(work: Settings) -> None:
    text = build_report(work, NOW)
    ids = [r[0] for r in table_rows(text, r"S\d+") if r[0] in RULE_IDS]
    first = section(text, "Rules")
    listed = [r[0] for r in table_rows(first, r"S\d+")]
    assert listed == RULE_IDS
    assert ids[: len(RULE_IDS)] == RULE_IDS


def test_ac1_table_has_the_spec_columns(work: Settings) -> None:
    header = next(
        line for line in section(build_report(work, NOW), "Rules").splitlines() if "|" in line
    )
    cells = [c.strip().lower() for c in header.strip().strip("|").split("|")]
    assert cells == [
        "rule",
        "description",
        "rows affected",
        "% of rows",
        "net sales impact",
        "action",
        "severity",
    ]


def test_ac1_counts_equal_the_dq_rule_results_table(work: Settings) -> None:
    text = section(build_report(work, NOW), "Rules")
    stored = {
        rule: (count, action, severity)
        for rule, count, action, severity in query(
            work, "select rule_id, rows_affected, action_taken, severity from dq_rule_results"
        )
    }
    for cells in table_rows(text, r"S\d+"):
        count, action, severity = stored[cells[0]]
        assert cells[2] == f"{count:,}"
        assert cells[5] == action
        assert cells[6] == severity


def test_ac1_known_counts_from_the_fixture(work: Settings) -> None:
    text = section(build_report(work, NOW), "Rules")
    counts = {r[0]: r[2] for r in table_rows(text, r"S\d+")}
    assert counts["S5"] == "1"  # one exact copy
    assert counts["S9"] == "1"  # the stray row
    assert counts["S10"] == "2"  # copy and stray row
    assert counts["S12"] == "2"


def test_ac1_percent_and_amount_are_formatted_and_null_is_n_a(work: Settings) -> None:
    text = section(build_report(work, NOW), "Rules")
    row = {r[0]: r for r in table_rows(text, r"S\d+")}
    assert re.fullmatch(r"\d+\.\d\d%", row["S5"][3])
    assert row["S1"][4] == "n/a"  # no net sales impact for S1
    assert re.fullmatch(r"-?[\d,]+\.\d\d", row["S5"][4])


def test_ac1_a_missing_rule_in_the_results_table_fails_the_report(work: Settings) -> None:
    con = duckdb.connect(str(work.paths.warehouse))
    con.execute("delete from dq_rule_results where rule_id = 'S7'")
    con.close()
    with pytest.raises(ReportError, match="S7"):
        build_report(work, NOW)


def test_ac1_the_report_says_which_data_it_describes(work: Settings) -> None:
    text = build_report(work, NOW)
    total = query(work, "select count(*) from silver_sales")[0][0]
    assert f"{total:,}" in text.split("## Rules")[0]
    assert "2020-02-29" in text.split("## Rules")[0]  # the as-of date from settings


# AC2: an Exclusions block with count and revenue effect per reason -------------------------------


def test_ac2_exclusions_block_has_a_row_per_reason(work: Settings) -> None:
    block = section(build_report(work, NOW), "Exclusions")
    reasons = [r[0] for r in table_rows(block, r"exact_duplicate|stray_row")]
    assert sorted(set(reasons)) == ["exact_duplicate", "stray_row"]


def test_ac2_excluded_counts_are_stated_per_reason(work: Settings) -> None:
    block = section(build_report(work, NOW), "Exclusions")
    counts = {r[0]: r[1] for r in table_rows(block, r"exact_duplicate|stray_row") if r[1] != ""}
    assert counts == {"exact_duplicate": "1", "stray_row": "1"}


def test_ac2_revenue_effect_is_given_for_every_candidate_column(work: Settings) -> None:
    block = section(build_report(work, NOW), "Revenue effect")
    for column in work.net_sales.candidate_columns:
        assert column in block
    assert len(table_rows(block, r"exact_duplicate")) == len(work.net_sales.candidate_columns)
    assert len(table_rows(block, r"stray_row")) == len(work.net_sales.candidate_columns)


def test_ac2_revenue_effect_equals_the_dq_exclusion_effect_table(work: Settings) -> None:
    block = section(build_report(work, NOW), "Revenue effect")
    stored = {
        (reason, column): (amount, pct)
        for reason, column, amount, pct in query(
            work,
            "select exclusion_reason, amount_column, excluded_amount, pct_of_column_total "
            "from dq_exclusion_effect",
        )
    }
    for cells in table_rows(block, r"exact_duplicate|stray_row"):
        amount, pct = stored[(cells[0], cells[1])]
        assert cells[3] == ("n/a" if amount is None else f"{amount:,.2f}")
        assert cells[4] == ("n/a" if pct is None else f"{pct:.2f}%")


def test_ac2_the_net_sales_field_is_marked(work: Settings) -> None:
    block = section(build_report(work, NOW), "Revenue effect")
    marked = [r for r in table_rows(block, r"exact_duplicate|stray_row") if "net sales" in r[2]]
    assert {r[1] for r in marked} == {work.net_sales.field}


def test_ac2_net_sales_share_of_the_total_is_stated(work: Settings) -> None:
    block = section(build_report(work, NOW), "Revenue effect")
    (pct,) = query(
        work,
        "select pct_of_net_sales_total from dq_exclusion_effect "
        "where exclusion_reason = 'exact_duplicate' and is_net_sales_field",
    )[0]
    assert f"{pct:.2f}%" in block


def test_ac2_total_excluded_row_count_is_stated(work: Settings) -> None:
    block = section(build_report(work, NOW), "Exclusions")
    assert "2 rows" in block  # S10: all reasons


def test_ac2_void_effect_is_reported(work: Settings) -> None:
    text = build_report(work, NOW)
    voided, blank, unmapped = query(
        work, "select voided_lines, blank_void_lines, unmapped_void_lines from dq_void_effect"
    )[0]
    block = section(text, "Void")
    assert f"{voided:,}" in block
    assert f"{blank:,}" in block
    assert f"{unmapped:,}" in block


# AC3: a re-run gives the same content apart from the timestamp -----------------------------------


def test_ac3_two_runs_differ_only_in_the_timestamp_line(work: Settings) -> None:
    first = write_report(work, NOW).read_text(encoding="utf-8")
    second = write_report(work, LATER).read_text(encoding="utf-8")
    assert first != second
    assert STAMP.sub("", first) == STAMP.sub("", second)


def test_ac3_the_timestamp_is_one_line_in_utc(work: Settings) -> None:
    text = build_report(work, NOW)
    assert len(STAMP.findall(text)) == 1
    assert "Generated: 2026-10-31T09:30:00Z" in text


def test_ac3_a_run_at_the_same_time_is_byte_identical(work: Settings) -> None:
    a = write_report(work, NOW).read_bytes()
    b = write_report(work, NOW).read_bytes()
    assert a == b


def test_ac3_a_re_run_replaces_the_file_and_leaves_nothing_behind(work: Settings) -> None:
    write_report(work, NOW)
    write_report(work, LATER)
    assert [p.name for p in work.paths.reports.iterdir()] == [REPORT_FILE]


def test_ac3_a_fresh_silver_build_gives_the_same_report(built: Settings, work: Settings) -> None:
    before = write_report(work, NOW).read_text(encoding="utf-8")
    run_silver(work)
    after = write_report(work, NOW).read_text(encoding="utf-8")
    assert before == after


def test_ac3_default_timestamp_is_the_current_utc_time(work: Settings) -> None:
    text = build_report(work)
    assert re.search(r"^Generated: \d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$", text, re.M)


def test_ac3_the_file_is_utf8_with_unix_line_ends(work: Settings) -> None:
    data = write_report(work, NOW).read_bytes()
    assert b"\r\n" not in data
    assert data.endswith(b"\n")
    data.decode("utf-8")


# AC4: no customer-level values --------------------------------------------------------------------


def test_ac4_report_holds_no_customer_label_or_void_values(work: Settings) -> None:
    text = write_report(work, NOW).read_text(encoding="utf-8")
    assert SECRET not in text
    for name in ("Name 1", "O1", "O2", "O3", "O4"):
        assert name not in text


def test_ac4_the_warehouse_holds_the_secret_so_the_check_means_something(work: Settings) -> None:
    assert query(work, "select count(*) from silver_sales where Customer like 'SECRET-%'")[0][0] > 0


def test_ac4_report_logs_and_output_hold_no_values(
    work: Settings, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    with caplog.at_level(logging.DEBUG):
        assert execute_report(work, NOW) == 0
    out = capsys.readouterr()
    assert SECRET not in out.out + out.err + caplog.text


def test_ac4_only_rule_ids_reasons_and_columns_appear_as_row_labels(work: Settings) -> None:
    text = build_report(work, NOW)
    labels = {c[0] for c in table_rows(text, r".+")}
    allowed = set(RULE_IDS) | {"exact_duplicate", "stray_row", "Rule", "Reason", "Column"}
    allowed |= set(AMOUNT_COLUMNS)
    assert labels <= allowed | {"Item"}, labels - allowed


# `revint report dq` -----------------------------------------------------------------------------


def use(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in {
        "REVINT_PATHS_RAW": settings.paths.raw,
        "REVINT_PATHS_BRONZE": settings.paths.bronze,
        "REVINT_PATHS_WAREHOUSE": settings.paths.warehouse,
        "REVINT_PATHS_APP_DB": settings.paths.app_db,
        "REVINT_PATHS_REPORTS": settings.paths.reports,
    }.items():
        monkeypatch.setenv(key, str(value))


def test_ac1_cli_report_dq_writes_the_file_and_exits_zero(
    work: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    use(work, monkeypatch)
    result = runner.invoke(app, ["report", "dq"])
    assert result.exit_code == 0, result.output
    assert (work.paths.reports / "data_quality.md").is_file()
    assert "data_quality.md" in result.output


def test_ac1_cli_without_a_warehouse_says_to_build_silver(
    work: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    work.paths.warehouse.unlink()
    use(work, monkeypatch)
    result = runner.invoke(app, ["report", "dq"])
    assert result.exit_code == EXIT_REPORT_FAILED
    assert "silver" in result.output.lower()
    assert not work.paths.reports.exists()


def test_ac1_cli_with_a_warehouse_but_no_quality_tables_says_to_build_silver(
    work: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    con = duckdb.connect(str(work.paths.warehouse))
    con.execute("drop table dq_rule_results")
    con.close()
    use(work, monkeypatch)
    result = runner.invoke(app, ["report", "dq"])
    assert result.exit_code == EXIT_REPORT_FAILED
    assert "dq_rule_results" in result.output
    assert not (work.paths.reports / REPORT_FILE).exists()


def test_ac1_a_failed_run_keeps_the_previous_report(
    work: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_report(work, NOW)
    before = path.read_bytes()
    con = duckdb.connect(str(work.paths.warehouse))
    con.execute("drop table dq_exclusion_effect")
    con.close()
    use(work, monkeypatch)
    assert runner.invoke(app, ["report", "dq"]).exit_code == EXIT_REPORT_FAILED
    assert path.read_bytes() == before


def test_ac1_cli_with_invalid_settings_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from revint import config

    bad = tmp_path / "settings.yaml"
    bad.write_text("typo_section:\n  x: 1\n", encoding="utf-8")
    monkeypatch.setattr(config, "DEFAULT_SETTINGS_FILE", bad)
    assert runner.invoke(app, ["report", "dq"]).exit_code == 1


def test_ac1_report_does_not_change_the_warehouse(work: Settings) -> None:
    before = query(work, "select count(*) from silver_sales")
    tables = query(work, "select table_name from information_schema.tables order by 1")
    write_report(work, NOW)
    assert query(work, "select count(*) from silver_sales") == before
    assert query(work, "select table_name from information_schema.tables order by 1") == tables


# The settings key and git ----------------------------------------------------------------------


def test_ac1_reports_path_defaults_to_the_reports_folder_under_the_project_root() -> None:
    root = Path(__file__).resolve().parents[2]
    assert load_settings(env={}).paths.reports == root / "reports"


def test_ac1_reports_path_can_be_overridden_from_the_environment(tmp_path: Path) -> None:
    settings = load_settings(env={"REVINT_PATHS_REPORTS": str(tmp_path / "out")})
    assert settings.paths.reports == tmp_path / "out"


def test_ac1_reports_folder_is_git_ignored() -> None:
    lines = (Path(__file__).resolve().parents[2] / ".gitignore").read_text().splitlines()
    assert "reports/" in lines


# AC5 ---------------------------------------------------------------------------------------------


def test_ac5_every_ac_has_a_test_in_this_module() -> None:
    names = Path(__file__).read_text(encoding="utf-8")
    for ac in range(1, 5):
        assert f"def test_ac{ac}_" in names


def test_ac5_amount_columns_used_in_the_fixture_are_the_candidates() -> None:
    assert set(SIX_AMOUNTS) == set(AMOUNT_COLUMNS)


@pytest.mark.realdata
def test_ac1_to_ac4_real_file_report(tmp_path: Path) -> None:
    """Counts and structure only."""
    env = {
        "REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb"),
        "REVINT_PATHS_REPORTS": str(tmp_path / "reports"),
    }
    real = load_settings(env=env)
    if not list(real.paths.bronze.glob("*__RAW_SCJ_SALES.parquet")):
        pytest.skip("bronze not built: run `uv run revint build bronze` first")
    run_silver(real)
    text = write_report(real, NOW).read_text(encoding="utf-8")
    assert [r[0] for r in table_rows(section(text, "Rules"), r"S\d+")] == RULE_IDS
    assert "662,128" in text
    assert "557" in section(text, "Exclusions")
    assert len(table_rows(section(text, "Revenue effect"), r"exact_duplicate|stray_row")) == 12
