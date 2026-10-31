"""Helpers shared by the gold tests: a silver warehouse copy with the gold stage run on it.

Synthetic data only. Not a test module (pytest does not collect it).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import yaml

from revint.config import DEFAULT_SETTINGS_FILE, Settings, load_settings
from revint.gold import run_gold


def variant(root: Path, source: Settings, **sections: dict[str, Any]) -> Settings:
    """The committed settings with some keys changed, pointing at `source`'s warehouse."""
    data = yaml.safe_load(DEFAULT_SETTINGS_FILE.read_text(encoding="utf-8"))
    for name, keys in sections.items():
        data[name] = {**data.get(name, {}), **keys}
    config_file = root / "config" / "settings.yaml"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return load_settings(config_file, env={"REVINT_PATHS_WAREHOUSE": str(source.paths.warehouse)})


def gold(built: Settings, tmp_path: Path, **sections: dict[str, Any]) -> Settings:
    """A private copy of the silver warehouse with the gold stage run under `sections`."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    shutil.copy(built.paths.warehouse, tmp_path / "warehouse.duckdb")
    source = load_settings(env={"REVINT_PATHS_WAREHOUSE": str(tmp_path / "warehouse.duckdb")})
    settings = variant(tmp_path, source, **sections)
    run_gold(settings)
    return settings
