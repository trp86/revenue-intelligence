"""Shared fixtures for the settings tests."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from revint.config import Settings, load_settings

BASE: dict[str, Any] = {
    "paths": {
        "raw": "data/raw",
        "bronze": "data/bronze",
        "warehouse": "data/warehouse.duckdb",
        "app_db": "data/app.duckdb",
    },
    "asof": {"date": "2020-02-29"},
}


@pytest.fixture
def load_with(tmp_path: Path) -> Callable[..., Settings]:
    """Load settings from a temporary file made of the required sections plus `extra`.

    `extra` maps a section name to its keys. Pass `name` to load two different
    files in one test.
    """

    def _load(extra: dict[str, Any] | None = None, name: str = "cfg") -> Settings:
        path = tmp_path / name / "config" / "settings.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump({**BASE, **(extra or {})}), encoding="utf-8")
        return load_settings(path, env={})

    return _load
