"""Shared fixtures for the unit tests."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import xlsxwriter
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


@pytest.fixture
def build_workbook() -> Callable[..., Path]:
    """Write a small .xlsx with cells at exact Excel rows. Synthetic data only.

    `rows` maps an Excel row number (1-based) to the values written from column A
    (None leaves a cell empty). `styled_blank` lists rows that get a formatted empty
    cell in column A, as the real sheet has. `sheets` adds further sheets by name.
    """

    def _build(
        path: Path,
        rows: dict[int, list[Any]],
        sheet: str = "RAW SCJ SALES",
        styled_blank: tuple[int, ...] = (),
        extra_sheets: tuple[str, ...] = (),
    ) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        book = xlsxwriter.Workbook(str(path))
        sheets = [book.add_worksheet(sheet), *[book.add_worksheet(n) for n in extra_sheets]]
        fmt = book.add_format({"bold": True})
        main = sheets[0]
        for row in styled_blank:
            main.write_blank(row - 1, 0, None, fmt)
        for row, values in rows.items():
            for col, value in enumerate(values):
                if value is not None:
                    main.write(row - 1, col, value)
        book.close()
        return path

    return _build
