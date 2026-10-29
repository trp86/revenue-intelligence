"""Story #28: the `labels` section of config/settings.yaml (AC1, AC2, AC4)."""

from __future__ import annotations

import pytest

from revint.config import ConfigError, config_hash, load_settings


def test_ac1_committed_config_has_empty_maps() -> None:
    labels = load_settings(env={}).labels
    assert labels.channel_map == {}
    assert labels.branch_map == {}


def test_ac1_defaults_apply_when_the_section_is_absent(load_with) -> None:
    labels = load_with().labels
    assert labels.channel_map == {}
    assert labels.branch_map == {}


def test_ac1_maps_load_as_given(load_with) -> None:
    labels = load_with(
        {"labels": {"channel_map": {"MT": "Modern Trade"}, "branch_map": {"BR1": "Branch 1"}}}
    ).labels
    assert labels.channel_map == {"MT": "Modern Trade"}
    assert labels.branch_map == {"BR1": "Branch 1"}


def test_ac2_unknown_key_fails_and_names_it(load_with) -> None:
    with pytest.raises(ConfigError, match=r"labels\.region_map"):
        load_with({"labels": {"region_map": {}}})


def test_ac2_map_that_is_not_a_mapping_fails_and_names_the_key(load_with) -> None:
    with pytest.raises(ConfigError, match=r"labels\.channel_map"):
        load_with({"labels": {"channel_map": ["MT"]}})


def test_ac4_changing_a_map_changes_the_config_hash(load_with) -> None:
    a = load_with({"labels": {"channel_map": {"MT": "Modern Trade"}}}, name="a")
    b = load_with({"labels": {"channel_map": {"MT": "Supermarket"}}}, name="b")
    assert config_hash(a) != config_hash(b)
