"""Story #160: the `display` section of config/settings.yaml (the currency label)."""

from __future__ import annotations

import pytest

from revint.config import ConfigError, load_settings
from revint.pipeline import settings_parameters


def test_display_currency_is_set_in_config_and_can_be_changed(load_with) -> None:
    assert load_settings(env={}).display.currency == "MMK"  # provisional, to be confirmed
    assert load_with({"display": {"currency": "USD"}}).display.currency == "USD"


def test_display_currency_may_be_empty(load_with) -> None:
    assert load_with({"display": {"currency": ""}}).display.currency == ""


@pytest.mark.parametrize("bad", ["mmk", "KYAT", "M1K"])
def test_display_currency_must_be_a_three_letter_code(load_with, bad: str) -> None:
    with pytest.raises(ConfigError, match="currency"):
        load_with({"display": {"currency": bad}})


def test_display_is_not_a_sql_parameter() -> None:
    names = settings_parameters(load_settings(env={}))
    assert not any(name.startswith("display_") for name in names)
