"""Where the API's databases live (story #195): local files, or MotherDuck when hosted.

Locally the warehouse and the app database are the files in `paths`. A hosted run sets
`database.warehouse` and `database.app_db` to MotherDuck addresses (`md:<name>`, in
config/settings.production.yaml). The MotherDuck token comes only from the environment
(`MOTHERDUCK_TOKEN`) and is passed as connection config, never in the address, so it never
appears in a log or an error message. Only the API's connections go through here; the build
pipeline always works on local files.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

import duckdb

from revint.config import Settings

TOKEN_ENV = "MOTHERDUCK_TOKEN"


class DatabaseError(duckdb.Error):
    """A database cannot be opened (for example a MotherDuck address without a token)."""


def warehouse_target(settings: Settings) -> str:
    return settings.database.warehouse or str(settings.paths.warehouse)


def app_db_target(settings: Settings) -> str:
    return settings.database.app_db or str(settings.paths.app_db)


def is_remote(target: str) -> bool:
    return target.startswith("md:")


def connect_target(target: str, read_only: bool) -> duckdb.DuckDBPyConnection:
    """A connection to a file or a MotherDuck database."""
    if not is_remote(target):
        return duckdb.connect(target, read_only=read_only)
    token = os.environ.get(TOKEN_ENV, "").strip()
    if not token:
        raise DatabaseError(f"{target} needs the {TOKEN_ENV} environment variable")
    # MotherDuck has no read-only open; the API only reads the warehouse
    return duckdb.connect(target, config={"motherduck_token": token})


def open_warehouse(settings: Settings) -> duckdb.DuckDBPyConnection:
    """The warehouse, read-only when it is a file."""
    return connect_target(warehouse_target(settings), read_only=True)


def open_app_db(settings: Settings, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    return connect_target(app_db_target(settings), read_only=read_only)


@contextmanager
def warehouse(settings: Settings) -> Iterator[duckdb.DuckDBPyConnection]:
    con = open_warehouse(settings)
    try:
        yield con
    finally:
        con.close()
