"""Story #72: the `calendar` section of config/settings.yaml.

The full set of checks (defaults, invalid values, column cross-checks, config hash, SQL
parameters) is in `test_settings_gold.py`; this module holds the section's own basics.
"""

from __future__ import annotations

from revint.config import load_settings


def test_fiscal_year_starts_in_january_by_default(load_with) -> None:
    assert load_settings(env={}).calendar.fiscal_year_start_month == 1
    assert (
        load_with({"calendar": {"fiscal_year_start_month": 7}}).calendar.fiscal_year_start_month
        == 7
    )
