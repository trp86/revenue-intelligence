"""Story #87: `revint build gold`, `revint build all` with gold, and the E2 acceptance run.

Synthetic workbooks only; customer codes carry a SECRET- marker to prove none reaches output, logs
or `build_log`. The real-file tests are marked `realdata`: they work on a copy of `data/bronze`
with a temporary warehouse, run the real commands, and assert counts, sums and structure only.
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
import yaml
from silver_helpers import EXPECTED, query
from typer.testing import CliRunner

from revint.build import execute_build_all, execute_gold
from revint.build_log import read_build_log
from revint.cli import app
from revint.config import DEFAULT_SETTINGS_FILE, Settings, load_settings
from revint.data_dictionary import DICTIONARY_FILE, GOLD_TABLES, build_dictionary
from revint.gold import GOLD_DIR
from revint.silver import run_silver

runner = CliRunner()
S = "SECRET-"
DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def write_workbook(path: Path) -> None:
    """Header on Excel row 4: two customers in two branches and months, a copy, the stray row."""
    path.parent.mkdir(parents=True, exist_ok=True)
    book = xlsxwriter.Workbook(str(path))
    sheet = book.add_worksheet("RAW SCJ SALES")
    for col, name in enumerate(EXPECTED):
        sheet.write(3, col, name)
    base: dict[str, Any] = {
        "Customer": f"{S}name",
        "SCJ_CODE_1": "P1",
        "Product_Decription": f"{S}product",
        "Internal_Category": f"{S}cat",
        "Channel_Category": "GT",
        "Quantity(PCS)": 1,
    }
    lines = [
        {
            **base,
            "OrderReference": "O1",
            "CustomerCode": f"{S}C1",
            "Branch_Name": "Magway",
            "Date": "2019-01-10",
            "Net_Amount_2": 10,
            "Selling_Amount": 20,
        },
        {
            **base,
            "OrderReference": "O2",
            "CustomerCode": f"{S}C2",
            "Branch_Name": "PYAY",
            "Date": "2019-02-10",
            "Net_Amount_2": 7,
            "Selling_Amount": 14,
        },
        {
            **base,
            "OrderReference": "O2",
            "CustomerCode": f"{S}C2",
            "Branch_Name": "PYAY",
            "Date": "2019-02-10",
            "Net_Amount_2": 7,
            "Selling_Amount": 14,
        },
        {"Change_to_Ctn": 1},
    ]
    for offset, line in enumerate(lines):
        for name, value in line.items():
            sheet.write(4 + offset, EXPECTED.index(name), value)
    book.close()


def settings_in(root: Path, raw: Path | None = None, **sections: dict[str, Any]) -> Settings:
    env = {
        "REVINT_PATHS_RAW": str(raw or root / "raw"),
        "REVINT_PATHS_BRONZE": str(root / "bronze"),
        "REVINT_PATHS_WAREHOUSE": str(root / "warehouse.duckdb"),
        "REVINT_PATHS_APP_DB": str(root / "app.duckdb"),
        "REVINT_PATHS_REPORTS": str(root / "reports"),
    }
    if not sections:
        return load_settings(DEFAULT_SETTINGS_FILE, env=env)
    data = yaml.safe_load(DEFAULT_SETTINGS_FILE.read_text(encoding="utf-8"))
    for name, keys in sections.items():
        data[name] = {**data.get(name, {}), **keys}
    config_file = root / "config" / "settings.yaml"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return load_settings(config_file, env=env)


def use(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in {
        "RAW": settings.paths.raw,
        "BRONZE": settings.paths.bronze,
        "WAREHOUSE": settings.paths.warehouse,
        "APP_DB": settings.paths.app_db,
        "REPORTS": settings.paths.reports,
    }.items():
        monkeypatch.setenv(f"REVINT_PATHS_{key}", str(value))


def hashes(folder: Path) -> dict[str, str]:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.iterdir())}


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    """Workbook -> `build all` once (bronze, silver, gold)."""
    root = tmp_path_factory.mktemp("buildgold")
    write_workbook(root / "raw" / "sales.xlsx")
    settings = settings_in(root)
    assert execute_build_all(settings) == 0
    return settings


@pytest.fixture
def silver_only(tmp_path: Path, built: Settings) -> Settings:
    """Bronze and silver built, no gold: a private copy of the warehouse with gold dropped."""
    shutil.copytree(built.paths.bronze, tmp_path / "bronze")
    shutil.copy(built.paths.warehouse, tmp_path / "warehouse.duckdb")
    settings = settings_in(tmp_path, raw=built.paths.raw)
    con = duckdb.connect(str(settings.paths.warehouse))
    try:
        for name, kind in con.execute(
            "select table_name, table_type from information_schema.tables"
        ).fetchall():
            if name.startswith(("dim_", "fact_", "mart_", "gold_")) or name == "v_net_sales":
                con.execute(f"drop {'view' if kind == 'VIEW' else 'table'} if exists {name}")
        con.execute("drop table if exists recon_results")
    finally:
        con.close()
    return settings


# AC1: build gold runs sql/20_gold in one transaction, is recorded, fails clearly ------


def test_ac1_build_gold_builds_every_gold_object_from_silver(
    silver_only: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    use(silver_only, monkeypatch)
    result = runner.invoke(app, ["build", "gold"])
    assert result.exit_code == 0, result.output
    tables = {t for (t,) in query(silver_only, "select table_name from information_schema.tables")}
    assert set(GOLD_TABLES) <= tables


def test_ac1_it_prints_files_statements_and_the_fact_rows(
    silver_only: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    assert execute_gold(silver_only) == 0
    out = capsys.readouterr().out
    assert f"{len(list(GOLD_DIR.glob('*.sql')))} files" in out
    assert "2 fact rows" in out  # two sales lines are loaded (the copy and the stray row are not)


def test_ac1_the_run_is_recorded_in_build_log(silver_only: Settings) -> None:
    execute_gold(silver_only)
    last = read_build_log(silver_only)[-1]
    assert (last["stage"], last["status"]) == ("gold", "succeeded")
    assert last["files"] == len(list(GOLD_DIR.glob("*.sql")))
    assert last["rows_out"] == 2
    assert last["statements"] > last["files"]


def test_ac1_the_stage_runs_in_one_transaction(
    silver_only: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken = GOLD_DIR.parent / "99_broken_gold"
    broken.mkdir(exist_ok=True)
    try:
        (broken / "01_ok.sql").write_text(
            "create or replace table dim_branch as select 1 as x;", "utf-8"
        )
        (broken / "02_bad.sql").write_text("select error('boom');", "utf-8")
        monkeypatch.setattr("revint.gold.GOLD_DIR", broken)
        use(silver_only, monkeypatch)
        before = query(silver_only, "select count(*) from information_schema.tables")
        result = runner.invoke(app, ["build", "gold"])
    finally:
        shutil.rmtree(broken, ignore_errors=True)
    assert result.exit_code == 4
    assert "02_bad.sql" in result.output
    assert query(silver_only, "select count(*) from information_schema.tables") == before


def test_ac1_a_failed_gold_stage_is_recorded_as_failed_with_the_file(
    silver_only: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken = GOLD_DIR.parent / "99_broken_gold"
    broken.mkdir(exist_ok=True)
    try:
        (broken / "01_bad.sql").write_text("select error('boom');", "utf-8")
        monkeypatch.setattr("revint.gold.GOLD_DIR", broken)
        execute_gold(silver_only)
    finally:
        shutil.rmtree(broken, ignore_errors=True)
    last = read_build_log(silver_only)[-1]
    assert (last["stage"], last["status"], last["failed_file"]) == ("gold", "failed", "01_bad.sql")


def test_ac1_it_fails_clearly_when_silver_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = settings_in(tmp_path, raw=tmp_path / "raw")
    use(empty, monkeypatch)
    result = runner.invoke(app, ["build", "gold"])
    assert result.exit_code == 4
    assert "revint build silver" in result.output
    assert "Traceback" not in result.output


def test_ac1_a_missing_silver_is_recorded_as_a_failed_gold_run(tmp_path: Path) -> None:
    empty = settings_in(tmp_path, raw=tmp_path / "raw")
    assert execute_gold(empty) == 4
    assert [(r["stage"], r["status"]) for r in read_build_log(empty)] == [("gold", "failed")]


def test_ac1_a_warehouse_without_silver_tables_is_refused_naming_them(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "warehouse.duckdb"
    duckdb.connect(str(path)).close()
    settings = settings_in(tmp_path, raw=tmp_path / "raw")
    assert execute_gold(settings) == 4
    assert "silver_sales" in capsys.readouterr().err


def test_ac1_it_reports_a_locked_warehouse(
    silver_only: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_connect = duckdb.connect

    def locked(database: str = ":memory:", *args: object, **kwargs: object):
        if database == ":memory:" or kwargs.get("read_only"):
            return real_connect(database, *args, **kwargs)
        raise duckdb.IOException("Could not set lock on file")

    monkeypatch.setattr("revint.pipeline.runner.duckdb.connect", locked)
    use(silver_only, monkeypatch)
    result = runner.invoke(app, ["build", "gold"])
    assert result.exit_code == 5
    assert "in use" in result.output


def test_ac1_build_gold_does_not_read_bronze_or_the_raw_folder(
    silver_only: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    shutil.rmtree(silver_only.paths.bronze)
    root = silver_only.paths.bronze.parent
    use(settings_in(root, raw=root / "no_such_raw_folder"), monkeypatch)
    assert runner.invoke(app, ["build", "gold"]).exit_code == 0


def test_ac1_build_gold_with_invalid_settings_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from revint import config

    bad = tmp_path / "settings.yaml"
    bad.write_text("typo_section:\n  x: 1\n", encoding="utf-8")
    monkeypatch.setattr(config, "DEFAULT_SETTINGS_FILE", bad)
    assert runner.invoke(app, ["build", "gold"]).exit_code == 1


def test_ac1_build_gold_leaves_silver_untouched(silver_only: Settings) -> None:
    before = query(silver_only, "select count(*), sum(Net_Amount_2) from silver_sales")
    execute_gold(silver_only)
    assert query(silver_only, "select count(*), sum(Net_Amount_2) from silver_sales") == before


# AC2: build all runs bronze, silver and gold ------


def test_ac2_build_all_runs_the_three_stages_in_order(built: Settings) -> None:
    assert [r["stage"] for r in read_build_log(built)] == ["bronze", "silver", "gold"]
    assert {r["status"] for r in read_build_log(built)} == {"succeeded"}


def test_ac2_it_no_longer_says_that_no_gold_stage_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_workbook(tmp_path / "raw" / "sales.xlsx")
    use(settings_in(tmp_path), monkeypatch)
    result = runner.invoke(app, ["build", "all"])
    assert result.exit_code == 0, result.output
    assert "no gold stage" not in result.output
    assert "bronze, silver and gold built" in result.output
    out = result.output
    assert out.index("bronze") < out.index("silver") < out.index("gold:")


def test_ac2_a_failing_silver_stops_build_all_before_gold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_workbook(tmp_path / "raw" / "sales.xlsx")
    settings = settings_in(tmp_path)
    use(settings, monkeypatch)
    monkeypatch.setattr("revint.build.execute_silver", lambda s: 4)
    result = runner.invoke(app, ["build", "all"])
    assert result.exit_code == 4
    assert "stopped at the silver stage" in result.output
    tables = {t for (t,) in query(settings, "select table_name from information_schema.tables")}
    assert "fact_sales" not in tables


def test_ac2_a_failing_gold_fails_build_all_and_says_which_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_workbook(tmp_path / "raw" / "sales.xlsx")
    use(settings_in(tmp_path), monkeypatch)
    monkeypatch.setattr("revint.build.execute_gold", lambda s: 4)
    result = runner.invoke(app, ["build", "all"])
    assert result.exit_code == 4
    assert "stopped at the gold stage" in result.output


def test_ac2_build_all_regenerates_nothing_outside_the_warehouse(built: Settings) -> None:
    assert not built.paths.reports.exists()
    assert sorted(p.name for p in built.paths.raw.iterdir()) == ["sales.xlsx"]


# AC3: revint check includes the gold checks; real file under both settings ------


def test_ac3_check_includes_the_gold_checks_after_build_gold(
    silver_only: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    execute_gold(silver_only)
    use(silver_only, monkeypatch)
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 0, result.output
    for check in ("R1 bronze_rows", "R7 gold:Net_Amount_2", "G1", "G2", "G3", "G4", "G5"):
        assert check in result.output


@pytest.mark.parametrize("exclude", [True, False])
def test_ac3_check_passes_under_both_duplicate_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exclude: bool
) -> None:
    write_workbook(tmp_path / "raw" / "sales.xlsx")
    settings = settings_in(tmp_path, duplicates={"exclude_from_net_sales": exclude})
    assert execute_build_all(settings) == 0
    from revint.recon import execute_recon

    assert execute_recon(settings) == 0
    rows = query(settings, "select count(*) from fact_sales")[0][0]
    assert rows == (2 if exclude else 3)


def test_ac3_check_exits_non_zero_when_gold_is_tampered(
    silver_only: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    execute_gold(silver_only)
    con = duckdb.connect(str(silver_only.paths.warehouse))
    try:
        con.execute("update fact_sales set net_sales = net_sales + 1 where sales_line_id = 5")
    finally:
        con.close()
    use(silver_only, monkeypatch)
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 7
    assert "G1 fact_net_sales: fail" in result.output


# AC4: bronze is byte-identical; a gold re-run gives identical content ------


def test_ac4_build_gold_leaves_every_bronze_file_byte_identical(silver_only: Settings) -> None:
    before = hashes(silver_only.paths.bronze)
    assert before
    execute_gold(silver_only)
    assert hashes(silver_only.paths.bronze) == before


def gold_content(settings: Settings) -> dict[str, list]:
    out = {}
    for table in GOLD_TABLES:
        out[table] = query(settings, f"select * from {table} order by all")
    return out


def test_ac4_a_gold_re_run_gives_identical_content(silver_only: Settings) -> None:
    execute_gold(silver_only)
    first = gold_content(silver_only)
    execute_gold(silver_only)
    assert gold_content(silver_only) == first


def test_ac4_a_full_re_run_gives_identical_gold_content(built: Settings, tmp_path: Path) -> None:
    root = tmp_path / "again"
    shutil.copytree(built.paths.raw, root / "raw")
    other = settings_in(root)
    assert execute_build_all(other) == 0
    assert gold_content(other) == gold_content(built)


def test_ac4_the_data_dictionary_matches_the_gold_layer_after_build_all(built: Settings) -> None:
    assert build_dictionary(built) == DICTIONARY_FILE.read_text(encoding="utf-8")


# Safety ------


def test_output_logs_and_build_log_hold_no_cell_values(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    write_workbook(tmp_path / "raw" / "sales.xlsx")
    settings = settings_in(tmp_path)
    with caplog.at_level(logging.DEBUG):
        assert execute_build_all(settings) == 0
    out = capsys.readouterr()
    assert S not in out.out + out.err + caplog.text
    assert S not in repr(query(settings, "select * from build_log"))


def test_build_gold_is_no_longer_a_stub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    use(settings_in(tmp_path, raw=tmp_path / "raw"), monkeypatch)
    result = runner.invoke(app, ["build", "gold"])
    assert "not implemented" not in result.output.lower()
    assert result.exit_code == 4  # a real failure (no silver), not the stub's exit 3


# AC6 ------


def test_ac6_every_ac_has_a_test_in_this_module() -> None:
    text = Path(__file__).read_text(encoding="utf-8")
    for ac in range(1, 5):
        assert f"def test_ac{ac}_" in text
    assert "def test_ac5_" in text


# AC3, AC4, AC5: the real file ------


@pytest.fixture(scope="module")
def real(tmp_path_factory: pytest.TempPathFactory):
    """`build silver`, `build gold` and `check` on a copy of the real bronze files."""
    source = load_settings(env={})
    if not DATA_DIR.is_dir() or not list(source.paths.bronze.glob("*__RAW_SCJ_SALES.parquet")):
        pytest.skip("bronze not built: run `uv run revint build bronze` first")
    root = tmp_path_factory.mktemp("e2acceptance")
    shutil.copytree(source.paths.bronze, root / "bronze")
    env = {
        "REVINT_PATHS_BRONZE": str(root / "bronze"),
        "REVINT_PATHS_WAREHOUSE": str(root / "warehouse.duckdb"),
        "REVINT_PATHS_REPORTS": str(root / "reports"),
    }
    before = hashes(root / "bronze")
    runs = {}
    for name, args in (("silver", ["build", "silver"]), ("gold", ["build", "gold"])):
        runs[name] = runner.invoke(app, args, env=env)
    runs["check"] = runner.invoke(app, ["check"], env=env)
    settings = load_settings(env=env)
    return settings, before, hashes(root / "bronze"), runs


@pytest.mark.realdata
def test_ac3_ac4_real_build_gold_and_check_pass(real) -> None:
    settings, before, after, runs = real
    assert runs["silver"].exit_code == 0, runs["silver"].output
    assert runs["gold"].exit_code == 0, runs["gold"].output
    assert runs["check"].exit_code == 0, runs["check"].output
    assert after == before  # bronze is byte-identical


@pytest.mark.realdata
def test_ac3_real_check_lists_every_gold_check(real) -> None:
    _, _, _, runs = real
    out = runs["check"].output
    for check in ("G1 fact_net_sales: pass", "G5 fact_rows: pass"):
        assert check in out
    assert out.count("G2 ") == 9 and out.count("G3 ") == 5 and out.count("G4 ") == 8
    assert out.count("R7 gold:") == 6
    assert ": fail" not in out


@pytest.mark.realdata
@pytest.mark.parametrize("exclude", [True, False])
def test_ac3_ac5_real_gold_under_both_settings(real, tmp_path: Path, exclude: bool) -> None:
    settings, *_ = real
    shutil.copy(settings.paths.warehouse, tmp_path / "w.duckdb")
    env = {
        "REVINT_PATHS_RAW": str(load_settings(env={}).paths.raw),  # R1 reads the real workbook
        "REVINT_PATHS_BRONZE": str(settings.paths.bronze),
        "REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb"),
    }
    data = yaml.safe_load(DEFAULT_SETTINGS_FILE.read_text(encoding="utf-8"))
    data["duplicates"]["exclude_from_net_sales"] = exclude
    config_file = tmp_path / "config" / "settings.yaml"
    config_file.parent.mkdir()
    config_file.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    mine = load_settings(config_file, env=env)
    assert execute_gold(mine) == 0
    from revint.recon import execute_recon

    assert execute_recon(mine) == 0
    assert query(mine, "select count(*) from fact_sales") == [(662_128 - (557 if exclude else 1),)]


@pytest.mark.realdata
def test_ac5_real_dimension_and_mart_counts(real) -> None:
    settings, *_ = real
    counts = {
        table: query(settings, f"select count(*) from {table}")[0][0] for table in GOLD_TABLES
    }
    assert counts["dim_customer"] == 12_240
    assert counts["dim_product"] == 182
    assert counts["dim_branch"] == 34
    assert counts["dim_date"] == 974
    assert counts["fact_sales"] == 661_571
    assert counts["v_net_sales"] == 661_571
    assert counts["mart_customer_profile"] == 12_240
    assert counts["mart_branch_month"] == 944
    assert counts["mart_customer_month"] == 203_183


@pytest.mark.realdata
def test_ac4_real_gold_re_run_gives_identical_content(real, tmp_path: Path) -> None:
    settings, *_ = real
    first = gold_content(settings)
    assert execute_gold(settings) == 0
    assert gold_content(settings) == first


@pytest.mark.realdata
def test_ac5_the_e2_success_measure_on_the_real_file(real) -> None:
    settings, *_ = real
    fact = query(settings, "select sum(net_sales) from fact_sales")[0][0]
    for mart, column in (
        ("mart_customer_month", "net_sales"),
        ("mart_customer_category_month", "net_sales"),
        ("mart_branch_month", "net_sales"),
    ):
        assert query(settings, f"select sum({column}) from {mart}")[0][0] == fact
    assert query(
        settings,
        "select count(*) from recon_results where status = 'fail'",
    ) == [(0,)]
    assert build_dictionary(settings) == DICTIONARY_FILE.read_text(encoding="utf-8")


@pytest.mark.realdata
def test_ac3_real_check_runs_even_when_only_silver_was_built(tmp_path: Path) -> None:
    source = load_settings(env={})
    if not list(source.paths.bronze.glob("*__RAW_SCJ_SALES.parquet")):
        pytest.skip("bronze not built: run `uv run revint build bronze` first")
    settings = load_settings(env={"REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb")})
    run_silver(settings)
    from revint.recon import execute_recon

    assert execute_recon(settings) == 0
