"""Story #72: the `product` section of config/settings.yaml.

The full set of checks (defaults, invalid values, column cross-checks, config hash, SQL
parameters) is in `test_settings_gold.py`; this module holds the section's own basics.
"""

from __future__ import annotations

from revint.config import load_settings


def test_product_columns_default_to_the_provisional_hierarchy(load_with) -> None:
    product = load_settings(env={}).product
    assert product.code_column == "SCJ_CODE_1"
    assert (
        load_with({"product": {"brand_column": "Actual_Brands_2"}}).product.brand_column
        == "Actual_Brands_2"
    )
