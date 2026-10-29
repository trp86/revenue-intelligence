"""Story #28: the `ingest` section of config/settings.yaml (AC1, AC2, AC4)."""

from __future__ import annotations

import pytest

from revint.config import ConfigError, load_settings


def test_ac1_committed_config_has_the_spec_01_defaults() -> None:
    ingest = load_settings(env={}).ingest
    assert ingest.sheets == ["RAW SCJ SALES"]
    assert ingest.header_search_rows == 30
    assert ingest.header_min_match == 0.8
    assert ingest.expected_columns == []


def test_ac1_defaults_apply_when_the_section_is_absent(load_with) -> None:
    ingest = load_with().ingest
    assert ingest.sheets == ["RAW SCJ SALES"]
    assert ingest.header_search_rows == 30
    assert ingest.header_min_match == 0.8


def test_ac1_values_from_the_file_override_the_defaults(load_with) -> None:
    ingest = load_with(
        {"ingest": {"sheets": ["A", "B"], "header_search_rows": 10, "header_min_match": 0.5,
                    "expected_columns": ["X", "Y_1", "Y_2"]}}
    ).ingest
    assert ingest.sheets == ["A", "B"]
    assert ingest.header_search_rows == 10
    assert ingest.header_min_match == 0.5
    assert ingest.expected_columns == ["X", "Y_1", "Y_2"]


def test_ac2_unknown_key_fails_and_names_it(load_with) -> None:
    with pytest.raises(ConfigError, match=r"ingest\.header_rows"):
        load_with({"ingest": {"header_rows": 5}})


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("header_search_rows", 0),
        ("header_search_rows", -3),
        ("header_min_match", 0),
        ("header_min_match", 1.5),
        ("sheets", []),
    ],
)
def test_ac2_out_of_range_value_fails_and_names_the_key(load_with, key: str, value) -> None:
    with pytest.raises(ConfigError, match=rf"ingest\.{key}"):
        load_with({"ingest": {key: value}})


def test_ac2_header_min_match_of_one_is_allowed(load_with) -> None:
    assert load_with({"ingest": {"header_min_match": 1}}).ingest.header_min_match == 1


def test_ac4_changing_an_ingest_value_changes_the_config_hash(load_with) -> None:
    from revint.config import config_hash

    a = load_with({"ingest": {"header_search_rows": 30}}, name="a")
    b = load_with({"ingest": {"header_search_rows": 31}}, name="b")
    assert config_hash(a) != config_hash(b)
