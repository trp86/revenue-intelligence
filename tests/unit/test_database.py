"""Story #195: the API opens its databases by a MotherDuck address when one is configured.

Locally nothing changes: without `database.*` the files in `paths` are used. MotherDuck itself is
not called here; the helper's choice of target and its token handling are checked instead.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from revint import db
from revint.config import ConfigError, Settings, load_settings
from revint.pipeline import settings_parameters

ROOT = Path(__file__).resolve().parents[2]


def with_database(settings: Settings, **values: str) -> Settings:
    return settings.model_copy(update={"database": settings.database.model_copy(update=values)})


def test_ac1_by_default_the_files_in_paths_are_used() -> None:
    settings = load_settings(env={})
    assert settings.database.warehouse is None and settings.database.app_db is None
    assert db.warehouse_target(settings) == str(settings.paths.warehouse)
    assert db.app_db_target(settings) == str(settings.paths.app_db)


def test_ac1_the_production_overlay_points_at_motherduck() -> None:
    settings = load_settings(env={"REVINT_SETTINGS_OVERLAY": "config/settings.production.yaml"})
    assert settings.database.warehouse == "md:revint"
    assert settings.database.app_db == "md:revint_app"


@pytest.mark.parametrize("bad", ["revint", "file.duckdb", "md:", "md:Bad Name", "md:revint;drop"])
def test_ac1_a_database_address_must_be_a_motherduck_name(load_with, bad: str) -> None:
    with pytest.raises(ConfigError, match="database"):
        load_with({"database": {"warehouse": bad}})


def test_ac1_database_is_not_a_sql_parameter() -> None:
    assert not any(n.startswith("database_") for n in settings_parameters(load_settings(env={})))


def test_ac1_a_local_warehouse_is_opened_read_only(tmp_path: Path) -> None:
    file = tmp_path / "w.duckdb"
    duckdb.connect(str(file)).close()
    base = load_settings(env={})
    settings = base.model_copy(update={"paths": base.paths.model_copy(update={"warehouse": file})})
    with db.warehouse(settings) as con:
        with pytest.raises(duckdb.Error, match="read-only"):
            con.execute("create table t (x int)")


def test_ac2_a_motherduck_address_needs_the_token_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MOTHERDUCK_TOKEN", raising=False)
    settings = with_database(load_settings(env={}), warehouse="md:revint")
    with pytest.raises(db.DatabaseError, match="MOTHERDUCK_TOKEN"):
        db.connect_target("md:revint", read_only=True)
    assert db.warehouse_target(settings) == "md:revint"


def test_ac2_the_token_is_passed_as_config_and_never_in_the_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def fake_connect(database: str, **kwargs: object) -> object:
        seen.update(database=database, **kwargs)
        return object()

    monkeypatch.setenv("MOTHERDUCK_TOKEN", "tok_secret_value")
    monkeypatch.setattr(duckdb, "connect", fake_connect)
    db.connect_target("md:revint", read_only=True)
    assert seen["database"] == "md:revint"  # the token is not in the address (it would be logged)
    assert seen["config"] == {"motherduck_token": "tok_secret_value"}


def test_ac2_no_token_is_committed() -> None:
    import subprocess

    tracked = subprocess.run(
        [
            "git",
            "grep",
            "-I",
            "-n",
            "-i",
            "-E",
            r"motherduck_token\s*[=:]\s*['\"]?[a-z0-9._-]{20,}",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    assert tracked == "", "a MotherDuck token looks committed"


# Story #197: the hosted API reaches MotherDuck, and says why when it cannot ------


def test_197_ac2_a_failed_open_is_logged_without_the_token(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    token = "tok_" + "x" * 40

    def failing_connect(database: str, **_kwargs: object) -> object:
        # some errors echo the connection settings; the log must never carry the token
        raise duckdb.IOException(f"IO Error: extension failed (motherduck_token={token})")

    monkeypatch.setenv("MOTHERDUCK_TOKEN", token)
    monkeypatch.setattr(duckdb, "connect", failing_connect)
    caplog.set_level(logging.WARNING, logger="revint.db")
    with pytest.raises(duckdb.IOException):
        db.connect_target("md:revint", read_only=True)
    assert "cannot open md:revint" in caplog.text
    assert "extension failed" in caplog.text  # the real reason is visible in the logs
    assert token not in caplog.text and "***" in caplog.text


def test_197_ac2_a_local_file_error_is_logged_too(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    caplog.set_level(logging.WARNING, logger="revint.db")
    missing = tmp_path / "no" / "such" / "dir" / "w.duckdb"
    with pytest.raises(duckdb.Error):
        db.connect_target(str(missing), read_only=True)
    assert "cannot open" in caplog.text


def test_197_ac1_the_image_installs_the_motherduck_extension_at_build_time() -> None:
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    install = text.index("INSTALL motherduck")
    user = text.index("USER revint")
    assert user < install  # installed for the revint user, in its home, before the app starts
    assert "/app/.venv/bin/python" in text[install - 200 : install]
