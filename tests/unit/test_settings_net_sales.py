"""Story #28: the `net_sales` section of config/settings.yaml (AC1, AC2, AC4)."""

from __future__ import annotations

import pytest

from revint.config import ConfigError, config_hash, load_settings


def test_ac1_committed_config_uses_the_provisional_net_amount_field() -> None:
    assert load_settings(env={}).net_sales.field == "Net AMOUNT"


def test_ac1_defaults_apply_when_the_section_is_absent(load_with) -> None:
    assert load_with().net_sales.field == "Net AMOUNT"


def test_ac1_field_can_be_changed_in_the_file(load_with) -> None:
    assert load_with({"net_sales": {"field": "Gross AMOUNT"}}).net_sales.field == "Gross AMOUNT"


def test_ac2_unknown_key_fails_and_names_it(load_with) -> None:
    with pytest.raises(ConfigError, match=r"net_sales\.fields"):
        load_with({"net_sales": {"fields": "Net AMOUNT"}})


@pytest.mark.parametrize("value", ["", None])
def test_ac2_empty_field_fails_and_names_the_key(load_with, value) -> None:
    with pytest.raises(ConfigError, match=r"net_sales\.field"):
        load_with({"net_sales": {"field": value}})


def test_ac4_changing_the_field_changes_the_config_hash(load_with) -> None:
    a = load_with({"net_sales": {"field": "Net AMOUNT"}}, name="a")
    b = load_with({"net_sales": {"field": "Gross AMOUNT"}}, name="b")
    assert config_hash(a) != config_hash(b)
