"""Story #104: the `dormancy` section of config/settings.yaml.

The full set of checks (defaults, invalid values, config hash, SQL parameters) is in
`test_settings_engines.py`; this module holds the section's own basics.
"""

from __future__ import annotations

from revint.config import load_settings


def test_dormancy_defaults_load_and_can_be_changed(load_with) -> None:
    assert load_settings(env={}).dormancy.min_orders == 4
    assert load_with({"dormancy": {"min_days": 60}}).dormancy.min_days == 60
