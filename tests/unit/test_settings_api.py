"""Story #134: the `api` section of config/settings.yaml."""

from __future__ import annotations

import pytest

from revint.config import ConfigError, load_settings
from revint.pipeline import settings_parameters


def test_api_defaults_load_and_can_be_changed(load_with) -> None:
    api = load_settings(env={}).api
    assert (api.host, api.port, api.page_size_default, api.page_size_max) == (
        "127.0.0.1",
        8000,
        25,
        200,
    )
    assert api.cors_origins == ["http://localhost:5173"]
    assert load_with({"api": {"port": 8100}}).api.port == 8100


def test_api_page_size_default_cannot_exceed_the_max(load_with) -> None:
    with pytest.raises(ConfigError, match="page_size_default"):
        load_with({"api": {"page_size_default": 300, "page_size_max": 200}})


def test_api_is_not_a_sql_parameter() -> None:
    assert not any(name.startswith("api_") for name in settings_parameters(load_settings(env={})))
