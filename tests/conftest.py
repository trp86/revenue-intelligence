"""Shared pytest setup: skip `realdata` tests when the data/ folder is absent."""

from __future__ import annotations

from pathlib import Path

import pytest

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if DATA_DIR.is_dir():
        return
    skip = pytest.mark.skip(reason="data/ not present; realdata tests need the client data")
    for item in items:
        if "realdata" in item.keywords:
            item.add_marker(skip)
