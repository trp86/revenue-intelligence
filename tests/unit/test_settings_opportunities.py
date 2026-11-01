"""Story #104: the `opportunities` section of config/settings.yaml.

The full set of checks (defaults, invalid values, config hash, SQL parameters) is in
`test_settings_engines.py`; this module holds the section's own basics.
"""

from __future__ import annotations

from revint.config import load_settings


def test_opportunities_defaults_load_and_can_be_changed(load_with) -> None:
    assert load_settings(env={}).opportunities.top_n_per_type is None
    assert load_with({"opportunities": {"top_n_per_type": 50}}).opportunities.top_n_per_type == 50
