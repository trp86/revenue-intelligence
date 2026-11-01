"""Story #104: the `recovery` section of config/settings.yaml.

The full set of checks (defaults, invalid values, config hash, SQL parameters) is in
`test_settings_engines.py`; this module holds the section's own basics.
"""

from __future__ import annotations

from revint.config import load_settings


def test_recovery_defaults_load_and_can_be_changed(load_with) -> None:
    assert load_settings(env={}).recovery.window_months == 3
    assert load_with({"recovery": {"window_months": 6}}).recovery.window_months == 6
