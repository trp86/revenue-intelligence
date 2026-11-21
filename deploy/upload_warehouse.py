"""Upload the warehouse to MotherDuck, after checking it works there (story #195).

    uv run python deploy/upload_warehouse.py           # check, then upload
    uv run python deploy/upload_warehouse.py --check   # check only, nothing uploaded

The project uses DuckDB 2.0; MotherDuck supports DuckDB up to 1.5.6, which cannot open a 2.0
file. So the warehouse is:
1. exported with 2.0 to Parquet (a temporary folder, deleted at the end);
2. imported into a local 1.5.6 file, and the API is checked against it on 1.5.6
   (deploy/check_api.py, every endpoint the screens use);
3. only if that passes, imported into MotherDuck (`database.warehouse`, replacing it), and the
   app database (`database.app_db`) is created when missing.
The MotherDuck token is read from MOTHERDUCK_TOKEN or .env and never printed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from md_import import MOTHERDUCK_DUCKDB  # noqa: E402

from revint.config import load_settings  # noqa: E402


def _token() -> str | None:
    value = os.environ.get("MOTHERDUCK_TOKEN", "").strip()
    env_file = ROOT / ".env"
    if not value and env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            name, _, rest = line.partition("=")
            if name.strip() == "MOTHERDUCK_TOKEN":
                value = rest.strip().strip("'\"")
    return value or None


def _with_duckdb15(args: list[str], project: bool, env: dict[str, str] | None = None) -> int:
    command = ["uv", "run"] + ([] if project else ["--no-project"])
    command += ["--with", f"duckdb=={MOTHERDUCK_DUCKDB}", "python", *args]
    return subprocess.run(command, cwd=ROOT, env=env, check=False).returncode


def main(check_only: bool) -> int:
    settings = load_settings()
    hosted = load_settings(
        env={**os.environ, "REVINT_SETTINGS_OVERLAY": "config/settings.production.yaml"}
    )
    target, app_db = hosted.database.warehouse, hosted.database.app_db
    warehouse = settings.paths.warehouse
    if not warehouse.is_file():
        print(f"no warehouse at {warehouse}: build it first (uv run revint build all)")
        return 2
    work = Path(tempfile.mkdtemp(prefix="revint-upload-"))
    try:
        export = work / "export"
        print(f"1/3 exporting the warehouse with duckdb {duckdb.__version__}")
        con = duckdb.connect(str(warehouse), read_only=True)
        try:
            con.execute(f"export database '{export.as_posix()}' (format parquet)")
        finally:
            con.close()

        print(f"2/3 checking it on duckdb {MOTHERDUCK_DUCKDB} (the version MotherDuck runs)")
        local = work / "check.duckdb"
        importer = str(ROOT / "deploy" / "md_import.py")
        if _with_duckdb15([importer, str(export), str(local)], project=False) != 0:
            print("the import into duckdb 1.5.6 failed: nothing was uploaded")
            return 1
        checker = str(ROOT / "deploy" / "check_api.py")
        if _with_duckdb15([checker, str(local), str(work / "app.duckdb")], project=True) != 0:
            print("the API check on duckdb 1.5.6 failed: nothing was uploaded")
            return 1
        if check_only:
            print("check passed; nothing uploaded (--check)")
            return 0

        print(f"3/3 uploading to MotherDuck as {target} (replacing it)")
        token = _token()
        if not token:
            print("no MOTHERDUCK_TOKEN in the environment or .env: nothing was uploaded")
            return 2
        env = {**os.environ, "MOTHERDUCK_TOKEN": token}
        if _with_duckdb15([importer, str(export), target, app_db], project=False, env=env) != 0:
            print("the upload to MotherDuck failed")
            return 1
        print("done")
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(check_only="--check" in sys.argv[1:]))
