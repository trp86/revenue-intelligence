"""Stories #28 and #37: the `labels` section of config/settings.yaml (spec 01 S3).

Channel labels come from `Channel_Category` and branch labels from `Branch_Name` (decision of
the maintainer on issue #37). The maps hold only the obvious spelling variants.
"""

from __future__ import annotations

import pytest

from revint.config import ConfigError, config_hash, load_settings

KNOWN = ["Cat", "Branch", "Other"]


def known(**labels: object) -> dict[str, object]:
    """Settings extras with a small expected_columns list and the given labels keys.

    Keys the test does not give point at the list's own columns, so only the rule under test
    is checked.
    """
    return {
        "ingest": {"expected_columns": KNOWN},
        "net_sales": {"field": "Cat", "candidate_columns": ["Cat"], "quantity_field": "Cat"},
        "customers": {"code_column": "Cat", "name_column": "Cat", "branch_column": "Cat"},
        "labels": {"channel_columns": ["Cat"], "branch_columns": ["Branch"], **labels},
    }


def test_committed_config_names_the_label_columns() -> None:
    settings = load_settings(env={})
    assert settings.labels.channel_columns == ["Channel_Category"]
    assert settings.labels.branch_columns == ["Branch_Name"]
    for column in (*settings.labels.channel_columns, *settings.labels.branch_columns):
        assert column in settings.ingest.expected_columns


def test_committed_config_holds_only_the_obvious_variants() -> None:
    labels = load_settings(env={}).labels
    assert labels.channel_map == {"MODERN TRADE": "Modern Trade", "MT": "Modern Trade"}
    assert labels.branch_map == {
        "MAGWAY": "Magway",
        "Hpa-an": "Hpa-An",
        "PyinooLwin": "Pyinoolwin",
        "PYAY": "Pyay",
        "DAWEI": "Dawei",
    }


def test_defaults_apply_when_the_section_is_absent(load_with) -> None:
    labels = load_with().labels
    assert labels.channel_columns == ["Channel_Category"]
    assert labels.branch_columns == ["Branch_Name"]
    assert labels.channel_map == {} and labels.branch_map == {}


def test_maps_and_columns_load_as_given(load_with) -> None:
    labels = load_with(
        known(
            channel_columns=["Cat", "Other"],
            channel_map={"MT": "Modern Trade"},
            branch_columns=["Branch"],
            branch_map={"BR1": "Branch 1"},
        )
    ).labels
    assert labels.channel_columns == ["Cat", "Other"]
    assert labels.channel_map == {"MT": "Modern Trade"}
    assert labels.branch_map == {"BR1": "Branch 1"}


def test_unknown_key_fails_and_names_it(load_with) -> None:
    with pytest.raises(ConfigError, match=r"labels\.region_map"):
        load_with(known(region_map={}))


def test_a_map_that_is_not_a_mapping_fails_and_names_the_key(load_with) -> None:
    with pytest.raises(ConfigError, match=r"labels\.channel_map"):
        load_with(known(channel_map=["MT"]))


@pytest.mark.parametrize("key", ["channel_columns", "branch_columns"])
def test_an_empty_column_list_fails_and_names_the_key(load_with, key: str) -> None:
    with pytest.raises(ConfigError, match=rf"labels\.{key}"):
        load_with(known(**{key: []}))


@pytest.mark.parametrize("key", ["channel_columns", "branch_columns"])
def test_a_repeated_column_fails_and_names_the_key(load_with, key: str) -> None:
    with pytest.raises(ConfigError, match=rf"labels\.{key}.*Cat"):
        load_with(known(**{key: ["Cat", "Cat"]}))


@pytest.mark.parametrize("key", ["channel_columns", "branch_columns"])
def test_a_column_not_in_expected_columns_fails_and_names_the_key(load_with, key: str) -> None:
    with pytest.raises(ConfigError, match=rf"labels\.{key}.*Nowhere_Col"):
        load_with(known(**{key: ["Nowhere_Col"]}))


def test_the_check_against_expected_columns_is_skipped_while_the_list_is_empty(load_with) -> None:
    settings = load_with({"labels": {"channel_columns": ["Anything"]}})
    assert settings.labels.channel_columns == ["Anything"]


@pytest.mark.parametrize("key", ["channel_map", "branch_map"])
@pytest.mark.parametrize("bad", [{"": "X"}, {"  ": "X"}, {"MT": ""}, {"MT": "  "}])
def test_a_blank_key_or_value_fails_and_names_the_map(load_with, key: str, bad) -> None:
    with pytest.raises(ConfigError, match=rf"labels\.{key}"):
        load_with(known(**{key: bad}))


@pytest.mark.parametrize("key", ["channel_map", "branch_map"])
def test_two_keys_that_are_equal_once_trimmed_fail_and_name_the_map(load_with, key: str) -> None:
    with pytest.raises(ConfigError, match=rf"labels\.{key}.*MT"):
        load_with(known(**{key: {"MT": "Modern Trade", " MT ": "Modern Trade"}}))


def test_keys_that_differ_only_by_case_are_two_keys(load_with) -> None:
    labels = load_with(known(channel_map={"MT": "A", "mt": "B"})).labels
    assert labels.channel_map == {"MT": "A", "mt": "B"}


def test_changing_a_map_changes_the_config_hash(load_with) -> None:
    a = load_with(known(channel_map={"MT": "Modern Trade"}), name="a")
    b = load_with(known(channel_map={"MT": "Supermarket"}), name="b")
    assert config_hash(a) != config_hash(b)


def test_changing_a_label_column_changes_the_config_hash(load_with) -> None:
    a = load_with(known(channel_columns=["Cat"]), name="a")
    b = load_with(known(channel_columns=["Other"]), name="b")
    assert config_hash(a) != config_hash(b)
