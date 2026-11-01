"""Story #104: the `whitespace` section of config/settings.yaml.

The full set of checks (defaults, invalid values, config hash, SQL parameters) is in
`test_settings_engines.py`; this module holds the section's own basics.
"""

from __future__ import annotations

from revint.config import load_settings


def test_whitespace_defaults_load_and_can_be_changed(load_with) -> None:
    assert load_settings(env={}).whitespace.min_peer_penetration == 0.5
    assert load_with({"whitespace": {"lookback_months": 6}}).whitespace.lookback_months == 6
