"""Story #28: the `duplicates` section of config/settings.yaml (AC1 to AC4)."""

from __future__ import annotations

import pytest

from revint.config import ConfigError, config_hash, load_settings


def test_ac1_committed_config_excludes_duplicates_from_net_sales() -> None:
    assert load_settings(env={}).duplicates.exclude_from_net_sales is True


def test_ac1_defaults_apply_when_the_section_is_absent(load_with) -> None:
    assert load_with().duplicates.exclude_from_net_sales is True


def test_ac2_unknown_key_fails_and_names_it(load_with) -> None:
    with pytest.raises(ConfigError, match=r"duplicates\.exclude_net_sales"):
        load_with({"duplicates": {"exclude_net_sales": True}})


@pytest.mark.parametrize("value", ["false", "yes", 1, "maybe"])
def test_ac2_non_boolean_exclude_flag_fails_and_names_the_key(load_with, value) -> None:
    with pytest.raises(ConfigError, match=r"duplicates\.exclude_from_net_sales"):
        load_with({"duplicates": {"exclude_from_net_sales": value}})


def test_ac3_unset_key_columns_derive_from_expected_columns_minus_source_row(load_with) -> None:
    settings = load_with({"ingest": {"expected_columns": ["A", "_source_row", "B", "B_1"]}})
    assert settings.duplicates.key_columns is None
    assert settings.duplicate_key_columns == ["A", "B", "B_1"]


def test_ac3_derivation_keeps_source_order_and_works_without_source_row(load_with) -> None:
    settings = load_with({"ingest": {"expected_columns": ["Z", "A", "M"]}})
    assert settings.duplicate_key_columns == ["Z", "A", "M"]


def test_ac3_unset_key_columns_with_no_expected_columns_is_empty(load_with) -> None:
    assert load_with().duplicate_key_columns == []


def test_ac3_explicit_key_columns_are_used_as_given(load_with) -> None:
    settings = load_with(
        {
            "ingest": {"expected_columns": ["A", "B"]},
            "duplicates": {"key_columns": ["B"]},
        }
    )
    assert settings.duplicate_key_columns == ["B"]


def test_ac3_derived_key_columns_follow_a_change_in_expected_columns(load_with) -> None:
    a = load_with({"ingest": {"expected_columns": ["A", "B"]}}, name="a")
    b = load_with({"ingest": {"expected_columns": ["A", "B", "C"]}}, name="b")
    assert a.duplicate_key_columns == ["A", "B"]
    assert b.duplicate_key_columns == ["A", "B", "C"]


def test_ac4_flipping_exclude_from_net_sales_changes_the_config_hash(load_with) -> None:
    on = load_with({"duplicates": {"exclude_from_net_sales": True}}, name="on")
    off = load_with({"duplicates": {"exclude_from_net_sales": False}}, name="off")
    assert off.duplicates.exclude_from_net_sales is False
    assert config_hash(on) != config_hash(off)
