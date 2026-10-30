"""Story #40: the `customers` section of config/settings.yaml.

It names the three source columns the customer-code table is built from (spec 01 S4). The
choice of columns is a business input, so it lives in config and is checked at load time.
"""

from __future__ import annotations

import pytest

from revint.config import ConfigError, config_hash, load_settings

KNOWN = ["CustomerCode", "Customer", "Branch_Name", "Other"]


def known(**customers: object) -> dict[str, object]:
    """Settings extras with a small expected_columns list and the given customers keys.

    The net sales section points at the list's first column, so only the customers rules are
    under test.
    """
    return {
        "ingest": {"expected_columns": KNOWN},
        "net_sales": {
            "field": KNOWN[0],
            "candidate_columns": [KNOWN[0]],
            "quantity_field": KNOWN[0],
        },
        "customers": customers,
    }


def test_committed_config_names_the_code_name_and_branch_columns() -> None:
    settings = load_settings(env={})
    customers = settings.customers
    assert customers.code_column == "CustomerCode"
    assert customers.name_column == "Customer"
    assert customers.branch_column == "Branch_Name"
    for column in (customers.code_column, customers.name_column, customers.branch_column):
        assert column in settings.ingest.expected_columns


def test_defaults_apply_when_the_section_is_absent(load_with) -> None:
    customers = load_with().customers
    assert (customers.code_column, customers.name_column, customers.branch_column) == (
        "CustomerCode",
        "Customer",
        "Branch_Name",
    )


def test_the_columns_can_be_changed_in_the_file(load_with) -> None:
    settings = load_with(known(branch_column="Other"))
    assert settings.customers.branch_column == "Other"


def test_unknown_key_fails_and_names_it(load_with) -> None:
    with pytest.raises(ConfigError, match=r"customers\.region_column"):
        load_with(known(region_column="Other"))


@pytest.mark.parametrize("key", ["code_column", "name_column", "branch_column"])
@pytest.mark.parametrize("value", ["", None])
def test_an_empty_column_fails_and_names_the_key(load_with, key: str, value) -> None:
    with pytest.raises(ConfigError, match=rf"customers\.{key}"):
        load_with(known(**{key: value}))


@pytest.mark.parametrize("key", ["code_column", "name_column", "branch_column"])
def test_a_column_that_is_not_in_expected_columns_fails_and_names_the_key(
    load_with, key: str
) -> None:
    with pytest.raises(ConfigError, match=rf"customers\.{key}.*Nowhere_Col"):
        load_with(known(**{key: "Nowhere_Col"}))


def test_the_check_against_expected_columns_is_skipped_while_the_list_is_empty(load_with) -> None:
    settings = load_with({"customers": {"code_column": "Anything"}})
    assert settings.customers.code_column == "Anything"


def test_changing_a_column_changes_the_config_hash(load_with) -> None:
    a = load_with(known(branch_column="Branch_Name"), name="a")
    b = load_with(known(branch_column="Other"), name="b")
    assert config_hash(a) != config_hash(b)
