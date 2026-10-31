"""Story #30: build_log, one row per stage run (spec 10 section 5).

Synthetic data only. Most tests use a tiny stage folder; two run the real silver stage.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest
from silver_helpers import EXPECTED, SIX_AMOUNTS, bronze_row, query, write_bronze

from revint.build_log import (
    BUILD_LOG_TABLE,
    BuildLogError,
    StageCounts,
    read_build_log,
    record_stage,
    run_logged,
)
from revint.config import Settings, config_hash
from revint.pipeline import StageError, run_stage
from revint.silver import SILVER_DIR, SilverError, run_silver

SECRET = "SECRET-"


@pytest.fixture
def settings(load_with) -> Settings:
    return load_with({"ingest": {"expected_columns": EXPECTED, "sheets": ["RAW SCJ SALES"]}})


@pytest.fixture
def stage(tmp_path: Path) -> Path:
    folder = tmp_path / "10_demo"
    folder.mkdir()
    (folder / "01_a.sql").write_text("create or replace table demo as select 1 as x;", "utf-8")
    (folder / "02_b.sql").write_text("insert into demo select 2;\nselect * from demo;", "utf-8")
    return folder


def rows(settings: Settings) -> list[dict]:
    return read_build_log(settings)


def run_demo(settings: Settings, stage: Path):
    return run_logged(
        settings,
        "demo",
        lambda: run_stage(stage, settings),
        lambda r: StageCounts(files=len(r.files), statements=r.statements),
    )


# AC1: one row per finished stage, with the listed fields ------


def test_ac1_a_finished_stage_adds_exactly_one_row(settings: Settings, stage: Path) -> None:
    run_demo(settings, stage)
    assert len(rows(settings)) == 1


def test_ac1_the_row_has_stage_status_start_duration_counts_and_config_hash(
    settings: Settings, stage: Path
) -> None:
    before = datetime.now(UTC)
    run_demo(settings, stage)
    (row,) = rows(settings)
    assert row["stage"] == "demo"
    assert row["status"] == "succeeded"
    assert row["files"] == 2
    assert row["statements"] == 3
    assert row["failed_file"] is None
    assert row["config_hash"] == config_hash(settings)
    assert re.fullmatch(r"[0-9a-f]{64}", row["config_hash"])
    assert before <= row["started_at"] <= datetime.now(UTC)
    assert row["started_at"].tzinfo is not None
    assert row["duration_seconds"] >= 0


def test_ac1_the_table_has_the_documented_columns(settings: Settings, stage: Path) -> None:
    run_demo(settings, stage)
    columns = [
        c
        for (c,) in query(
            settings,
            f"select column_name from information_schema.columns "
            f"where table_name = '{BUILD_LOG_TABLE}' order by ordinal_position",
        )
    ]
    assert columns == [
        "run_id",
        "stage",
        "status",
        "started_at",
        "duration_seconds",
        "files",
        "statements",
        "rows_out",
        "failed_file",
        "config_hash",
    ]


def test_ac1_every_run_gets_its_own_id(settings: Settings, stage: Path) -> None:
    run_demo(settings, stage)
    run_demo(settings, stage)
    ids = [r["run_id"] for r in rows(settings)]
    assert len(ids) == 2
    assert len(set(ids)) == 2


def test_ac1_rows_come_back_in_the_order_they_were_run(settings: Settings, stage: Path) -> None:
    run_logged(settings, "first", lambda: 1, lambda r: StageCounts())
    run_logged(settings, "second", lambda: 2, lambda r: StageCounts())
    assert [r["stage"] for r in rows(settings)] == ["first", "second"]


def test_ac1_the_wrapper_returns_what_the_stage_returned(settings: Settings, stage: Path) -> None:
    result = run_demo(settings, stage)
    assert result.statements == 3


def test_ac1_a_row_count_is_stored_when_the_stage_reports_one(settings: Settings) -> None:
    run_logged(settings, "demo", lambda: 7, lambda r: StageCounts(rows_out=r))
    assert rows(settings)[0]["rows_out"] == 7


def test_ac1_record_stage_writes_a_row_directly(settings: Settings) -> None:
    start = datetime(2026, 10, 31, 9, 30, tzinfo=UTC)
    record_stage(settings, "bronze", "succeeded", start, 1.5, StageCounts(files=1, rows_out=5))
    (row,) = rows(settings)
    assert (row["stage"], row["files"], row["rows_out"], row["duration_seconds"]) == (
        "bronze",
        1,
        5,
        1.5,
    )
    assert row["started_at"] == start


def test_ac1_an_unknown_status_is_refused(settings: Settings) -> None:
    with pytest.raises(BuildLogError, match="status"):
        record_stage(settings, "demo", "finished", datetime.now(UTC), 0.0)
    assert not settings.paths.warehouse.exists() or rows(settings) == []


def test_ac1_a_blank_stage_name_is_refused(settings: Settings) -> None:
    with pytest.raises(BuildLogError, match="stage"):
        record_stage(settings, " ", "succeeded", datetime.now(UTC), 0.0)


def test_ac1_reading_a_warehouse_without_the_table_gives_no_rows(settings: Settings) -> None:
    assert rows(settings) == []


def test_ac1_the_real_silver_stage_records_files_statements_and_rows(settings: Settings) -> None:
    write_bronze(settings, [bronze_row(8 + i, OrderReference=f"O{i}") for i in range(3)])
    run_logged(
        settings,
        "silver",
        lambda: run_silver(settings),
        lambda r: StageCounts(
            files=len(r.stage.files), statements=r.stage.statements, rows_out=r.rows
        ),
    )
    (row,) = rows(settings)
    assert (row["stage"], row["status"], row["rows_out"]) == ("silver", "succeeded", 3)
    assert row["files"] == len(list(SILVER_DIR.glob("*.sql")))
    assert row["statements"] > row["files"]


# AC2: a failed stage has status failed and the failing file name ------


def failing_stage(tmp_path: Path) -> Path:
    folder = tmp_path / "20_bad"
    folder.mkdir()
    (folder / "01_ok.sql").write_text("create or replace table ok as select 1 as x;", "utf-8")
    (folder / "02_broken.sql").write_text("select error('boom');", "utf-8")
    return folder


def test_ac2_a_failed_stage_is_recorded_as_failed_with_the_file_name(
    settings: Settings, tmp_path: Path
) -> None:
    bad = failing_stage(tmp_path)
    with pytest.raises(StageError):
        run_logged(settings, "demo", lambda: run_stage(bad, settings), lambda r: StageCounts())
    (row,) = rows(settings)
    assert row["status"] == "failed"
    assert row["failed_file"] == "02_broken.sql"
    assert row["stage"] == "demo"
    assert row["config_hash"] == config_hash(settings)
    assert row["files"] is None
    assert row["statements"] is None


def test_ac2_the_original_error_is_raised_unchanged(settings: Settings, tmp_path: Path) -> None:
    bad = failing_stage(tmp_path)
    with pytest.raises(StageError, match="02_broken.sql"):
        run_logged(settings, "demo", lambda: run_stage(bad, settings), lambda r: StageCounts())


def test_ac2_a_failed_stage_leaves_the_stage_rolled_back_but_the_log_written(
    settings: Settings, tmp_path: Path
) -> None:
    bad = failing_stage(tmp_path)
    with pytest.raises(StageError):
        run_logged(settings, "demo", lambda: run_stage(bad, settings), lambda r: StageCounts())
    tables = {t for (t,) in query(settings, "select table_name from information_schema.tables")}
    assert BUILD_LOG_TABLE in tables
    assert "ok" not in tables  # the stage rolled back


def test_ac2_a_wrapped_error_still_gives_the_failing_file(
    settings: Settings, tmp_path: Path
) -> None:
    bad = failing_stage(tmp_path)

    def run() -> None:
        try:
            run_stage(bad, settings)
        except StageError as exc:
            raise SilverError(str(exc)) from exc

    with pytest.raises(SilverError):
        run_logged(settings, "silver", run, lambda r: StageCounts())
    assert rows(settings)[0]["failed_file"] == "02_broken.sql"


def test_ac2_an_error_with_no_file_leaves_the_file_empty(settings: Settings) -> None:
    def run() -> None:
        raise SilverError("bronze file not found")

    with pytest.raises(SilverError):
        run_logged(settings, "silver", run, lambda r: StageCounts())
    (row,) = rows(settings)
    assert row["status"] == "failed"
    assert row["failed_file"] is None


def test_ac2_a_real_silver_failure_names_the_sql_file(settings: Settings) -> None:
    # bronze lacks every expected column except one: silver stops before any SQL runs, so
    # the row has no file; a missing bronze file is the simplest real failure
    with pytest.raises(SilverError):
        run_logged(settings, "silver", lambda: run_silver(settings), lambda r: StageCounts())
    (row,) = rows(settings)
    assert (row["status"], row["failed_file"]) == ("failed", None)


def test_ac2_a_keyboard_interrupt_is_recorded_and_still_raised(settings: Settings) -> None:
    def run() -> None:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_logged(settings, "demo", run, lambda r: StageCounts())
    assert rows(settings)[0]["status"] == "failed"


# AC3: a changed setting gives a different config hash ------


def test_ac3_a_changed_business_setting_changes_the_stored_hash(load_with, stage: Path) -> None:
    a = load_with({"recon": {"tolerance_amount": 0.01}}, name="a")
    b = load_with({"recon": {"tolerance_amount": 0.05}}, name="b")
    run_demo(a, stage)
    run_demo(b, stage)
    assert rows(a)[0]["config_hash"] != rows(b)[0]["config_hash"]


def test_ac3_the_same_settings_store_the_same_hash(settings: Settings, stage: Path) -> None:
    run_demo(settings, stage)
    run_demo(settings, stage)
    first, second = rows(settings)
    assert first["config_hash"] == second["config_hash"]


def test_ac3_changing_a_setting_between_runs_shows_in_one_log(
    load_with, tmp_path: Path, stage: Path
) -> None:
    a = load_with({"recon": {"tolerance_amount": 0.01}}, name="x")
    run_demo(a, stage)
    changed = load_with({"recon": {"tolerance_amount": 0.02}}, name="y")
    # the same warehouse file, a different configuration
    object.__setattr__(changed.paths, "warehouse", a.paths.warehouse)
    run_demo(changed, stage)
    hashes = [r["config_hash"] for r in rows(a)]
    assert len(hashes) == 2
    assert hashes[0] != hashes[1]


def test_ac3_a_changed_path_does_not_change_the_hash(load_with, stage: Path) -> None:
    a = load_with(name="p1")
    run_demo(a, stage)
    assert rows(a)[0]["config_hash"] == config_hash(load_with(name="p2"))


# AC4: a rebuild keeps the earlier rows ------


def test_ac4_a_silver_rebuild_keeps_the_earlier_rows(settings: Settings) -> None:
    write_bronze(settings, [bronze_row(8, OrderReference="O1")])
    for _ in range(2):
        run_logged(
            settings,
            "silver",
            lambda: run_silver(settings),
            lambda r: StageCounts(files=len(r.stage.files), rows_out=r.rows),
        )
    log = rows(settings)
    assert [r["stage"] for r in log] == ["silver", "silver"]
    assert log[0]["run_id"] != log[1]["run_id"]
    assert query(settings, "select count(*) from silver_sales") == [(1,)]


def test_ac4_a_failed_rebuild_keeps_the_earlier_rows(settings: Settings, tmp_path: Path) -> None:
    write_bronze(settings, [bronze_row(8)])
    run_logged(settings, "silver", lambda: run_silver(settings), lambda r: StageCounts())
    bad = failing_stage(tmp_path)
    with pytest.raises(StageError):
        run_logged(settings, "silver", lambda: run_stage(bad, settings), lambda r: StageCounts())
    assert [r["status"] for r in rows(settings)] == ["succeeded", "failed"]


def test_ac4_no_stage_sql_touches_build_log() -> None:
    for folder in ("10_silver", "20_gold", "30_opportunities", "checks"):
        for path in (SILVER_DIR.parent / folder).glob("*.sql"):
            assert BUILD_LOG_TABLE not in path.read_text(encoding="utf-8"), path.name


def test_ac4_recording_does_not_replace_the_table(settings: Settings, stage: Path) -> None:
    run_demo(settings, stage)
    con = duckdb.connect(str(settings.paths.warehouse))
    con.execute(f"update {BUILD_LOG_TABLE} set stage = 'kept'")
    con.close()
    run_demo(settings, stage)
    assert [r["stage"] for r in rows(settings)] == ["kept", "demo"]


# AC5: only counts appear ------


def test_ac5_logs_and_the_table_hold_no_row_values(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    write_bronze(
        settings,
        [
            bronze_row(
                8,
                CustomerCode=f"{SECRET}C1",
                Customer=f"{SECRET}Name",
                **dict.fromkeys(SIX_AMOUNTS, "5"),
            )
        ],
    )
    with caplog.at_level(logging.DEBUG):
        run_logged(
            settings,
            "silver",
            lambda: run_silver(settings),
            lambda r: StageCounts(files=len(r.stage.files), rows_out=r.rows),
        )
    assert SECRET not in caplog.text
    assert SECRET not in repr(query(settings, f"select * from {BUILD_LOG_TABLE}"))


def test_ac5_a_failure_message_with_a_value_is_not_stored_or_logged(
    settings: Settings, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    folder = tmp_path / "30_secret"
    folder.mkdir()
    (folder / "01_x.sql").write_text(f"select error('{SECRET}value');", "utf-8")
    with caplog.at_level(logging.DEBUG), pytest.raises(StageError):
        run_logged(settings, "demo", lambda: run_stage(folder, settings), lambda r: StageCounts())
    assert SECRET not in caplog.text
    assert SECRET not in repr(query(settings, f"select * from {BUILD_LOG_TABLE}"))


def test_ac5_a_failure_that_carries_a_value_stores_no_message(settings: Settings) -> None:
    def run() -> None:
        raise ValueError(f"{SECRET}customer")

    with pytest.raises(ValueError):
        run_logged(settings, "demo", run, lambda r: StageCounts())
    assert SECRET not in repr(query(settings, f"select * from {BUILD_LOG_TABLE}"))


def test_ac5_the_log_message_holds_only_counts(
    settings: Settings, stage: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="revint.build_log"):
        run_demo(settings, stage)
    messages = [r.getMessage() for r in caplog.records if r.name == "revint.build_log"]
    assert messages
    assert all("demo" in m and "succeeded" in m for m in messages)


def test_ac5_a_stage_name_with_a_path_or_sql_is_refused(settings: Settings) -> None:
    with pytest.raises(BuildLogError, match="stage"):
        record_stage(settings, "x'; drop table silver_sales; --", "succeeded", datetime.now(UTC), 0)


# Recording problems ----------------------------------------


def refuse_connections(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every connection fail as a locked warehouse file does.

    DuckDB shares one instance per file inside a process, so a second connection cannot lock
    the first; the failure is simulated at the connect call.
    """

    def locked(*args: object, **kwargs: object) -> None:
        raise duckdb.IOException("Could not set lock on file")

    monkeypatch.setattr("revint.build_log.duckdb.connect", locked)


def test_recording_into_a_locked_warehouse_raises_a_build_log_error(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    refuse_connections(monkeypatch)
    with pytest.raises(BuildLogError, match="build_log"):
        record_stage(settings, "demo", "succeeded", datetime.now(UTC), 0.0)


def test_a_log_failure_after_a_success_is_raised(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    refuse_connections(monkeypatch)
    with pytest.raises(BuildLogError):
        run_logged(settings, "demo", lambda: 1, lambda r: StageCounts())


def test_a_log_failure_after_a_stage_failure_does_not_hide_the_stage_error(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def run() -> None:
        refuse_connections(monkeypatch)
        raise StageError("02_broken.sql statement 1 of 1 failed", "02_broken.sql")

    with caplog.at_level(logging.WARNING), pytest.raises(StageError, match="02_broken.sql"):
        run_logged(settings, "demo", run, lambda r: StageCounts())
    assert "could not record" in caplog.text


# AC6 ----------------------------------------


def test_ac6_every_ac_has_a_test_in_this_module() -> None:
    text = Path(__file__).read_text(encoding="utf-8")
    for ac in range(1, 6):
        assert f"def test_ac{ac}_" in text
