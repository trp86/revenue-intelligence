"""Story #137: the `ai` section of config/settings.yaml."""

from __future__ import annotations

import pytest

from revint.config import ConfigError, load_settings
from revint.pipeline import settings_parameters


def test_ai_defaults_load_and_can_be_changed(load_with) -> None:
    ai = load_settings(env={}).ai
    assert (ai.enabled, ai.temperature, ai.max_facts, ai.max_retries) == (True, 0.2, 15, 2)
    assert (ai.mask_identifiers, ai.precompute_top_n, ai.daily_call_limit) == (True, 20, 200)
    assert ai.model.startswith("gemini-")
    assert load_with({"ai": {"max_facts": 8}}).ai.max_facts == 8


def test_ai_rejects_an_out_of_range_value(load_with) -> None:
    with pytest.raises(ConfigError, match="temperature"):
        load_with({"ai": {"temperature": 3}})


def test_ai_is_not_a_sql_parameter() -> None:
    assert not any(name.startswith("ai_") for name in settings_parameters(load_settings(env={})))
