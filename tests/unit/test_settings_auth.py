"""Story #191: the `auth` section of config/settings.yaml."""

from __future__ import annotations

import pytest

from revint.config import ConfigError, load_settings
from revint.pipeline import settings_parameters


def test_auth_defaults_load_and_can_be_changed(load_with) -> None:
    auth = load_settings(env={}).auth
    assert (auth.session_hours, auth.max_attempts, auth.lockout_minutes) == (8, 5, 15)
    assert (auth.cookie_secure, auth.cookie_samesite, auth.min_password_length) == (
        False,
        "lax",
        12,
    )
    assert load_with({"auth": {"session_hours": 2}}).auth.session_hours == 2


def test_auth_samesite_none_needs_a_secure_cookie(load_with) -> None:
    with pytest.raises(ConfigError, match="cookie_secure"):
        load_with({"auth": {"cookie_samesite": "none", "cookie_secure": False}})
    ok = load_with({"auth": {"cookie_samesite": "none", "cookie_secure": True}}).auth
    assert ok.cookie_samesite == "none"


def test_auth_limits_must_be_positive(load_with) -> None:
    with pytest.raises(ConfigError, match="max_attempts"):
        load_with({"auth": {"max_attempts": 0}})


def test_the_users_file_defaults_to_data(load_with) -> None:
    users = load_settings(env={}).paths.users
    assert users.parts[-2:] == ("data", "users.json")


def test_auth_is_not_a_sql_parameter() -> None:
    names = settings_parameters(load_settings(env={}))
    assert not any(name.startswith("auth_") for name in names)
