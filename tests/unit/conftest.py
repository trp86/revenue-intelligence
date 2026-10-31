"""Shared fixtures for the unit tests."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
import xlsxwriter
import yaml

from revint.config import (
    CalendarSettings,
    CustomersSettings,
    LabelsSettings,
    NetSalesSettings,
    PeerGroupsSettings,
    ProductSettings,
    ReconSettings,
    RegionsSettings,
    Settings,
    load_settings,
)

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

    A test that gives its own `ingest.expected_columns` list but no `net_sales`,
    `customers` or `labels` section gets sections that fit the list (the settings check those column
    names against it): the real defaults when the list contains them, otherwise the list's
    first column. To test the real defaults against a list that lacks them, pass the section
    explicitly, even as `{}`.
    """

    def _load(extra: dict[str, Any] | None = None, name: str = "cfg") -> Settings:
        sections = {**BASE, **(extra or {})}
        columns = sections.get("ingest", {}).get("expected_columns") or []
        if columns:
            first = columns[0]
            net = NetSalesSettings()
            net_wanted = {net.field, net.quantity_field, *net.candidate_columns}
            cust = CustomersSettings()
            cust_wanted = {cust.code_column, cust.name_column, cust.branch_column}
            lab = LabelsSettings()
            lab_wanted = {*lab.channel_columns, *lab.branch_columns}
            rec = ReconSettings()
            rec_wanted = {rec.product_column, rec.date_column}
            if "recon" not in sections:
                sections["recon"] = (
                    {}
                    if rec_wanted <= set(columns)
                    else {"product_column": first, "date_column": first}
                )
            prod = ProductSettings()
            prod_wanted = {
                prod.code_column,
                prod.name_column,
                prod.brand_column,
                prod.category_column,
            }
            if "product" not in sections:
                sections["product"] = (
                    {}
                    if prod_wanted <= set(columns)
                    else dict.fromkeys(
                        ("code_column", "name_column", "brand_column", "category_column"), first
                    )
                )
            if "calendar" not in sections:
                sections["calendar"] = (
                    {} if CalendarSettings().date_column in columns else {"date_column": first}
                )
            if "regions" not in sections:
                sections["regions"] = (
                    {} if RegionsSettings().source_column in columns else {"source_column": first}
                )
            if "peer_groups" not in sections:
                sections["peer_groups"] = (
                    {}
                    if set(PeerGroupsSettings().columns) <= set(columns)
                    else {"columns": [first], "fallback_columns": []}
                )
            if "net_sales" not in sections:
                sections["net_sales"] = (
                    {}
                    if net_wanted <= set(columns)
                    else {"field": first, "candidate_columns": [first], "quantity_field": first}
                )
            if "customers" not in sections:
                sections["customers"] = (
                    {}
                    if cust_wanted <= set(columns)
                    else {"code_column": first, "name_column": first, "branch_column": first}
                )
            if "labels" not in sections:
                sections["labels"] = (
                    {}
                    if lab_wanted <= set(columns)
                    else {"channel_columns": [first], "branch_columns": [first]}
                )
        path = tmp_path / name / "config" / "settings.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(sections), encoding="utf-8")
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
        date_fmt = book.add_format({"num_format": 14})  # the date format the real sheet uses
        main = sheets[0]
        for row in styled_blank:
            main.write_blank(row - 1, 0, None, fmt)
        for row, values in rows.items():
            for col, value in enumerate(values):
                if isinstance(value, datetime):
                    main.write_datetime(row - 1, col, value, date_fmt)
                elif value is not None:
                    main.write(row - 1, col, value)
        book.close()
        return path

    return _build
