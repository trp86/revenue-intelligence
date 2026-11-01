"""Story #104: the `crosssell` section of config/settings.yaml.

The full set of checks (defaults, invalid values, config hash, SQL parameters) is in
`test_settings_engines.py`; this module holds the section's own basics.
"""

from __future__ import annotations

from revint.config import load_settings


def test_crosssell_defaults_load_and_can_be_changed(load_with) -> None:
    assert load_settings(env={}).crosssell.min_support == 30
    assert load_with({"crosssell": {"min_lift": 2.0}}).crosssell.min_lift == 2.0
