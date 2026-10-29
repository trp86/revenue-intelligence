"""Story #28: the `void` section of config/settings.yaml (AC1, AC2, AC4)."""

from __future__ import annotations

import pytest

from revint.config import ConfigError, config_hash, load_settings


def test_ac1_committed_config_has_the_spec_01_defaults() -> None:
    void = load_settings(env={}).void
    assert void.blank_means == "not_void"
    assert void.value_map == {}


def test_ac1_defaults_apply_when_the_section_is_absent(load_with) -> None:
    void = load_with().void
    assert void.blank_means == "not_void"
    assert void.value_map == {}


@pytest.mark.parametrize("value", ["not_void", "void"])
def test_ac2_allowed_blank_means_values_load(load_with, value: str) -> None:
    assert load_with({"void": {"blank_means": value}}).void.blank_means == value


@pytest.mark.parametrize("value", ["maybe", "", "NOT_VOID", 0])
def test_ac2_blank_means_outside_the_allowed_set_fails_and_names_the_key(
    load_with, value
) -> None:
    with pytest.raises(ConfigError, match=r"void\.blank_means"):
        load_with({"void": {"blank_means": value}})


def test_ac2_unknown_key_fails_and_names_it(load_with) -> None:
    with pytest.raises(ConfigError, match=r"void\.blank_mean\b"):
        load_with({"void": {"blank_mean": "not_void"}})


def test_ac2_value_map_maps_text_values_to_zero_or_one(load_with) -> None:
    void = load_with({"void": {"value_map": {"X": 1, "Y": 0}}}).void
    assert void.value_map == {"X": 1, "Y": 0}


@pytest.mark.parametrize("flag", [2, -1, "yes"])
def test_ac2_value_map_flag_outside_zero_one_fails(load_with, flag) -> None:
    with pytest.raises(ConfigError, match=r"void\.value_map"):
        load_with({"void": {"value_map": {"X": flag}}})


def test_ac4_changing_blank_means_changes_the_config_hash(load_with) -> None:
    a = load_with({"void": {"blank_means": "not_void"}}, name="a")
    b = load_with({"void": {"blank_means": "void"}}, name="b")
    assert config_hash(a) != config_hash(b)
