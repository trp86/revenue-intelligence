"""Story #72: the `peer_groups` section of config/settings.yaml.

The full set of checks (defaults, invalid values, column cross-checks, config hash, SQL
parameters) is in `test_settings_gold.py`; this module holds the section's own basics.
"""

from __future__ import annotations

from revint.config import load_settings


def test_peer_group_defaults_are_channel_and_branch_with_a_channel_fallback(load_with) -> None:
    group = load_settings(env={}).peer_groups
    assert group.columns == ["Channel_Category", "Branch_Name"]
    assert group.fallback_columns == ["Channel_Category"]
    assert load_with({"peer_groups": {"min_size": 3}}).peer_groups.min_size == 3
