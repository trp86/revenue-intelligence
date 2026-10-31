"""Story #72: the `marts` section of config/settings.yaml.

The full set of checks (defaults, invalid values, column cross-checks, config hash, SQL
parameters) is in `test_settings_gold.py`; this module holds the section's own basics.
"""

from __future__ import annotations

from revint.config import load_settings


def test_zero_fill_defaults_to_true_and_is_a_boolean(load_with) -> None:
    assert load_settings(env={}).marts.zero_fill is True
    assert load_with({"marts": {"zero_fill": False}}).marts.zero_fill is False
