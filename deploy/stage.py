"""Build the upload folder for Railway (story #193): an allow-list of what the API needs.

    uv run python deploy/stage.py            # writes deploy/.stage (git-ignored)
    railway up deploy/.stage --path-as-root  # uploads only that folder

Only the files named below are copied: the code, the config, the lock file and the built
warehouse. `.env`, the users file, app.duckdb, the raw and bronze data, the frontend and the
tests are never copied, whatever any ignore file says.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "deploy" / ".stage"
DEFAULT_WAREHOUSE = ROOT / "data" / "warehouse.duckdb"

FILES = ["Dockerfile", "pyproject.toml", "uv.lock", "README.md", "deploy/entrypoint.sh"]
CONFIG = ["config/settings.yaml", "config/settings.production.yaml", "config/definitions.yaml"]
SKIP = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache")


def stage(out: Path = DEFAULT_OUT, warehouse: Path = DEFAULT_WAREHOUSE) -> Path:
    """A fresh `out` folder with exactly the files the API image needs."""
    if not warehouse.is_file():
        raise SystemExit(f"no warehouse at {warehouse}: run `uv run revint build all` first")
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for name in FILES + CONFIG:
        target = out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)
    shutil.copytree(ROOT / "src", out / "src", ignore=SKIP)
    (out / "data").mkdir()
    shutil.copy2(warehouse, out / "data" / "warehouse.duckdb")
    return out


if __name__ == "__main__":
    folder = stage()
    size = sum(p.stat().st_size for p in folder.rglob("*") if p.is_file()) / 1e6
    print(f"staged {folder} ({size:.0f} MB). Next: railway up {folder} --path-as-root")
    sys.exit(0)
