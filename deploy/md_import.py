"""Import an exported warehouse with the DuckDB version MotherDuck supports (story #195).

Runs in its own environment, started by deploy/upload_warehouse.py:

    uv run --no-project --with duckdb==<MOTHERDUCK_DUCKDB> python deploy/md_import.py \
        <export> <target>

`<export>` is a folder written by DuckDB 2.0's EXPORT DATABASE (Parquet). `<target>` is a
local file (for the compatibility check) or `md:<name>` (the real upload, which replaces that
MotherDuck database and creates the app database `md:<app>` when it is missing). It prints
only table and row counts, never rows. The MotherDuck token comes from MOTHERDUCK_TOKEN.
"""

from __future__ import annotations

import os
import re
import sys

import duckdb

MOTHERDUCK_DUCKDB = "1.5.6"  # the newest DuckDB MotherDuck supports (checked 2026-11-21)
_NAME = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


def _motherduck(token: str) -> duckdb.DuckDBPyConnection:
    return duckdb.connect("md:", config={"motherduck_token": token})


def import_export(export: str, target: str, app_db: str | None = None) -> tuple[int, int]:
    """Load `export` into `target`; returns (tables and views, opportunities)."""
    if duckdb.__version__ != MOTHERDUCK_DUCKDB:
        raise SystemExit(f"run with duckdb {MOTHERDUCK_DUCKDB}, not {duckdb.__version__}")
    export = export.replace("\\", "/")
    if target.startswith("md:"):
        token = os.environ.get("MOTHERDUCK_TOKEN", "").strip()
        if not token:
            raise SystemExit("set MOTHERDUCK_TOKEN (in .env) to upload to MotherDuck")
        name = target.removeprefix("md:")
        if not _NAME.match(name) or (app_db and not _NAME.match(app_db.removeprefix("md:"))):
            raise SystemExit("MotherDuck database names are lower case letters, digits and _")
        con = _motherduck(token)
        con.execute(f"create or replace database {name}")
        con.execute(f"use {name}")
        if app_db:
            con.execute(f"create database if not exists {app_db.removeprefix('md:')}")
    else:
        if os.path.exists(target):
            os.remove(target)
        con = duckdb.connect(target)
    try:
        con.execute(f"import database '{export}'")
        tables = con.execute(
            "select count(*) from information_schema.tables "
            "where table_catalog = current_database()"
        ).fetchone()[0]
        opportunities = con.execute("select count(*) from opp_opportunities").fetchone()[0]
    finally:
        con.close()
    return tables, opportunities


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4):
        raise SystemExit("usage: md_import.py <export folder> <target> [<app database>]")
    tables, opportunities = import_export(*sys.argv[1:])
    print(f"imported into {sys.argv[2]}: {tables} tables and views, {opportunities} opportunities")
