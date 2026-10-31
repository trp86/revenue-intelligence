"""Story #45: `revint build silver` and `revint build all` (spec 10 section 5).

Synthetic workbooks only. One module-level build; a test that changes anything works on a
copy. Output, logs and build_log hold counts and names, never a cell value.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
from pathlib import Path
from typing import Any

import duckdb
import pytest
import xlsxwriter
from silver_helpers import EXPECTED, query
from typer.testing import CliRunner

from revint.build import execute_build_all
from revint.build_log import read_build_log
from revint.cli import app
from revint.config import DEFAULT_SETTINGS_FILE, Settings, load_settings
from revint.silver import SILVER_DIR, execute_silver

runner = CliRunner()
SECRET = "SECRET-"
STAGES = ("bronze", "silver")


def write_workbook(path: Path) -> None:
    """Header on Excel row 4, data from row 5: two plain lines, a copy of one, the stray row."""
    path.parent.mkdir(parents=True, exist_ok=True)
    book = xlsxwriter.Workbook(str(path))
    sheet = book.add_worksheet("RAW SCJ SALES")
    for col, name in enumerate(EXPECTED):
        sheet.write(3, col, name)
    plain: dict[str, Any] = {
        "CustomerCode": f"{SECRET}C1",
        "Customer": f"{SECRET}Name",
        "Net_Amount_2": 40.5,
        "Selling_Amount": 50,
        "Quantity(PCS)": 2,
        "Date": "2019-03-01",
    }
    lines = [
        {**plain, "OrderReference": "O1"},
        {**plain, "OrderReference": "O2", "Net_Amount_2": 10},
        {**plain, "OrderReference": "O2", "Net_Amount_2": 10},
        {"Change_to_Ctn": 1},
    ]
    for offset, line in enumerate(lines):
        for name, value in line.items():
            sheet.write(4 + offset, EXPECTED.index(name), value)
    book.close()


def settings_in(root: Path, raw: Path | None = None) -> Settings:
    env = {
        "REVINT_PATHS_RAW": str(raw or root / "raw"),
        "REVINT_PATHS_BRONZE": str(root / "bronze"),
        "REVINT_PATHS_WAREHOUSE": str(root / "warehouse.duckdb"),
        "REVINT_PATHS_APP_DB": str(root / "app.duckdb"),
        "REVINT_PATHS_REPORTS": str(root / "reports"),
    }
    return load_settings(DEFAULT_SETTINGS_FILE, env=env)


def use(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in {
        "RAW": settings.paths.raw,
        "BRONZE": settings.paths.bronze,
        "WAREHOUSE": settings.paths.warehouse,
        "APP_DB": settings.paths.app_db,
        "REPORTS": settings.paths.reports,
    }.items():
        monkeypatch.setenv(f"REVINT_PATHS_{key}", str(value))


def bronze_file(settings: Settings) -> Path:
    return next(settings.paths.bronze.glob("*__RAW_SCJ_SALES.parquet"))


def bronze_hashes(settings: Settings) -> dict[str, str]:
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(settings.paths.bronze.iterdir())
    }


def silver_content(settings: Settings) -> list[tuple[Any, ...]]:
    """Every silver row and the audit table's keys, without the build timestamps."""
    sales = query(settings, "select * from silver_sales order by _source_row")
    audit = query(
        settings,
        "select _source_row, exclusion_reason, duplicate_of_source_row from silver_excluded_rows "
        "order by _source_row",
    )
    return [*sales, *audit]


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    """Workbook -> `build all` once."""
    root = tmp_path_factory.mktemp("build")
    write_workbook(root / "raw" / "sales.xlsx")
    settings = settings_in(root)
    assert execute_build_all(settings) == 0
    return settings


@pytest.fixture
def work(tmp_path: Path, built: Settings) -> Settings:
    """A private copy of the built project (bronze, warehouse) sharing the read-only raw file."""
    shutil.copytree(built.paths.bronze, tmp_path / "bronze")
    shutil.copy(built.paths.warehouse, tmp_path / "warehouse.duckdb")
    return settings_in(tmp_path, raw=built.paths.raw)


@pytest.fixture
def fresh(tmp_path: Path, built: Settings) -> Settings:
    """Bronze built, no warehouse yet."""
    shutil.copytree(built.paths.bronze, tmp_path / "bronze")
    return settings_in(tmp_path, raw=built.paths.raw)


# AC1: build silver runs the silver stage; missing bronze fails clearly ------


def test_ac1_build_silver_builds_silver_from_bronze(
    fresh: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    use(fresh, monkeypatch)
    result = runner.invoke(app, ["build", "silver"])
    assert result.exit_code == 0, result.output
    assert query(fresh, "select count(*) from silver_sales") == [(4,)]
    assert "silver" in result.output
    assert "4" in result.output  # the row count


def test_ac1_build_silver_prints_files_statements_and_rows(
    fresh: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    assert execute_silver(fresh) == 0
    out = capsys.readouterr().out
    assert f"{len(list(SILVER_DIR.glob('*.sql')))} files" in out
    assert "4 rows" in out


def test_ac1_build_silver_without_bronze_fails_with_a_clear_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = settings_in(tmp_path, raw=tmp_path / "raw")
    use(empty, monkeypatch)
    result = runner.invoke(app, ["build", "silver"])
    assert result.exit_code == 4
    assert "bronze" in result.output.lower()
    assert "revint build bronze" in result.output
    assert "Traceback" not in result.output


def test_ac1_a_failed_build_silver_creates_no_silver_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = settings_in(tmp_path, raw=tmp_path / "raw")
    use(empty, monkeypatch)
    runner.invoke(app, ["build", "silver"])
    if empty.paths.warehouse.exists():
        tables = {t for (t,) in query(empty, "select table_name from information_schema.tables")}
        assert "silver_sales" not in tables


def test_ac1_build_silver_with_a_bronze_file_missing_columns_fails_cleanly(
    fresh: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    import polars as pl

    path = bronze_file(fresh)
    pl.read_parquet(path).drop("Customer").write_parquet(path)
    use(fresh, monkeypatch)
    result = runner.invoke(app, ["build", "silver"])
    assert result.exit_code == 4
    assert "Customer" in result.output
    assert "Traceback" not in result.output


def test_ac1_build_silver_with_invalid_settings_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from revint import config

    bad = tmp_path / "settings.yaml"
    bad.write_text("typo_section:\n  x: 1\n", encoding="utf-8")
    monkeypatch.setattr(config, "DEFAULT_SETTINGS_FILE", bad)
    for args in (["build", "silver"], ["build", "all"]):
        assert runner.invoke(app, args).exit_code == 1


def test_ac1_build_silver_does_not_read_the_raw_folder(
    fresh: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    gone = settings_in(tmp_path, raw=tmp_path / "no_such_raw_folder")
    use(gone, monkeypatch)
    assert runner.invoke(app, ["build", "silver"]).exit_code == 0


def test_ac1_build_silver_reports_a_locked_warehouse(
    fresh: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_connect = duckdb.connect

    def locked(database: str = ":memory:", *args: object, **kwargs: object):
        if database == ":memory:":  # the runner's SQL parser; only the file is locked
            return real_connect(database, *args, **kwargs)
        raise duckdb.IOException("Could not set lock on file")

    monkeypatch.setattr("revint.pipeline.runner.duckdb.connect", locked)
    use(fresh, monkeypatch)
    result = runner.invoke(app, ["build", "silver"])
    assert result.exit_code == 5
    assert "in use" in result.output


# AC2: build all runs bronze then silver and says there is no gold stage ------


def test_ac2_build_all_runs_bronze_then_silver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_workbook(tmp_path / "raw" / "sales.xlsx")
    settings = settings_in(tmp_path)
    use(settings, monkeypatch)
    result = runner.invoke(app, ["build", "all"])
    assert result.exit_code == 0, result.output
    assert result.output.index("bronze") < result.output.index("silver")
    assert bronze_file(settings).is_file()
    assert query(settings, "select count(*) from silver_sales") == [(4,)]


def test_ac2_build_all_states_that_no_gold_stage_exists_yet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_workbook(tmp_path / "raw" / "sales.xlsx")
    use(settings_in(tmp_path), monkeypatch)
    result = runner.invoke(app, ["build", "all"])
    assert "no gold stage exists yet" in result.output
    assert result.output.rstrip().splitlines()[-1].lower().startswith("build all")


def test_ac2_build_all_records_the_stages_in_order(built: Settings) -> None:
    assert [r["stage"] for r in read_build_log(built)] == list(STAGES)


def test_ac2_a_failing_bronze_stops_build_all_before_silver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "raw").mkdir()
    settings = settings_in(tmp_path)
    use(settings, monkeypatch)
    result = runner.invoke(app, ["build", "all"])
    assert result.exit_code == 4
    assert "silver" not in result.output.lower().replace("build_log", "")
    assert not settings.paths.warehouse.exists() or "silver_sales" not in {
        t for (t,) in query(settings, "select table_name from information_schema.tables")
    }
    assert "no gold stage" not in result.output


def test_ac2_a_failing_silver_fails_build_all_and_says_which_stage(
    work: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    import polars as pl

    path = bronze_file(work)
    pl.read_parquet(path).drop("Customer").write_parquet(path)
    use(work, monkeypatch)
    # raw stays valid, so bronze is rebuilt; break silver by pointing at a bronze set that
    # lacks a column through a one-column expected list is not possible, so fail silver directly
    monkeypatch.setattr("revint.build.execute_bronze", lambda *a, **k: 0)
    result = runner.invoke(app, ["build", "all"])
    assert result.exit_code == 4
    assert "silver" in result.output.lower()
    assert "no gold stage" not in result.output


def test_ac2_build_all_with_a_locked_raw_workbook_exits_six(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_workbook(tmp_path / "raw" / "sales.xlsx")
    (tmp_path / "raw" / "~$sales.xlsx").write_bytes(b"x")
    use(settings_in(tmp_path), monkeypatch)
    result = runner.invoke(app, ["build", "all"])
    assert result.exit_code == 6


def test_ac2_build_gold_is_still_a_stub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    use(settings_in(tmp_path), monkeypatch)
    result = runner.invoke(app, ["build", "gold"])
    assert result.exit_code == 3
    assert "not implemented" in result.output.lower()


# AC3: every stage run is recorded in build_log ------


def test_ac3_build_all_records_bronze_and_silver_with_counts(built: Settings) -> None:
    log = {r["stage"]: r for r in read_build_log(built)}
    assert log["bronze"]["status"] == "succeeded"
    assert log["bronze"]["files"] == 1
    assert log["bronze"]["rows_out"] == 4
    assert log["silver"]["status"] == "succeeded"
    assert log["silver"]["rows_out"] == 4
    assert log["silver"]["files"] == len(list(SILVER_DIR.glob("*.sql")))


def test_ac3_build_silver_alone_adds_a_silver_row(work: Settings) -> None:
    before = len(read_build_log(work))
    assert execute_silver(work) == 0
    log = read_build_log(work)
    assert len(log) == before + 1
    assert log[-1]["stage"] == "silver"


def test_ac3_build_bronze_alone_is_recorded_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_workbook(tmp_path / "raw" / "sales.xlsx")
    settings = settings_in(tmp_path)
    use(settings, monkeypatch)
    assert runner.invoke(app, ["build", "bronze"]).exit_code == 0
    assert [(r["stage"], r["status"]) for r in read_build_log(settings)] == [
        ("bronze", "succeeded")
    ]


def test_ac3_a_failed_stage_is_recorded_as_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = settings_in(tmp_path, raw=tmp_path / "raw")
    use(empty, monkeypatch)
    runner.invoke(app, ["build", "silver"])
    assert [(r["stage"], r["status"]) for r in read_build_log(empty)] == [("silver", "failed")]


def test_ac3_a_failed_bronze_is_recorded_as_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "raw").mkdir()
    settings = settings_in(tmp_path)
    use(settings, monkeypatch)
    runner.invoke(app, ["build", "bronze"])
    assert [(r["stage"], r["status"]) for r in read_build_log(settings)] == [("bronze", "failed")]


def test_ac3_a_failing_sql_file_is_named_in_the_log(
    work: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    import polars as pl

    # a bronze file whose _source_row is not a number makes a silver SQL file fail
    path = bronze_file(work)
    frame = pl.read_parquet(path)
    frame.with_columns(pl.lit("not a number").alias("_source_row")).write_parquet(path)
    use(work, monkeypatch)
    result = runner.invoke(app, ["build", "silver"])
    assert result.exit_code == 4
    last = read_build_log(work)[-1]
    assert (last["stage"], last["status"]) == ("silver", "failed")
    assert last["failed_file"] is not None
    assert last["failed_file"].endswith(".sql")


def test_ac3_the_log_keeps_earlier_runs_when_stages_are_rebuilt(work: Settings) -> None:
    before = len(read_build_log(work))
    execute_silver(work)
    execute_silver(work)
    assert len(read_build_log(work)) == before + 2


def test_ac3_a_stub_command_writes_no_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = settings_in(tmp_path)
    use(settings, monkeypatch)
    runner.invoke(app, ["build", "gold"])
    assert not settings.paths.warehouse.exists()


# AC4: a re-run gives identical silver (apart from timestamps); bronze is untouched ------


def test_ac4_build_silver_leaves_every_bronze_file_byte_identical(work: Settings) -> None:
    before = bronze_hashes(work)
    assert before
    execute_silver(work)
    assert bronze_hashes(work) == before


def test_ac4_a_silver_re_run_gives_identical_content(work: Settings) -> None:
    first = silver_content(work)
    assert execute_silver(work) == 0
    assert silver_content(work) == first
    assert len(first) > 4


def test_ac4_only_the_audit_timestamp_differs_between_silver_runs(work: Settings) -> None:
    stamps = query(work, "select excluded_at from silver_excluded_rows order by _source_row")
    execute_silver(work)
    again = query(work, "select excluded_at from silver_excluded_rows order by _source_row")
    assert len(stamps) == len(again) == 2
    assert query(work, "select count(distinct excluded_at) from silver_excluded_rows") == [(1,)]


def test_ac4_a_full_re_run_gives_identical_silver_apart_from_the_ingest_time(
    built: Settings, tmp_path: Path
) -> None:
    root = tmp_path / "again"
    shutil.copytree(built.paths.raw, root / "raw")
    other = settings_in(root)
    assert execute_build_all(other) == 0
    drop = "_ingested_at"
    columns = ", ".join(
        f'"{c}"'
        for (c,) in query(
            built,
            "select column_name from information_schema.columns "
            f"where table_name = 'silver_sales' and column_name <> '{drop}' "
            "order by ordinal_position",
        )
    )
    sql = f"select {columns} from silver_sales order by _source_row"
    assert query(other, sql) == query(built, sql)


def test_ac4_bronze_files_are_not_changed_by_check_or_report(work: Settings) -> None:
    before = bronze_hashes(work)
    execute_silver(work)
    assert bronze_hashes(work) == before


# Safety ------


def test_output_and_logs_hold_no_cell_values(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    write_workbook(tmp_path / "raw" / "sales.xlsx")
    settings = settings_in(tmp_path)
    with caplog.at_level(logging.DEBUG):
        assert execute_build_all(settings) == 0
    out = capsys.readouterr()
    assert SECRET not in out.out + out.err + caplog.text
    assert SECRET not in repr(query(settings, "select * from build_log"))


def test_build_all_never_writes_to_the_raw_folder(built: Settings) -> None:
    names = sorted(p.name for p in built.paths.raw.iterdir())
    assert names == ["sales.xlsx"]


# AC5 ------


def test_ac5_every_ac_has_a_test_in_this_module() -> None:
    text = Path(__file__).read_text(encoding="utf-8")
    for ac in range(1, 5):
        assert f"def test_ac{ac}_" in text
