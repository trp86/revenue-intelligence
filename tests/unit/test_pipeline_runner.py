"""Story #29: runner for numbered SQL files (spec 10 section 5)."""

from __future__ import annotations

import logging
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import pytest
from pydantic import BaseModel

from revint.pipeline import (
    EXIT_STAGE_FAILED,
    EXIT_WAREHOUSE_LOCKED,
    StageError,
    WarehouseLockedError,
    execute_stage,
    flatten_parameters,
    run_stage,
    settings_parameters,
)


def write_sql(folder: Path, files: dict[str, str]) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (folder / name).write_text(text, encoding="utf-8")
    return folder


def rows(settings: Any, sql: str) -> list[tuple[Any, ...]]:
    con = duckdb.connect(str(settings.paths.warehouse), read_only=True)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def table_names(settings: Any) -> list[str]:
    if not settings.paths.warehouse.exists():
        return []
    result = rows(settings, "select table_name from information_schema.tables order by 1")
    return [name for (name,) in result]


@contextmanager
def hold_open(path: Path) -> Iterator[None]:
    """Hold the DuckDB file open from another process, as a running API would."""
    path.parent.mkdir(parents=True, exist_ok=True)
    code = (
        "import duckdb, sys, time\n"
        "c = duckdb.connect(sys.argv[1])\n"
        "print('ready', flush=True)\n"
        "time.sleep(60)\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", code, str(path)], stdout=subprocess.PIPE, text=True
    )
    try:
        assert proc.stdout is not None
        assert proc.stdout.readline().strip() == "ready"
        yield
    finally:
        proc.kill()
        proc.wait()
        if proc.stdout is not None:
            proc.stdout.close()


# AC1: files run in filename order ---------------------------------------------


def test_ac1_files_run_in_filename_order(
    tmp_path: Path, load_with, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = load_with()
    stage = write_sql(
        tmp_path / "sql",
        {
            "10_c.sql": "insert into log values ('c');",
            "02_b.sql": "insert into log values ('b');",
            "01_a.sql": "create table log (step varchar); insert into log values ('a');",
        },
    )
    # Make the folder listing come back in reverse so only an explicit sort passes.
    original = Path.iterdir
    monkeypatch.setattr(Path, "iterdir", lambda self: iter(sorted(original(self), reverse=True)))

    result = run_stage(stage, settings)

    assert rows(settings, "select step from log order by rowid") == [("a",), ("b",), ("c",)]
    assert result.files == ("01_a.sql", "02_b.sql", "10_c.sql")
    assert result.statements == 4
    assert result.stage == "sql"


def test_ac1_statements_inside_a_file_run_in_order(tmp_path: Path, load_with) -> None:
    settings = load_with()
    stage = write_sql(
        tmp_path / "sql",
        {
            "01_a.sql": (
                "create table t (n integer);\n"
                "insert into t values (1);\n"
                "-- a comment between statements\n"
                "insert into t values (2);\n"
                "update t set n = n * 10;\n"
            )
        },
    )
    assert run_stage(stage, settings).statements == 4
    assert rows(settings, "select n from t order by n") == [(10,), (20,)]


def test_ac1_only_sql_files_in_the_folder_itself_run(tmp_path: Path, load_with) -> None:
    settings = load_with()
    stage = write_sql(
        tmp_path / "sql",
        {
            "01_a.sql": "create table t (n integer);",
            "02_upper.SQL": "insert into t values (1);",
            "README.md": "not sql",
            ".gitkeep": "",
            "03_notes.txt": "drop table t;",
        },
    )
    write_sql(stage / "sub", {"99_nested.sql": "drop table t;"})
    result = run_stage(stage, settings)
    assert result.files == ("01_a.sql", "02_upper.SQL")
    assert rows(settings, "select count(*) from t") == [(1,)]


def test_ac1_a_file_with_a_byte_order_mark_runs(tmp_path: Path, load_with) -> None:
    settings = load_with()
    stage = tmp_path / "sql"
    stage.mkdir()
    (stage / "01_a.sql").write_bytes(b"\xef\xbb\xbfcreate table t (n integer);\n")
    assert run_stage(stage, settings).files == ("01_a.sql",)
    assert table_names(settings) == ["t"]


def test_ac1_a_successful_stage_is_committed(tmp_path: Path, load_with) -> None:
    settings = load_with()
    stage = write_sql(tmp_path / "sql", {"01_a.sql": "create table t as select 7 as n;"})
    run_stage(stage, settings)
    assert rows(settings, "select n from t") == [(7,)]


def test_ac1_a_stage_can_build_on_an_earlier_stage(tmp_path: Path, load_with) -> None:
    settings = load_with()
    first = write_sql(tmp_path / "10_first", {"01_a.sql": "create table t as select 1 as n;"})
    second = write_sql(tmp_path / "20_second", {"01_b.sql": "insert into t values (2);"})
    run_stage(first, settings)
    run_stage(second, settings)
    assert rows(settings, "select n from t order by n") == [(1,), (2,)]


def test_ac1_an_empty_stage_folder_succeeds_with_zero_files(tmp_path: Path, load_with) -> None:
    settings = load_with()
    stage = write_sql(tmp_path / "sql", {".gitkeep": ""})
    result = run_stage(stage, settings)
    assert result.files == ()
    assert result.statements == 0


def test_ac1_a_missing_stage_folder_fails_naming_it(tmp_path: Path, load_with) -> None:
    with pytest.raises(StageError, match="stage folder not found"):
        run_stage(tmp_path / "no_such_stage", load_with())


def test_ac1_the_warehouse_folder_is_created_when_absent(tmp_path: Path, load_with) -> None:
    settings = load_with()
    assert not settings.paths.warehouse.parent.exists()
    stage = write_sql(tmp_path / "sql", {"01_a.sql": "create table t (n integer);"})
    run_stage(stage, settings)
    assert settings.paths.warehouse.is_file()


def test_ac1_an_explicit_warehouse_overrides_the_settings_path(
    tmp_path: Path, load_with
) -> None:
    settings = load_with()
    other = tmp_path / "other" / "w.duckdb"
    stage = write_sql(tmp_path / "sql", {"01_a.sql": "create table t (n integer);"})
    run_stage(stage, settings, warehouse=other)
    assert other.is_file()
    assert not settings.paths.warehouse.exists()


# AC2: a failing file rolls the whole stage back --------------------------------


def test_ac2_failing_second_file_rolls_back_the_first(tmp_path: Path, load_with) -> None:
    settings = load_with()
    stage = write_sql(
        tmp_path / "sql",
        {
            "01_ok.sql": (
                "create table made_by_first (n integer); insert into made_by_first values (1);"
            ),
            "02_bad.sql": "select * from table_that_does_not_exist;",
            "03_after.sql": "create table made_by_third (n integer);",
        },
    )
    with pytest.raises(StageError) as info:
        run_stage(stage, settings)
    assert info.value.file == "02_bad.sql"
    assert "02_bad.sql" in str(info.value)
    assert table_names(settings) == [], "nothing from the stage may remain"


def test_ac2_rollback_leaves_earlier_committed_work_untouched(
    tmp_path: Path, load_with
) -> None:
    settings = load_with()
    good = write_sql(tmp_path / "10_good", {"01_a.sql": "create table t as select 1 as n;"})
    bad = write_sql(
        tmp_path / "20_bad",
        {
            "01_a.sql": "insert into t values (2); create table extra as select 1 as n;",
            "02_b.sql": "select * from missing;",
        },
    )
    run_stage(good, settings)
    with pytest.raises(StageError):
        run_stage(bad, settings)
    assert rows(settings, "select n from t") == [(1,)]
    assert table_names(settings) == ["t"]


def test_ac2_a_failure_inside_one_file_reports_the_statement_number(
    tmp_path: Path, load_with
) -> None:
    settings = load_with()
    stage = write_sql(
        tmp_path / "sql",
        {"01_a.sql": "create table t (n integer); select * from missing; select 1;"},
    )
    with pytest.raises(StageError, match=r"01_a\.sql statement 2 of 3"):
        run_stage(stage, settings)
    assert table_names(settings) == []


def test_ac2_a_syntax_error_names_the_file_and_runs_nothing(tmp_path: Path, load_with) -> None:
    settings = load_with()
    stage = write_sql(
        tmp_path / "sql",
        {"01_ok.sql": "create table t (n integer);", "02_syntax.sql": "selec 1;"},
    )
    with pytest.raises(StageError) as info:
        run_stage(stage, settings)
    assert info.value.file == "02_syntax.sql"
    assert "cannot parse" in str(info.value)
    assert table_names(settings) == []


def test_ac2_error_text_masks_quoted_values(tmp_path: Path, load_with) -> None:
    settings = load_with()
    stage = write_sql(
        tmp_path / "sql", {"01_a.sql": "select cast('SECRET-VALUE-123' as integer);"}
    )
    with pytest.raises(StageError) as info:
        run_stage(stage, settings)
    assert "SECRET-VALUE-123" not in str(info.value)
    assert "<masked>" in str(info.value)
    assert "Conversion" in str(info.value)


def test_ac2_the_error_message_is_a_single_line(tmp_path: Path, load_with) -> None:
    settings = load_with()
    stage = write_sql(tmp_path / "sql", {"01_a.sql": "select * from missing_table;"})
    with pytest.raises(StageError) as info:
        run_stage(stage, settings)
    assert "\n" not in str(info.value)


def test_ac2_execute_stage_prints_the_failing_file_and_returns_non_zero(
    tmp_path: Path, load_with, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = load_with()
    stage = write_sql(
        tmp_path / "10_silver",
        {"01_ok.sql": "create table t (n integer);", "02_bad.sql": "select * from missing;"},
    )
    code = execute_stage(stage, settings)
    captured = capsys.readouterr()
    assert code == EXIT_STAGE_FAILED != 0
    assert "02_bad.sql" in captured.err
    assert "10_silver" in captured.err
    assert "no changes were made" in captured.err
    assert "Traceback" not in captured.err + captured.out
    assert table_names(settings) == []


def test_ac2_execute_stage_reports_a_success_with_counts(
    tmp_path: Path, load_with, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = load_with()
    stage = write_sql(
        tmp_path / "10_silver",
        {"01_a.sql": "create table t (n integer);", "02_b.sql": "insert into t values (1);"},
    )
    assert execute_stage(stage, settings) == 0
    out = capsys.readouterr().out
    assert "10_silver" in out
    assert "2 files" in out and "2 statements" in out


def test_ac2_exit_codes_are_distinct_and_non_zero() -> None:
    assert EXIT_STAGE_FAILED != 0
    assert EXIT_WAREHOUSE_LOCKED != 0
    assert EXIT_STAGE_FAILED != EXIT_WAREHOUSE_LOCKED


# AC3: named parameters come from Settings --------------------------------------


def test_ac3_parameters_are_taken_from_settings(tmp_path: Path, load_with) -> None:
    settings = load_with()
    stage = write_sql(
        tmp_path / "sql",
        {
            "01_a.sql": (
                "create table p as select $asof_date as d, $recon_tolerance_amount as tol, "
                "$duplicates_exclude_from_net_sales as ex, $void_blank_means as vb, "
                "$net_sales_field as nf, $ingest_header_search_rows as hr;"
            )
        },
    )
    run_stage(stage, settings)
    assert rows(settings, "select d, tol, ex, vb, nf, hr from p") == [
        (date(2020, 2, 29), 0.01, True, "not_void", "Net AMOUNT", 30)
    ]


def test_ac3_a_changed_setting_changes_the_value_with_no_code_edit(
    tmp_path: Path, load_with
) -> None:
    sql = {"01_a.sql": "create table p as select $asof_date as d, $recon_tolerance_amount as t;"}
    first = load_with({"asof": {"date": "2019-12-31"}, "recon": {"tolerance_amount": 0.5}}, "a")
    run_stage(write_sql(tmp_path / "sql_a", sql), first)
    assert rows(first, "select d, t from p") == [(date(2019, 12, 31), 0.5)]


def test_ac3_list_parameters_are_bound_as_lists(tmp_path: Path, load_with) -> None:
    settings = load_with({"ingest": {"sheets": ["A", "B"]}})
    stage = write_sql(
        tmp_path / "sql", {"01_a.sql": "create table p as select $ingest_sheets as s;"}
    )
    run_stage(stage, settings)
    assert rows(settings, "select s from p") == [(["A", "B"],)]


def test_ac3_unset_duplicate_key_columns_are_bound_as_the_derived_list(
    tmp_path: Path, load_with
) -> None:
    settings = load_with({"ingest": {"expected_columns": ["A", "_source_row", "B"]}})
    stage = write_sql(
        tmp_path / "sql", {"01_a.sql": "create table p as select $duplicates_key_columns as k;"}
    )
    run_stage(stage, settings)
    assert rows(settings, "select k from p") == [(["A", "B"],)]


def test_ac3_a_missing_parameter_fails_naming_it_and_runs_nothing(
    tmp_path: Path, load_with
) -> None:
    settings = load_with()
    stage = write_sql(
        tmp_path / "sql",
        {
            "01_ok.sql": "create table t (n integer);",
            "02_param.sql": "select 1; select $no_such_setting, $asof_date, $also_missing;",
        },
    )
    with pytest.raises(StageError) as info:
        run_stage(stage, settings)
    message = str(info.value)
    assert "$no_such_setting" in message
    assert "$also_missing" in message
    assert "$asof_date" not in message
    assert "02_param.sql statement 2" in message
    assert info.value.file == "02_param.sql"
    assert table_names(settings) == []


def test_ac3_paths_and_maps_are_not_parameters(tmp_path: Path, load_with) -> None:
    settings = load_with()
    params = settings_parameters(settings)
    assert not [k for k in params if k.startswith("paths_")]
    assert "void_value_map" not in params
    assert "labels_channel_map" not in params
    for name in ("paths_raw", "void_value_map"):
        stage = write_sql(tmp_path / name, {"01_a.sql": f"select ${name};"})
        with pytest.raises(StageError, match=name):
            run_stage(stage, settings)


def test_ac3_a_dollar_name_inside_a_string_literal_is_not_a_parameter(
    tmp_path: Path, load_with
) -> None:
    settings = load_with()
    stage = write_sql(
        tmp_path / "sql", {"01_a.sql": "create table t as select '$not_a_parameter' as s;"}
    )
    run_stage(stage, settings)
    assert rows(settings, "select s from t") == [("$not_a_parameter",)]


def test_ac3_parameter_names_are_section_then_key() -> None:
    from revint.config import load_settings

    params = settings_parameters(load_settings(env={}))
    assert params["asof_date"] == date(2020, 2, 29)
    assert params["net_sales_field"] == "Net AMOUNT"
    assert params["ingest_sheets"] == ["RAW SCJ SALES"]
    assert params["duplicates_key_columns"] == []
    assert list(params) == sorted(set(params), key=list(params).index), "names are unique"


def test_ac3_colliding_parameter_names_are_refused() -> None:
    class Inner(BaseModel):
        c: int = 1

    class Outer(BaseModel):
        b: Inner = Inner()
        b_c: int = 2

    with pytest.raises(ValueError, match="o_b_c"):
        flatten_parameters(Outer(), "o")


def test_ac3_only_the_parameters_a_statement_names_are_bound(
    tmp_path: Path, load_with
) -> None:
    # DuckDB rejects extra bound values, so a statement with no parameters must still run.
    settings = load_with()
    stage = write_sql(tmp_path / "sql", {"01_a.sql": "create table t (n integer);"})
    assert run_stage(stage, settings).statements == 1


# AC4: a locked warehouse fails clearly -----------------------------------------


def test_ac4_locked_warehouse_raises_a_clear_error(tmp_path: Path, load_with) -> None:
    settings = load_with()
    stage = write_sql(tmp_path / "sql", {"01_a.sql": "create table t (n integer);"})
    with hold_open(settings.paths.warehouse), pytest.raises(WarehouseLockedError) as info:
        run_stage(stage, settings)
    message = str(info.value)
    assert "in use by another process" in message
    assert str(settings.paths.warehouse) in message
    assert "\n" not in message


def test_ac4_execute_stage_prints_a_message_with_no_traceback(
    tmp_path: Path, load_with, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = load_with()
    stage = write_sql(tmp_path / "10_silver", {"01_a.sql": "create table t (n integer);"})
    with hold_open(settings.paths.warehouse):
        code = execute_stage(stage, settings)
    captured = capsys.readouterr()
    assert code == EXIT_WAREHOUSE_LOCKED
    assert "in use by another process" in captured.err
    assert "10_silver" in captured.err
    assert "Traceback" not in captured.err + captured.out
    assert captured.out == ""


def test_ac4_nothing_runs_while_the_warehouse_is_locked(tmp_path: Path, load_with) -> None:
    settings = load_with()
    stage = write_sql(tmp_path / "sql", {"01_a.sql": "create table t (n integer);"})
    with hold_open(settings.paths.warehouse):
        with pytest.raises(WarehouseLockedError):
            run_stage(stage, settings)
    assert table_names(settings) == []


def test_ac4_the_stage_runs_once_the_lock_is_released(tmp_path: Path, load_with) -> None:
    settings = load_with()
    stage = write_sql(tmp_path / "sql", {"01_a.sql": "create table t (n integer);"})
    with hold_open(settings.paths.warehouse):
        with pytest.raises(WarehouseLockedError):
            run_stage(stage, settings)
    assert run_stage(stage, settings).files == ("01_a.sql",)
    assert table_names(settings) == ["t"]


def test_ac4_an_unusable_warehouse_folder_is_a_clear_stage_error(
    tmp_path: Path, load_with
) -> None:
    settings = load_with()
    blocker = tmp_path / "not_a_folder"
    blocker.write_text("file", encoding="utf-8")
    stage = write_sql(tmp_path / "sql", {"01_a.sql": "create table t (n integer);"})
    with pytest.raises(StageError, match="warehouse"):
        run_stage(stage, settings, warehouse=blocker / "w.duckdb")


# Logging carries counts only ---------------------------------------------------


def test_logs_carry_counts_and_no_sql_or_row_values(
    tmp_path: Path, load_with, caplog: pytest.LogCaptureFixture
) -> None:
    settings = load_with()
    stage = write_sql(
        tmp_path / "sql",
        {"01_a.sql": "create table t as select 'ROW-VALUE-98765' as secret;"},
    )
    with caplog.at_level(logging.DEBUG, logger="revint"):
        run_stage(stage, settings)
    assert caplog.records, "the runner should log the stage result"
    assert "1 files" in caplog.text and "1 statements" in caplog.text
    assert "ROW-VALUE-98765" not in caplog.text
    assert "create table" not in caplog.text


def test_logs_on_failure_name_the_file_and_hide_values(
    tmp_path: Path, load_with, caplog: pytest.LogCaptureFixture
) -> None:
    settings = load_with()
    stage = write_sql(
        tmp_path / "sql", {"01_a.sql": "select cast('ROW-VALUE-98765' as integer);"}
    )
    with caplog.at_level(logging.DEBUG, logger="revint"), pytest.raises(StageError):
        run_stage(stage, settings)
    assert "01_a.sql" in caplog.text
    assert "ROW-VALUE-98765" not in caplog.text
