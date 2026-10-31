"""Story #43: reconciliation R1 to R4 and `revint check` (spec 01 section 6).

Synthetic workbooks only. The real-file test is marked `realdata` and asserts counts and
structure, never a cell value. The expensive build (workbook, bronze, silver) runs once per
module; a test that changes data works on its own copy.
"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb
import polars as pl
import pytest
import xlsxwriter
import yaml
from silver_helpers import EXPECTED, query
from typer.testing import CliRunner

from revint.cli import app
from revint.config import DEFAULT_SETTINGS_FILE, Settings, load_settings
from revint.ingest.bronze import run_bronze
from revint.recon import (
    EXIT_CHECK_FAILED,
    RECON_DIR,
    ReconError,
    excel_data_rows,
    execute_recon,
    run_recon,
)
from revint.silver import AMOUNT_COLUMNS, run_silver

runner = CliRunner()
HEADER_ROW = 4
SECRET = "SECRET-"


def cells(**values: Any) -> list[Any]:
    """One worksheet row: the 75 columns in order, None where nothing is given."""
    unknown = set(values) - set(EXPECTED)
    assert not unknown, unknown
    return [values.get(name) for name in EXPECTED]


def write_workbook(path: Path, rows: list[list[Any]], blank_after: int = 0) -> None:
    """Header on Excel row 4, data from row 5, then `blank_after` styled blank rows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    book = xlsxwriter.Workbook(str(path))
    sheet = book.add_worksheet("RAW SCJ SALES")
    bold = book.add_format({"bold": True})
    date_fmt = book.add_format({"num_format": 14})
    sheet.write(0, 0, "note above the header")
    for col, name in enumerate(EXPECTED):
        sheet.write(HEADER_ROW - 1, col, name)
    for offset, row in enumerate(rows):
        for col, value in enumerate(row):
            if isinstance(value, datetime):
                sheet.write_datetime(HEADER_ROW + offset, col, value, date_fmt)
            elif value is not None:
                sheet.write(HEADER_ROW + offset, col, value)
    last = HEADER_ROW + len(rows)
    for extra in range(blank_after):
        sheet.write_blank(last + extra, 0, None, bold)
    book.close()


def paths_env(root: Path, raw: Path | None = None) -> dict[str, str]:
    return {
        "REVINT_PATHS_RAW": str(raw or root / "raw"),
        "REVINT_PATHS_BRONZE": str(root / "bronze"),
        "REVINT_PATHS_WAREHOUSE": str(root / "warehouse.duckdb"),
        "REVINT_PATHS_APP_DB": str(root / "app.duckdb"),
    }


def settings_in(root: Path, raw: Path | None = None) -> Settings:
    return load_settings(DEFAULT_SETTINGS_FILE, env=paths_env(root, raw))


def variant(root: Path, source: Settings, **sections: dict[str, Any]) -> Settings:
    """The committed settings with some sections changed, pointing at `source`'s paths."""
    data = yaml.safe_load(DEFAULT_SETTINGS_FILE.read_text(encoding="utf-8"))
    for name, keys in sections.items():
        data[name] = {**data.get(name, {}), **keys}
    config_file = root / "config" / "settings.yaml"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    env = {
        "REVINT_PATHS_RAW": str(source.paths.raw),
        "REVINT_PATHS_BRONZE": str(source.paths.bronze),
        "REVINT_PATHS_WAREHOUSE": str(source.paths.warehouse),
        "REVINT_PATHS_APP_DB": str(source.paths.app_db),
    }
    return load_settings(config_file, env=env)


def copy_of(source: Settings, root: Path) -> Settings:
    """A copy of bronze and the warehouse in `root`; the raw folder is shared (read-only)."""
    shutil.copytree(source.paths.bronze, root / "bronze")
    shutil.copy(source.paths.warehouse, root / "warehouse.duckdb")
    return settings_in(root, raw=source.paths.raw)


def execute(settings: Settings, sql: str) -> None:
    con = duckdb.connect(str(settings.paths.warehouse))
    try:
        con.execute(sql)
    finally:
        con.close()


def results(settings: Settings) -> dict[tuple[str, str], tuple[Any, ...]]:
    """recon_results as {(check_id, subject): (status, expected, actual, difference)}."""
    rows = query(
        settings,
        "select check_id, subject, status, expected, actual, difference from recon_results",
    )
    return {(r[0], r[1]): r[2:] for r in rows}


def status(settings: Settings, check_id: str, subject: str) -> str:
    return results(settings)[(check_id, subject)][0]


# Six data rows (Excel rows 5 to 10): two plain, a blank row, a row and its exact copy, and the
# stray row. Two styled blank rows follow and are not data.
ROWS = [
    cells(
        OrderReference="O1",
        CustomerCode=f"{SECRET}C1",
        Customer=f"{SECRET}Name 1",
        Date=datetime(2019, 1, 5),
        SCJ_CODE_1="P1",
        Selling_Amount=100,
        NET_AMOUNT_1=95,
        AMOUNT_AF_DIS=90,
        Net_Amount_2=85.5,
        Net_AMOUNT_3=80,
        TAX_AMOUNT=5,
        **{"Quantity(PCS)": 4},
    ),
    cells(
        OrderReference="O2",
        CustomerCode=f"{SECRET}C2",
        Customer=f"{SECRET}Name 2",
        Date=datetime(2019, 2, 9),
        SCJ_CODE_1="P2",
        Selling_Amount=50,
        Net_Amount_2=40.25,
        **{"Quantity(PCS)": 2},
    ),
    cells(),
    cells(
        OrderReference="O3",
        CustomerCode=f"{SECRET}C1",
        Customer=f"{SECRET}Name 1",
        Date=datetime(2019, 3, 1),
        SCJ_CODE_1="P1",
        Selling_Amount=-10,
        Net_Amount_2=-8,
        **{"Quantity(PCS)": -1},
    ),
    cells(
        OrderReference="O3",
        CustomerCode=f"{SECRET}C1",
        Customer=f"{SECRET}Name 1",
        Date=datetime(2019, 3, 1),
        SCJ_CODE_1="P1",
        Selling_Amount=-10,
        Net_Amount_2=-8,
        **{"Quantity(PCS)": -1},
    ),
    cells(Change_to_Ctn=1),
]
EXCEL_ROWS = 6


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    """Workbook -> bronze -> silver -> reconciliation, once for the module."""
    root = tmp_path_factory.mktemp("recon")
    write_workbook(root / "raw" / "sales.xlsx", ROWS, blank_after=2)
    settings = settings_in(root)
    run_bronze(settings)
    run_silver(settings)
    run_recon(settings)
    return settings


@pytest.fixture
def work(built: Settings, tmp_path: Path) -> Settings:
    """A private copy of `built` that a test may change."""
    return copy_of(built, tmp_path)


# AC1: R1, bronze rows equal Excel data rows ----------------------------------------------------


def test_ac1_excel_data_rows_counts_rows_under_the_header_to_the_last_value(
    built: Settings,
) -> None:
    assert excel_data_rows(built) == EXCEL_ROWS


def test_ac1_excel_data_rows_counts_a_blank_row_between_data_rows(built: Settings) -> None:
    # the layout has one blank row inside the data: six rows, only five with a value
    non_blank = pl.read_parquet(next(built.paths.bronze.glob("*__RAW_SCJ_SALES.parquet")))
    assert non_blank.height == EXCEL_ROWS
    assert excel_data_rows(built) == EXCEL_ROWS


def test_ac1_r1_passes_when_bronze_has_every_excel_row(built: Settings) -> None:
    assert results(built)[("R1", "bronze_rows")] == ("pass", EXCEL_ROWS, EXCEL_ROWS, 0)


def test_ac1_r1_ignores_trailing_formatted_blank_rows(built: Settings) -> None:
    # the workbook has two styled blank rows after the data; bronze drops them, R1 must not
    # count them either
    assert results(built)[("R1", "bronze_rows")][0] == "pass"


def test_ac1_r1_fails_when_bronze_lost_a_row(built: Settings, tmp_path: Path) -> None:
    work = copy_of(built, tmp_path)
    bronze = next(work.paths.bronze.glob("*__RAW_SCJ_SALES.parquet"))
    frame = pl.read_parquet(bronze)
    frame.slice(0, frame.height - 1).write_parquet(bronze)
    outcome = run_recon(work)
    assert results(work)[("R1", "bronze_rows")] == ("fail", EXCEL_ROWS, EXCEL_ROWS - 1, -1)
    assert not outcome.passed


def test_ac1_r1_fails_when_bronze_has_an_extra_row(built: Settings, tmp_path: Path) -> None:
    work = copy_of(built, tmp_path)
    bronze = next(work.paths.bronze.glob("*__RAW_SCJ_SALES.parquet"))
    frame = pl.read_parquet(bronze)
    pl.concat([frame, frame.slice(0, 1)]).write_parquet(bronze)
    run_recon(work)
    assert status(work, "R1", "bronze_rows") == "fail"


def test_ac1_without_the_workbook_the_check_cannot_run(built: Settings, tmp_path: Path) -> None:
    empty_raw = tmp_path / "empty_raw"
    empty_raw.mkdir()
    work = copy_of(built, tmp_path / "w")
    missing = settings_in(tmp_path / "w", raw=empty_raw)
    assert missing.paths.warehouse == work.paths.warehouse
    with pytest.raises(ReconError, match="workbook"):
        run_recon(missing)


# AC2: R2, silver rows equal bronze rows --------------------------------------------------------


def test_ac2_r2_passes_when_silver_holds_every_bronze_row(built: Settings) -> None:
    assert results(built)[("R2", "silver_rows")] == ("pass", EXCEL_ROWS, EXCEL_ROWS, 0)


def test_ac2_r2_fails_when_a_silver_row_is_missing(work: Settings) -> None:
    execute(work, "delete from silver_sales where _source_row = 6")
    run_recon(work)
    assert results(work)[("R2", "silver_rows")] == ("fail", EXCEL_ROWS, EXCEL_ROWS - 1, -1)


def test_ac2_r2_fails_when_silver_has_an_extra_row(work: Settings) -> None:
    execute(work, "insert into silver_sales select * from silver_sales where _source_row = 5")
    run_recon(work)
    assert status(work, "R2", "silver_rows") == "fail"


def test_ac2_excluded_rows_table_matches_the_excluded_flag(built: Settings) -> None:
    # one exact duplicate and the stray row
    assert results(built)[("R2", "excluded_rows")] == ("pass", 2, 2, 0)


def test_ac2_r2_fails_when_the_audit_table_misses_an_excluded_row(work: Settings) -> None:
    execute(work, "delete from silver_excluded_rows where exclusion_reason = 'stray_row'")
    run_recon(work)
    assert results(work)[("R2", "excluded_rows")] == ("fail", 2, 1, -1)


def test_ac2_r2_fails_when_a_row_is_excluded_without_being_audited(work: Settings) -> None:
    execute(work, "update silver_sales set is_excluded = true where _source_row = 5")
    run_recon(work)
    assert status(work, "R2", "excluded_rows") == "fail"


def test_ac2_stray_rows_in_silver_match_the_audit_table(built: Settings) -> None:
    assert results(built)[("R2", "stray_rows")] == ("pass", 1, 1, 0)


def test_ac2_stray_row_count_fails_when_audit_and_flag_disagree(work: Settings) -> None:
    execute(work, "update silver_excluded_rows set exclusion_reason = 'exact_duplicate'")
    run_recon(work)
    assert status(work, "R2", "stray_rows") == "fail"


# AC3: R3, each amount column, bronze (cast) equals silver --------------------------------------


def test_ac3_r3_has_one_result_per_candidate_amount_column(built: Settings) -> None:
    subjects = {s for (cid, s) in results(built) if cid == "R3"}
    assert subjects == set(AMOUNT_COLUMNS)
    assert subjects == set(built.net_sales.candidate_columns)


def test_ac3_r3_passes_for_every_column_on_untampered_data(built: Settings) -> None:
    rows = {k: v for k, v in results(built).items() if k[0] == "R3"}
    assert {v[0] for v in rows.values()} == {"pass"}


def test_ac3_r3_sums_are_the_cast_bronze_total_and_the_silver_total(built: Settings) -> None:
    # Net_Amount_2: 85.5 + 40.25 - 8 - 8 (the copy is still in silver) = 109.75
    assert results(built)[("R3", "Net_Amount_2")] == ("pass", 109.75, 109.75, 0)


def test_ac3_a_tampered_silver_amount_fails_that_column_only(work: Settings) -> None:
    execute(work, "update silver_sales set Net_Amount_2 = Net_Amount_2 + 1 where _source_row = 5")
    outcome = run_recon(work)
    got = results(work)
    assert got[("R3", "Net_Amount_2")] == ("fail", 109.75, 110.75, 1)
    others = [k for k in got if k[0] == "R3" and k[1] != "Net_Amount_2"]
    assert {got[k][0] for k in others} == {"pass"}
    assert not outcome.passed


def test_ac3_a_difference_inside_the_tolerance_passes(work: Settings) -> None:
    execute(
        work, "update silver_sales set Net_Amount_2 = Net_Amount_2 + 0.005 where _source_row = 5"
    )
    run_recon(work)
    assert status(work, "R3", "Net_Amount_2") == "pass"


def test_ac3_the_tolerance_comes_from_config(work: Settings, tmp_path: Path) -> None:
    execute(
        work, "update silver_sales set Net_Amount_2 = Net_Amount_2 + 0.005 where _source_row = 5"
    )
    strict = variant(tmp_path / "strict", work, recon={"tolerance_amount": 0.001})
    run_recon(strict)
    assert status(strict, "R3", "Net_Amount_2") == "fail"


def test_ac3_a_difference_exactly_at_the_tolerance_passes(work: Settings) -> None:
    execute(
        work, "update silver_sales set Net_Amount_2 = Net_Amount_2 + 0.01 where _source_row = 5"
    )
    run_recon(work)
    assert status(work, "R3", "Net_Amount_2") == "pass"


def test_ac3_a_negative_difference_fails_too(work: Settings) -> None:
    execute(work, "update silver_sales set Net_Amount_2 = Net_Amount_2 - 1 where _source_row = 5")
    run_recon(work)
    assert results(work)[("R3", "Net_Amount_2")][3] == -1


def test_ac3_a_bronze_value_changed_after_the_build_shows_as_a_difference(
    built: Settings, tmp_path: Path
) -> None:
    # bronze now holds a number too large for decimal(18,4), so its cast total drops the 100
    work = copy_of(built, tmp_path)
    bronze = next(work.paths.bronze.glob("*__RAW_SCJ_SALES.parquet"))
    frame = pl.read_parquet(bronze)
    patched = frame.with_columns(
        pl.when(pl.col("_source_row") == "5")
        .then(pl.lit("12345678901234567890"))
        .otherwise(pl.col("Selling_Amount"))
        .alias("Selling_Amount")
    )
    patched.write_parquet(bronze)
    run_recon(work)
    assert status(work, "R3", "Selling_Amount") == "fail"


def test_ac3_the_columns_checked_follow_net_sales_candidates(
    built: Settings, tmp_path: Path
) -> None:
    work = copy_of(built, tmp_path / "w")
    narrow = variant(
        tmp_path / "narrow",
        work,
        net_sales={"candidate_columns": ["Net_Amount_2", "TAX_AMOUNT"]},
    )
    run_recon(narrow)
    subjects = {s for (cid, s) in results(narrow) if cid == "R3"}
    assert subjects == {"Net_Amount_2", "TAX_AMOUNT"}


def test_ac3_a_column_with_no_values_reconciles_to_zero(built: Settings) -> None:
    # Net_AMOUNT_3 has one value in the layout; AMOUNT_AF_DIS too: a column of blanks sums to 0
    got = results(built)
    assert got[("R3", "TAX_AMOUNT")][1:] == (5, 5, 0)


# AC4: R4, information --------------------------------------------------------------------------


def test_ac4_r4_reports_distinct_customers_products_and_the_date_range(built: Settings) -> None:
    got = results(built)
    assert got[("R4", "customers")][:3] == ("info", None, 2)
    assert got[("R4", "products")][:3] == ("info", None, 2)
    assert got[("R4", "date_min")][0] == "info"
    assert got[("R4", "date_max")][0] == "info"


def test_ac4_r4_date_range_is_in_the_detail(built: Settings) -> None:
    rows = dict(
        query(
            built,
            "select subject, detail from recon_results where check_id = 'R4' and "
            "subject like 'date_%'",
        )
    )
    assert rows == {"date_min": "2019-01-05", "date_max": "2019-03-01"}


def test_ac4_r4_never_fails_the_run(work: Settings) -> None:
    execute(work, "update silver_sales set CustomerCode = null, Date = null, SCJ_CODE_1 = null")
    outcome = run_recon(work)
    assert {r.status for r in outcome.results if r.check_id == "R4"} == {"info"}
    assert results(work)[("R4", "customers")][2] == 0


def test_ac4_r4_uses_the_configured_columns(built: Settings, tmp_path: Path) -> None:
    work = copy_of(built, tmp_path / "w")
    other = variant(
        tmp_path / "other",
        work,
        recon={"product_column": "OrderReference"},
    )
    run_recon(other)
    assert results(other)[("R4", "products")][2] == 3  # O1, O2, O3


# AC5: sql/checks, recon_results, `revint check` ------------------------------------------------


def test_ac5_the_checks_live_in_sql_checks() -> None:
    assert RECON_DIR.name == "checks"
    assert RECON_DIR.parent.name == "sql"
    names = sorted(p.name for p in RECON_DIR.glob("*.sql"))
    assert names and names == sorted(names)
    assert all(n[:2].isdigit() for n in names)


def test_ac5_recon_results_has_the_documented_columns(built: Settings) -> None:
    columns = [
        c
        for (c,) in query(
            built,
            "select column_name from information_schema.columns "
            "where table_name = 'recon_results' order by ordinal_position",
        )
    ]
    assert columns == [
        "check_id",
        "subject",
        "description",
        "status",
        "expected",
        "actual",
        "difference",
        "tolerance",
        "detail",
        "checked_at",
    ]


def test_ac5_recon_results_is_rewritten_not_appended(work: Settings) -> None:
    before = query(work, "select count(*) from recon_results")[0][0]
    run_recon(work)
    run_recon(work)
    assert query(work, "select count(*) from recon_results")[0][0] == before


def test_ac5_every_result_has_a_valid_status_and_a_timestamp(built: Settings) -> None:
    assert query(
        built,
        "select count(*) from recon_results where status not in ('pass', 'fail', 'info') "
        "or checked_at is null or description is null",
    ) == [(0,)]


def test_ac5_tolerance_is_recorded_for_the_amount_checks(built: Settings) -> None:
    assert query(
        built,
        "select distinct tolerance from recon_results where check_id = 'R3'",
    ) == [(0.01,)]
    assert query(
        built,
        "select distinct tolerance from recon_results where check_id in ('R1', 'R2')",
    ) == [(0.0,)]


def test_ac5_run_recon_does_not_touch_silver_or_bronze(built: Settings, tmp_path: Path) -> None:
    work = copy_of(built, tmp_path)
    bronze = next(work.paths.bronze.glob("*__RAW_SCJ_SALES.parquet"))
    before = bronze.read_bytes()
    rows = query(work, "select count(*), sum(Net_Amount_2) from silver_sales")
    run_recon(work)
    assert bronze.read_bytes() == before
    assert query(work, "select count(*), sum(Net_Amount_2) from silver_sales") == rows


def test_ac5_cli_check_exits_zero_when_every_check_passes(
    built: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = copy_of(built, tmp_path)
    for key, value in paths_env(tmp_path, raw=built.paths.raw).items():
        monkeypatch.setenv(key, value)
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 0, result.output
    assert "R1" in result.output
    assert "R3" in result.output
    assert work.paths.warehouse.exists()


def test_ac5_cli_check_exits_non_zero_when_a_check_fails(
    built: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = copy_of(built, tmp_path)
    execute(work, "update silver_sales set Net_Amount_2 = Net_Amount_2 + 1 where _source_row = 5")
    for key, value in paths_env(tmp_path, raw=built.paths.raw).items():
        monkeypatch.setenv(key, value)
    result = runner.invoke(app, ["check"])
    assert result.exit_code == EXIT_CHECK_FAILED
    assert "fail" in result.output.lower()
    assert "Net_Amount_2" in result.output


def test_ac5_exit_code_is_not_one_of_the_existing_codes() -> None:
    assert EXIT_CHECK_FAILED not in {0, 1, 2, 3, 4, 5, 6}


def test_ac5_cli_check_without_a_warehouse_says_to_build_silver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for key, value in paths_env(tmp_path).items():
        monkeypatch.setenv(key, value)
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 4
    assert "build" in result.output.lower()


def test_ac5_cli_check_with_invalid_settings_still_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from revint import config

    bad = tmp_path / "settings.yaml"
    bad.write_text("typo_section:\n  x: 1\n", encoding="utf-8")
    monkeypatch.setattr(config, "DEFAULT_SETTINGS_FILE", bad)
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 1


def test_ac5_output_and_logs_hold_no_cell_values(
    built: Settings, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    with caplog.at_level(logging.DEBUG):
        execute_recon(built)
    out = capsys.readouterr()
    assert SECRET not in out.out + out.err + caplog.text
    stored = query(built, "select * from recon_results")
    assert SECRET not in repr(stored)


def test_ac5_a_failed_stage_changes_nothing(work: Settings) -> None:
    before = query(work, "select count(*) from recon_results")
    execute(work, "drop table silver_excluded_rows")
    with pytest.raises(ReconError):
        run_recon(work)
    assert query(work, "select count(*) from recon_results") == before


# AC6: the settings the checks read -------------------------------------------------------------


def test_ac6_every_ac_has_a_test_in_this_module() -> None:
    names = Path(__file__).read_text(encoding="utf-8")
    for ac in range(1, 6):
        assert f"def test_ac{ac}_" in names


@pytest.mark.realdata
def test_ac1_to_ac5_real_file_reconciles(tmp_path: Path) -> None:
    """Counts only. Needs data/raw and a built data/bronze; builds silver in a temporary file."""
    real = load_settings(env={"REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb")})
    if not list(real.paths.bronze.glob("*__RAW_SCJ_SALES.parquet")):
        pytest.skip("bronze not built: run `uv run revint build bronze` first")
    run_silver(real)
    outcome = run_recon(real)
    got = {(r.check_id, r.subject): r for r in outcome.results}
    assert got[("R1", "bronze_rows")].actual == 662_128
    assert got[("R1", "bronze_rows")].status == "pass"
    assert got[("R2", "silver_rows")].status == "pass"
    assert {s for (c, s) in got if c == "R3"} == set(real.net_sales.candidate_columns)
    assert {got[k].status for k in got if k[0] == "R3"} == {"pass"}
    assert {got[k].status for k in got if k[0] == "R4"} == {"info"}
    assert outcome.passed
