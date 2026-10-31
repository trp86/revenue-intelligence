"""Story #72: the gold-layer config sections (spec 02 section 8).

Covers `marts`, `calendar`, `regions`, `peer_groups` and `product`, and the new
`net_sales.exclude_flags` key. Each section also has its own module (`test_settings_<section>.py`)
that the section-per-test rule in `test_settings.py` requires; those modules only point here.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
import yaml

from revint.config import (
    SILVER_FLAG_COLUMNS,
    ConfigError,
    Settings,
    config_hash,
    load_settings,
)
from revint.pipeline import settings_parameters
from revint.silver import AMOUNT_COLUMNS, COLUMN_TYPES

ROOT = Path(__file__).resolve().parents[2]
Loader = Callable[..., Settings]

SMALL = ["Code", "Name", "Brand", "Cat", "Chan", "Branch", "Reg", "Amount", "Qty"]


def small(**sections: dict) -> dict:
    """A small expected_columns list, with the earlier sections pointed at it."""
    first = SMALL[0]
    return {
        "ingest": {"expected_columns": SMALL},
        "net_sales": {"field": "Amount", "candidate_columns": ["Amount"], "quantity_field": "Qty"},
        "customers": {"code_column": first, "name_column": "Name", "branch_column": "Branch"},
        "labels": {"channel_columns": ["Chan"], "branch_columns": ["Branch"]},
        "recon": {"product_column": first, "date_column": first},
        "product": {
            "code_column": "Code",
            "name_column": "Name",
            "brand_column": "Brand",
            "category_column": "Cat",
        },
        "peer_groups": {"columns": ["Chan", "Branch"], "fallback_columns": ["Chan"]},
        "regions": {"source_column": "Reg"},
        **sections,
    }


# AC1: the committed config and the defaults ---------------------------------------------------


def test_ac1_committed_config_has_the_spec_defaults() -> None:
    s = load_settings(env={})
    assert s.net_sales.exclude_flags == []
    assert s.marts.zero_fill is True
    assert s.calendar.fiscal_year_start_month == 1
    assert s.calendar.date_column == "Date"
    assert s.regions.branch_to_region == {}
    assert s.regions.source_column == "Region"
    assert s.peer_groups.columns == ["Channel_Category", "Branch_Name"]
    assert s.peer_groups.fallback_columns == ["Channel_Category"]
    assert s.peer_groups.min_size >= 1


def test_ac1_committed_config_names_the_product_columns() -> None:
    p = load_settings(env={}).product
    assert p.code_column == "SCJ_CODE_1"
    assert p.name_column == "Product_Decription"
    assert (p.brand_column, p.category_column) == ("Actual_Brands_1", "Internal_Category")


def test_ac1_defaults_apply_when_the_sections_are_absent(load_with: Loader) -> None:
    s = load_with()
    committed = load_settings(env={})
    assert s.marts == committed.marts
    assert s.calendar == committed.calendar
    assert s.regions == committed.regions
    assert s.peer_groups == committed.peer_groups
    assert s.product == committed.product
    assert s.net_sales.exclude_flags == []


def test_ac1_the_committed_file_lists_every_new_key() -> None:
    data = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text(encoding="utf-8"))
    assert set(data["marts"]) == {"zero_fill"}
    assert set(data["calendar"]) == {"fiscal_year_start_month", "date_column"}
    assert set(data["regions"]) == {"source_column", "branch_to_region"}
    assert set(data["peer_groups"]) == {"columns", "min_size", "fallback_columns"}
    assert set(data["product"]) == {"code_column", "name_column", "brand_column", "category_column"}
    assert "exclude_flags" in data["net_sales"]


def test_ac1_the_default_product_columns_are_real_source_columns() -> None:
    s = load_settings(env={})
    known = set(s.ingest.expected_columns)
    for column in (
        s.product.code_column,
        s.product.name_column,
        s.product.brand_column,
        s.product.category_column,
    ):
        assert column in known


# AC2: invalid values fail and name the key ----------------------------------------------------


@pytest.mark.parametrize("value", [0, 13, -1, 1.5, "June"])
def test_ac2_fiscal_start_month_outside_1_to_12_fails(load_with: Loader, value: object) -> None:
    with pytest.raises(ConfigError, match=r"calendar\.fiscal_year_start_month"):
        load_with({"calendar": {"fiscal_year_start_month": value}})


@pytest.mark.parametrize("value", [1, 4, 12])
def test_ac2_fiscal_start_month_inside_the_range_loads(load_with: Loader, value: int) -> None:
    calendar = load_with({"calendar": {"fiscal_year_start_month": value}}).calendar
    assert calendar.fiscal_year_start_month == value


@pytest.mark.parametrize("value", ["yes", 1, 0, None, "true"])
def test_ac2_zero_fill_must_be_a_real_boolean(load_with: Loader, value: object) -> None:
    with pytest.raises(ConfigError, match=r"marts\.zero_fill"):
        load_with({"marts": {"zero_fill": value}})


@pytest.mark.parametrize("value", [-1, 0, 1.5, "ten"])
def test_ac2_invalid_peer_min_size_fails(load_with: Loader, value: object) -> None:
    with pytest.raises(ConfigError, match=r"peer_groups\.min_size"):
        load_with({"peer_groups": {"min_size": value}})


def test_ac2_min_size_of_one_is_the_smallest_allowed(load_with: Loader) -> None:
    assert load_with({"peer_groups": {"min_size": 1}}).peer_groups.min_size == 1


def test_ac2_unknown_keys_fail_and_name_them(load_with: Loader) -> None:
    for section in ("marts", "calendar", "regions", "peer_groups", "product"):
        with pytest.raises(ConfigError, match=rf"{section}\.nope"):
            load_with({section: {"nope": 1}})


def test_ac2_unknown_exclude_flag_fails_and_names_the_key_and_the_flag(load_with: Loader) -> None:
    with pytest.raises(ConfigError, match=r"net_sales\.exclude_flags.*f_not_a_flag"):
        load_with({"net_sales": {"exclude_flags": ["f_not_a_flag"]}})


def test_ac2_a_source_column_is_not_a_flag(load_with: Loader) -> None:
    with pytest.raises(ConfigError, match=r"net_sales\.exclude_flags.*Net_Amount_2"):
        load_with({"net_sales": {"exclude_flags": ["Net_Amount_2"]}})


def test_ac2_repeated_exclude_flags_fail(load_with: Loader) -> None:
    with pytest.raises(ConfigError, match=r"net_sales\.exclude_flags"):
        load_with({"net_sales": {"exclude_flags": ["f_blank_void", "f_blank_void"]}})


@pytest.mark.parametrize(
    "flag",
    [
        "f_stray_row",
        "f_zero_value_with_qty",
        "f_negative_qty",
        "f_negative_value",
        "f_blank_void",
        "f_unmapped_void",
        "f_unmapped_label",
        "is_duplicate",
        "is_excluded",
        "f_bad_Net_Amount_2",
    ],
)
def test_ac2_real_silver_flags_are_accepted(load_with: Loader, flag: str) -> None:
    assert load_with({"net_sales": {"exclude_flags": [flag]}}).net_sales.exclude_flags == [flag]


def test_ac2_an_f_bad_flag_for_an_untyped_column_fails(load_with: Loader) -> None:
    with pytest.raises(ConfigError, match=r"net_sales\.exclude_flags.*f_bad_Customer"):
        load_with({"net_sales": {"exclude_flags": ["f_bad_Customer"]}})


def test_ac2_the_flag_list_is_the_silver_flag_set() -> None:
    assert "f_stray_row" in SILVER_FLAG_COLUMNS
    assert "is_duplicate" in SILVER_FLAG_COLUMNS
    bad = {c for c in SILVER_FLAG_COLUMNS if c.startswith("f_bad_")}
    assert bad == {f"f_bad_{column}" for column in COLUMN_TYPES}


def test_ac2_the_flag_list_matches_the_silver_table(tmp_path: Path) -> None:
    """The names the config accepts are the flag columns silver really builds."""
    from silver_helpers import bronze_row, build, silver_columns

    settings = load_settings(
        env={
            "REVINT_PATHS_WAREHOUSE": str(tmp_path / "w.duckdb"),
            "REVINT_PATHS_BRONZE": str(tmp_path / "b"),
        }
    )
    build(settings, [bronze_row(8, OrderReference="O1")])
    real = {
        c
        for c in silver_columns(settings)
        if c.startswith("f_") or c in {"is_duplicate", "is_excluded"}
    }
    assert real == set(SILVER_FLAG_COLUMNS)


def test_ac2_regions_map_rejects_blank_keys_values_and_trim_collisions(load_with: Loader) -> None:
    for bad in ({" ": "North"}, {"Yangon": " "}, {"Yangon": "N", " Yangon ": "S"}):
        with pytest.raises(ConfigError, match=r"regions\.branch_to_region"):
            load_with({"regions": {"branch_to_region": bad}})


def test_ac2_regions_map_loads_and_is_exposed_as_two_lists(load_with: Loader) -> None:
    s = load_with({"regions": {"branch_to_region": {"Yangon": "South", "Pyay": "Central"}}})
    params = settings_parameters(s)
    pairs = dict(
        zip(
            params["regions_branch_to_region_keys"],
            params["regions_branch_to_region_values"],
            strict=True,
        )
    )
    assert pairs == {"Yangon": "South", "Pyay": "Central"}


def test_ac2_peer_columns_must_be_non_empty_and_unique(load_with: Loader) -> None:
    for bad in ([], ["Channel_Category", "Channel_Category"]):
        with pytest.raises(ConfigError, match=r"peer_groups\.columns"):
            load_with({"peer_groups": {"columns": bad}})


def test_ac2_fallback_columns_must_be_part_of_the_peer_columns(load_with: Loader) -> None:
    with pytest.raises(ConfigError, match=r"peer_groups\.fallback_columns.*Region"):
        load_with({"peer_groups": {"fallback_columns": ["Region"]}})


def test_ac2_fallback_columns_may_be_empty_meaning_no_fallback(load_with: Loader) -> None:
    assert load_with({"peer_groups": {"fallback_columns": []}}).peer_groups.fallback_columns == []


@pytest.mark.parametrize("key", ["code_column", "name_column", "brand_column", "category_column"])
def test_ac2_blank_product_column_fails_and_names_the_key(load_with: Loader, key: str) -> None:
    with pytest.raises(ConfigError, match=rf"product\.{key}"):
        load_with({"product": {key: ""}})


# AC3: a changed key changes the config hash ----------------------------------------------------

CHANGES = [
    {"net_sales": {"exclude_flags": ["f_blank_void"]}},
    {"marts": {"zero_fill": False}},
    {"calendar": {"fiscal_year_start_month": 4}},
    {"calendar": {"date_column": "SCJ_FISCAL_MONTH"}},
    {"regions": {"branch_to_region": {"Yangon": "South"}}},
    {"regions": {"source_column": "DC"}},
    {"peer_groups": {"min_size": 25}},
    {"peer_groups": {"columns": ["Branch_Name"], "fallback_columns": []}},
    {"product": {"brand_column": "Actual_Brands_2"}},
]


@pytest.mark.parametrize("change", CHANGES, ids=lambda c: next(iter(c)) + str(c))
def test_ac3_a_changed_key_changes_the_config_hash(load_with: Loader, change: dict) -> None:
    assert config_hash(load_with(name="a")) != config_hash(load_with(change, name="b"))


def test_ac3_the_same_settings_give_the_same_hash(load_with: Loader) -> None:
    assert config_hash(load_with(name="a")) == config_hash(load_with(name="b"))


# AC4: column names are checked against ingest.expected_columns ----------------------------------


def test_ac4_a_small_consistent_config_loads(load_with: Loader) -> None:
    s = load_with(small())
    assert s.product.brand_column == "Brand"
    assert s.regions.source_column == "Reg"


@pytest.mark.parametrize("key", ["code_column", "name_column", "brand_column", "category_column"])
def test_ac4_a_product_column_not_in_the_sheet_fails(load_with: Loader, key: str) -> None:
    extra = small(
        product={
            "code_column": "Code",
            "name_column": "Name",
            "brand_column": "Brand",
            "category_column": "Cat",
            key: "Nope",
        }
    )
    with pytest.raises(ConfigError, match=rf"product\.{key} 'Nope'"):
        load_with(extra)


def test_ac4_a_peer_column_not_in_the_sheet_fails(load_with: Loader) -> None:
    with pytest.raises(ConfigError, match=r"peer_groups\.columns.*Nope"):
        load_with(small(peer_groups={"columns": ["Chan", "Nope"], "fallback_columns": ["Chan"]}))


def test_ac4_a_calendar_date_column_not_in_the_sheet_fails(load_with: Loader) -> None:
    with pytest.raises(ConfigError, match=r"calendar\.date_column 'Nope'"):
        load_with(small(calendar={"date_column": "Nope"}))


def test_ac4_a_region_source_column_not_in_the_sheet_fails(load_with: Loader) -> None:
    with pytest.raises(ConfigError, match=r"regions\.source_column 'Nope'"):
        load_with(small(regions={"source_column": "Nope"}))


def test_ac4_the_check_is_skipped_while_expected_columns_is_empty(load_with: Loader) -> None:
    assert load_with({"product": {"brand_column": "Anything"}}).product.brand_column == "Anything"


# AC5: every section has a test module and is a SQL parameter -------------------------------------


@pytest.mark.parametrize("section", ["marts", "calendar", "regions", "peer_groups", "product"])
def test_ac5_each_new_section_has_its_own_test_module(section: str) -> None:
    assert (ROOT / "tests" / "unit" / f"test_settings_{section}.py").is_file()
    assert section in Settings.model_fields


def test_ac5_the_sections_are_sql_parameters_with_no_runner_change() -> None:
    params = settings_parameters(load_settings(env={}))
    assert params["marts_zero_fill"] is True
    assert params["calendar_fiscal_year_start_month"] == 1
    assert params["peer_groups_columns"] == ["Channel_Category", "Branch_Name"]
    assert params["peer_groups_fallback_columns"] == ["Channel_Category"]
    assert params["peer_groups_min_size"] >= 1
    assert params["product_brand_column"] == "Actual_Brands_1"
    assert params["net_sales_exclude_flags"] == []
    assert params["regions_source_column"] == "Region"
    assert params["regions_branch_to_region_keys"] == []


def test_ac5_the_amount_columns_are_unchanged() -> None:
    assert set(load_settings(env={}).net_sales.candidate_columns) == set(AMOUNT_COLUMNS)
