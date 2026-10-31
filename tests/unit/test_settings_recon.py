"""Story #28: the `recon` section of config/settings.yaml (AC1, AC2, AC4)."""

from __future__ import annotations

import pytest

from revint.config import ConfigError, config_hash, load_settings


def test_ac1_committed_config_has_the_spec_01_default() -> None:
    assert load_settings(env={}).recon.tolerance_amount == 0.01


def test_ac1_defaults_apply_when_the_section_is_absent(load_with) -> None:
    assert load_with().recon.tolerance_amount == 0.01


def test_ac2_unknown_key_fails_and_names_it(load_with) -> None:
    with pytest.raises(ConfigError, match=r"recon\.tolerance"):
        load_with({"recon": {"tolerance": 0.5}})


@pytest.mark.parametrize("value", [-0.01, "small"])
def test_ac2_invalid_tolerance_fails_and_names_the_key(load_with, value) -> None:
    with pytest.raises(ConfigError, match=r"recon\.tolerance_amount"):
        load_with({"recon": {"tolerance_amount": value}})


def test_ac2_zero_tolerance_is_allowed(load_with) -> None:
    assert load_with({"recon": {"tolerance_amount": 0}}).recon.tolerance_amount == 0


def test_ac4_changing_the_tolerance_changes_the_config_hash(load_with) -> None:
    a = load_with({"recon": {"tolerance_amount": 0.01}}, name="a")
    b = load_with({"recon": {"tolerance_amount": 0.05}}, name="b")
    assert config_hash(a) != config_hash(b)


# Story #43: the columns R4 reads ---------------------------------------------------------------


def test_story43_committed_config_names_the_r4_columns() -> None:
    recon = load_settings(env={}).recon
    assert (recon.product_column, recon.date_column) == ("SCJ_CODE_1", "Date")


def test_story43_r4_columns_default_when_absent(load_with) -> None:
    recon = load_with().recon
    assert (recon.product_column, recon.date_column) == ("SCJ_CODE_1", "Date")


@pytest.mark.parametrize("key", ["product_column", "date_column"])
def test_story43_blank_r4_column_fails_and_names_the_key(load_with, key) -> None:
    with pytest.raises(ConfigError, match=rf"recon\.{key}"):
        load_with({"recon": {key: ""}})


@pytest.mark.parametrize("key", ["product_column", "date_column"])
def test_story43_r4_column_not_in_the_sheet_fails_and_names_the_key(load_with, key) -> None:
    with pytest.raises(ConfigError, match=rf"recon\.{key} 'Nope'"):
        load_with({"ingest": {"expected_columns": ["A", "B"]}, "recon": {key: "Nope"}})


def test_story43_changing_an_r4_column_changes_the_config_hash(load_with) -> None:
    a = load_with(name="a")
    b = load_with({"recon": {"product_column": "SAP_CODE"}}, name="b")
    assert config_hash(a) != config_hash(b)
