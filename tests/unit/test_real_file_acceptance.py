"""Story #46: the E1 success measure on the real file (spec 01 section 9).

The real-file tests are marked `realdata`: they run only when `data/` exists (the conftest
skips them otherwise) and never in CI. They work on a COPY of `data/bronze` with a temporary
warehouse and reports folder, run the real commands, and assert counts, sums and structure only.
Nothing here prints or compares a customer-level value. The report and docs-count tests with
synthetic data run everywhere.
"""

from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest
from silver_helpers import bronze_row, build, query
from typer.testing import CliRunner

from revint.build_log import read_build_log
from revint.cli import app
from revint.config import RULE_IDS, Settings, load_settings
from revint.report import build_report

runner = CliRunner()
DATA_DIR = Path(__file__).resolve().parents[2] / "data"
BRONZE_ROWS = 662_128
EXCLUDED_ROWS = 557
DOCS_DUPLICATES = 556


@dataclass(frozen=True)
class RealRun:
    settings: Settings
    bronze_before: dict[str, str]
    bronze_after: dict[str, str]
    check_exit: int
    check_output: str
    report_exit: int
    report: str


def hashes(folder: Path) -> dict[str, str]:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.iterdir())}


@pytest.fixture(scope="module")
def real(tmp_path_factory: pytest.TempPathFactory) -> RealRun:
    """`build silver`, `check` and `report dq` on a copy of the real bronze files."""
    source = load_settings(env={})
    if not list(source.paths.bronze.glob("*__RAW_SCJ_SALES.parquet")):
        pytest.skip("bronze not built: run `uv run revint build bronze` first")
    root = tmp_path_factory.mktemp("acceptance")
    shutil.copytree(source.paths.bronze, root / "bronze")
    env = {
        "REVINT_PATHS_BRONZE": str(root / "bronze"),
        "REVINT_PATHS_WAREHOUSE": str(root / "warehouse.duckdb"),
        "REVINT_PATHS_REPORTS": str(root / "reports"),
    }
    before = hashes(root / "bronze")
    silver = runner.invoke(app, ["build", "silver"], env=env)
    assert silver.exit_code == 0, silver.output
    check = runner.invoke(app, ["check"], env=env)
    report = runner.invoke(app, ["report", "dq"], env=env)
    settings = load_settings(env=env)
    text = (settings.paths.reports / "data_quality.md").read_text(encoding="utf-8")
    return RealRun(
        settings=settings,
        bronze_before=before,
        bronze_after=hashes(root / "bronze"),
        check_exit=check.exit_code,
        check_output=check.output,
        report_exit=report.exit_code,
        report=text,
    )


def result_lines(output: str, check_id: str) -> list[str]:
    return [line for line in output.splitlines() if line.startswith(f"{check_id} ")]


# AC1: R1, R2, R3, R7 (silver side) and R8 pass; they skip without data/ ------------------------


@pytest.mark.realdata
def test_ac1_check_exits_zero_on_the_real_file(real: RealRun) -> None:
    assert real.check_exit == 0, real.check_output


@pytest.mark.realdata
def test_ac1_r1_bronze_rows_equal_the_excel_rows(real: RealRun) -> None:
    (line,) = result_lines(real.check_output, "R1")
    assert "pass" in line
    assert f"{BRONZE_ROWS:,}" in line


@pytest.mark.realdata
def test_ac1_r2_silver_audit_and_stray_counts_match(real: RealRun) -> None:
    lines = result_lines(real.check_output, "R2")
    assert len(lines) == 3
    assert all(": pass" in line for line in lines)
    assert f"{BRONZE_ROWS:,}" in " ".join(lines)
    assert f"{EXCLUDED_ROWS:,}" in " ".join(lines)


@pytest.mark.realdata
def test_ac1_r3_every_candidate_amount_column_reconciles(real: RealRun) -> None:
    lines = result_lines(real.check_output, "R3")
    assert len(lines) == len(real.settings.net_sales.candidate_columns)
    assert all(": pass" in line for line in lines)


@pytest.mark.realdata
def test_ac1_r7_silver_side_passes_for_every_candidate_column(real: RealRun) -> None:
    lines = result_lines(real.check_output, "R7")
    assert len(lines) == len(real.settings.net_sales.candidate_columns)
    assert all(": pass" in line for line in lines)


@pytest.mark.realdata
def test_ac1_r8_every_duplicate_has_an_identical_kept_twin(real: RealRun) -> None:
    (line,) = result_lines(real.check_output, "R8")
    assert ": pass" in line
    assert f"{DOCS_DUPLICATES} exact_duplicate rows checked" in line


@pytest.mark.realdata
def test_ac1_r4_is_reported_as_information(real: RealRun) -> None:
    lines = result_lines(real.check_output, "R4")
    assert len(lines) == 4
    assert all(": info" in line for line in lines)


@pytest.mark.realdata
def test_ac1_the_recon_results_table_has_no_failure(real: RealRun) -> None:
    assert query(real.settings, "select count(*) from recon_results where status = 'fail'") == [
        (0,)
    ]
    assert query(real.settings, "select count(*) from recon_results")[0][0] == 3 + 1 + 6 + 4 + 6 + 1


def test_ac1_real_data_tests_are_marked_so_they_skip_without_data() -> None:
    names = [
        name
        for name, obj in globals().items()
        if name.startswith("test_") and getattr(obj, "pytestmark", None)
    ]
    marked = {n for n in names if any(m.name == "realdata" for m in globals()[n].pytestmark)}
    assert len(marked) >= 15
    assert all(n.startswith("test_ac") for n in marked)


def test_ac1_the_conftest_skips_realdata_tests_when_data_is_absent() -> None:
    conftest = (Path(__file__).resolve().parents[1] / "conftest.py").read_text(encoding="utf-8")
    assert "realdata" in conftest
    assert "DATA_DIR.is_dir()" in conftest


# AC2: the report states excluded count and revenue effect, and the duplicate count ---------------


@pytest.mark.realdata
def test_ac2_report_states_the_excluded_count_and_revenue_effect_per_reason(real: RealRun) -> None:
    assert real.report_exit == 0
    block = real.report.split("## Exclusions")[1].split("## Void")[0]
    assert f"Excluded rows, all reasons: {EXCLUDED_ROWS:,} rows" in block
    reasons = re.findall(r"^\| (exact_duplicate|stray_row) \|", block, re.M)
    assert reasons.count("exact_duplicate") == 7  # 1 in Exclusions, 6 columns in Revenue effect
    assert reasons.count("stray_row") == 7


@pytest.mark.realdata
def test_ac2_report_shows_the_actual_duplicate_count_next_to_the_docs_figure(
    real: RealRun,
) -> None:
    assert (
        f"Exact duplicates: {DOCS_DUPLICATES:,} found; the project docs state about "
        f"{DOCS_DUPLICATES:,} (difference +0)"
    ) in real.report


@pytest.mark.realdata
def test_ac2_report_counts_equal_the_warehouse(real: RealRun) -> None:
    by_reason = dict(
        query(
            real.settings,
            "select exclusion_reason, count(*) from silver_excluded_rows group by 1",
        )
    )
    assert by_reason == {"exact_duplicate": DOCS_DUPLICATES, "stray_row": 1}
    rows = re.findall(r"^\| (exact_duplicate|stray_row) \| ([\d,]+) \|", real.report, re.M)
    assert {(reason, count) for reason, count in rows} == {
        ("exact_duplicate", f"{DOCS_DUPLICATES:,}"),
        ("stray_row", "1"),
    }


@pytest.mark.realdata
def test_ac2_report_lists_every_rule(real: RealRun) -> None:
    listed = re.findall(r"^\| (S\d+) \|", real.report, re.M)
    assert listed == RULE_IDS


def test_ac2_the_duplicate_line_shows_a_difference_from_the_docs_figure(load_with) -> None:
    """Synthetic: one copy, against the docs figure of 556."""
    settings = load_with({"ingest": {"expected_columns": EXPECTED_COLUMNS}})
    twin = {"OrderReference": "O1", "Net_Amount_2": "10"}
    build(
        settings,
        [bronze_row(8, **twin), bronze_row(9, **twin), bronze_row(10, OrderReference="O2")],
    )
    text = build_report(settings)
    assert "Exact duplicates: 1 found; the project docs state about 556 (difference -555)." in text


def test_ac2_the_docs_count_comes_from_config(load_with) -> None:
    settings = load_with(
        {"ingest": {"expected_columns": EXPECTED_COLUMNS}, "recon": {"docs_duplicate_count": 1}}
    )
    twin = {"OrderReference": "O1"}
    build(settings, [bronze_row(8, **twin), bronze_row(9, **twin)])
    assert "found; the project docs state about 1 (difference +0)" in build_report(settings)


# AC3: bronze is byte-identical before and after the build ---------------------------------------


@pytest.mark.realdata
def test_ac3_bronze_files_are_byte_identical_after_build_check_and_report(real: RealRun) -> None:
    assert real.bronze_before
    assert real.bronze_after == real.bronze_before


@pytest.mark.realdata
def test_ac3_the_real_data_raw_files_are_not_touched_by_the_run(real: RealRun) -> None:
    raw = DATA_DIR / "raw"
    assert not list(raw.glob("*.tmp"))
    assert not list(raw.glob("~$*"))
    assert not list(raw.glob("*.duckdb"))
    assert not list(raw.glob("*.parquet"))


# AC4: the evidence holds counts and aggregates only ----------------------------------------------


@pytest.mark.realdata
def test_ac4_the_build_log_holds_counts_for_the_run(real: RealRun) -> None:
    (row,) = read_build_log(real.settings)
    assert (row["stage"], row["status"], row["rows_out"]) == ("silver", "succeeded", BRONZE_ROWS)


@pytest.mark.realdata
def test_ac4_report_and_check_output_hold_only_labels_numbers_and_dates(real: RealRun) -> None:
    allowed = re.compile(r"^[A-Za-z0-9_ ,.;()%:+\-/=|#\\*<>`'\[\]]*$")
    for text in (real.report, real.check_output):
        assert all(allowed.match(line) for line in text.splitlines())
    codes = [
        c
        for (c,) in query(
            real.settings,
            "select customer_code from silver_customer_codes order by random() limit 25",
        )
    ]
    assert codes
    assert not any(code in real.report or code in real.check_output for code in codes if code)


# AC5 ------


def test_ac5_every_ac_has_a_test_in_this_module() -> None:
    text = Path(__file__).read_text(encoding="utf-8")
    for ac in range(1, 5):
        assert f"def test_ac{ac}_" in text


EXPECTED_COLUMNS = load_settings(env={}).ingest.expected_columns
