"""Story #116: `revint opportunities build` (spec 03 section 1, spec 10 section 5).

Synthetic data only: the acceptance warehouse of story #115 (one customer per engine), copied
per test. `execute_opportunities` runs with the case settings of that module, so the counts per
engine are known. The CLI reads the committed settings file (only the warehouse path is set by
environment), so the CLI tests check the wiring, the date option and the exit codes, not the
case counts. Output and build_log hold counts and names, never a customer value."""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import pytest
from silver_helpers import query
from test_opportunity_acceptance import EXPECTED, built, copied, snapshot  # noqa: F401
from typer.testing import CliRunner

from revint.build_log import read_build_log
from revint.cli import app
from revint.config import Settings, config_hash, load_settings
from revint.opportunities import ENGINES, execute_opportunities

runner = CliRunner()
ASOF = date(2020, 2, 29)


def use(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REVINT_PATHS_WAREHOUSE", str(settings.paths.warehouse))


@pytest.fixture
def work(built: Settings, tmp_path: Path) -> Settings:  # noqa: F811
    return copied(built, tmp_path)


# AC1: the command builds the tables and prints the counts per engine ------


def test_ac1_execute_builds_the_tables_and_prints_counts(
    work: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    assert execute_opportunities(work) == 0
    out = capsys.readouterr().out.splitlines()
    for engine in sorted(ENGINES):
        n = len(EXPECTED[engine])
        assert any(line.startswith(f"{engine}: ") and f", {n} triggered," in line for line in out)
    total = sum(len(v) for v in EXPECTED.values())
    assert out[-1].startswith(f"opportunities as of 2020-02-29: {total} opportunities")
    for table in ("opp_opportunities", "opp_evidence", "opp_run_summary"):
        assert query(work, f"select count(*) from {table}")[0][0] > 0, table


def test_ac1_the_cli_command_is_real(work: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    use(work, monkeypatch)
    result = runner.invoke(app, ["opportunities", "build"])
    assert result.exit_code == 0, result.output
    assert "not implemented" not in result.output.lower()
    assert "opportunities as of 2020-02-29:" in result.output
    for engine in ENGINES:
        assert f"{engine}: " in result.output


def test_ac1_output_holds_counts_not_values(
    work: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    use(work, monkeypatch)
    result = runner.invoke(app, ["opportunities", "build"])
    assert "SECRET-" not in result.output


# AC2: --as-of overrides the date for one run ------


def test_ac2_as_of_overrides_the_date(work: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    use(work, monkeypatch)
    result = runner.invoke(app, ["opportunities", "build", "--as-of", "2019-06-30"])
    assert result.exit_code == 0, result.output
    assert "opportunities as of 2019-06-30:" in result.output
    dates = query(work, "select distinct as_of_date from opp_run_summary")
    assert dates == [(date(2019, 6, 30),)]


def test_ac2_the_config_file_is_not_changed(
    work: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    use(work, monkeypatch)
    before = load_settings().asof.date
    runner.invoke(app, ["opportunities", "build", "--as-of", "2019-06-30"])
    assert load_settings().asof.date == before == ASOF


@pytest.mark.parametrize("bad", ["2019-13-01", "30.06.2019", "yesterday", ""])
def test_ac2_an_invalid_date_fails_with_exit_1(
    work: Settings, monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    use(work, monkeypatch)
    result = runner.invoke(app, ["opportunities", "build", "--as-of", bad])
    assert result.exit_code == 1
    assert "--as-of must be a date as YYYY-MM-DD" in result.output
    assert query(
        work,
        "select count(*) from information_schema.tables where table_name = 'opp_opportunities'",
    ) == [(0,)]


# AC3: build_log ------


def test_ac3_a_run_is_recorded_in_build_log(work: Settings) -> None:
    execute_opportunities(work)
    rows = [r for r in read_build_log(work) if r["stage"] == "opportunities"]
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "succeeded"
    assert row["rows_out"] == sum(len(v) for v in EXPECTED.values())
    assert row["files"] == 10 and row["statements"] > 0
    assert row["config_hash"] == config_hash(work)


def test_ac3_a_failure_records_the_failing_file(
    work: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import revint.opportunities as module

    stage = tmp_path / "broken"
    stage.mkdir()
    for path in module.OPPORTUNITIES_DIR.glob("*.sql"):
        shutil.copy(path, stage / path.name)
    (stage / "05_whitespace.sql").write_text("select * from no_such_table;\n", encoding="utf-8")
    monkeypatch.setattr(module, "OPPORTUNITIES_DIR", stage)
    real = module.run_opportunities
    monkeypatch.setattr(module, "run_opportunities", lambda s: real(s, stage_dir=stage))
    assert execute_opportunities(work) == 4
    row = [r for r in read_build_log(work) if r["stage"] == "opportunities"][-1]
    assert (row["status"], row["failed_file"]) == ("failed", "05_whitespace.sql")


# AC4: no gold ------


def test_ac4_no_gold_fails_with_exit_4(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REVINT_PATHS_WAREHOUSE", str(tmp_path / "none.duckdb"))
    result = runner.invoke(app, ["opportunities", "build"])
    assert result.exit_code == 4
    assert "revint build gold" in result.output


def test_ac4_a_warehouse_without_gold_fails_with_exit_4(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import duckdb

    path = tmp_path / "silver_only.duckdb"
    duckdb.connect(str(path)).close()
    monkeypatch.setenv("REVINT_PATHS_WAREHOUSE", str(path))
    result = runner.invoke(app, ["opportunities", "build"])
    assert result.exit_code == 4
    assert "revint build gold" in result.output


# AC5: a rerun is identical ------


def test_ac5_a_rerun_gives_identical_tables(work: Settings) -> None:
    execute_opportunities(work)
    first = snapshot(work)
    execute_opportunities(work)
    assert snapshot(work) == first


# AC6: build all is unchanged ------


def test_ac6_build_all_does_not_run_the_engines() -> None:
    import inspect

    from revint import build

    source = inspect.getsource(build.execute_build_all)
    assert "opportunit" not in source
    # test_build_commands.py pins the stages build all records to these three
    text = (Path(__file__).parent / "test_build_commands.py").read_text(encoding="utf-8")
    assert 'STAGES = ("bronze", "silver", "gold")' in text


# AC7 ------


def test_ac7_every_ac_has_a_test_in_this_module() -> None:
    text = Path(__file__).read_text(encoding="utf-8")
    for ac in range(1, 7):
        assert f"def test_ac{ac}_" in text
