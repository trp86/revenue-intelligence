"""Story #72: the `regions` section of config/settings.yaml.

The full set of checks (defaults, invalid values, column cross-checks, config hash, SQL
parameters) is in `test_settings_gold.py`; this module holds the section's own basics.
"""

from __future__ import annotations

from revint.config import load_settings


def test_region_defaults_to_the_source_column_with_an_empty_override_map(load_with) -> None:
    regions = load_settings(env={}).regions
    assert (regions.source_column, regions.branch_to_region) == ("Region", {})
    assert load_with(
        {"regions": {"branch_to_region": {"Pyay": "Central"}}}
    ).regions.branch_to_region == {"Pyay": "Central"}
