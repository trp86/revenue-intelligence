"""Story #195: the `database` section (MotherDuck addresses for the hosted API)."""

from __future__ import annotations

import pytest

from revint.config import ConfigError, load_settings


def test_database_defaults_to_the_local_files() -> None:
    database = load_settings(env={}).database
    assert (database.warehouse, database.app_db) == (None, None)


def test_database_takes_motherduck_names(load_with) -> None:
    database = load_with(
        {"database": {"warehouse": "md:revint", "app_db": "md:revint_app"}}
    ).database
    assert (database.warehouse, database.app_db) == ("md:revint", "md:revint_app")


@pytest.mark.parametrize("bad", ["data/warehouse.duckdb", "md:Revint", "md:a b", "md:x?token=y"])
def test_database_refuses_anything_but_a_plain_motherduck_name(load_with, bad: str) -> None:
    with pytest.raises(ConfigError, match="database"):
        load_with({"database": {"app_db": bad}})
