"""Story #41: the `quality` section of config/settings.yaml (spec 01 section 5).

Severity and action are a fixed value per rule S1 to S12, kept in config because they are
business judgements (maintainer's decision on issue #41), not computed from a percentage.
"""

from __future__ import annotations

import pytest

from revint.config import RULE_IDS, ConfigError, config_hash, load_settings

HIGH = {"S5", "S6", "S9", "S10"}
WARNING = {"S2", "S3", "S4", "S7", "S11"}
INFO = {"S1", "S8", "S12"}


def full(value: str) -> dict[str, str]:
    return dict.fromkeys(RULE_IDS, value)


def test_the_rule_ids_are_s1_to_s12() -> None:
    assert RULE_IDS == [f"S{i}" for i in range(1, 13)]


def test_committed_config_assigns_the_agreed_severities() -> None:
    severity = load_settings(env={}).quality.severity
    assert set(severity) == set(RULE_IDS)
    assert {r for r, v in severity.items() if v == "high"} == HIGH
    assert {r for r, v in severity.items() if v == "warning"} == WARNING
    assert {r for r, v in severity.items() if v == "info"} == INFO


def test_committed_config_assigns_the_agreed_actions() -> None:
    action = load_settings(env={}).quality.action
    assert action == {
        "S1": "transformed",
        "S2": "flagged",
        "S3": "transformed",
        "S4": "recorded",
        "S5": "excluded",
        "S6": "flagged",
        "S7": "flagged",
        "S8": "flagged",
        "S9": "excluded",
        "S10": "excluded",
        "S11": "flagged",
        "S12": "recorded",
    }


def test_defaults_apply_when_the_section_is_absent(load_with) -> None:
    quality = load_with().quality
    assert quality.severity == load_settings(env={}).quality.severity
    assert quality.action == load_settings(env={}).quality.action


def test_a_changed_value_is_loaded(load_with) -> None:
    severity = {**full("info"), "S5": "warning"}
    assert load_with({"quality": {"severity": severity}}).quality.severity["S5"] == "warning"


def test_unknown_key_fails_and_names_it(load_with) -> None:
    with pytest.raises(ConfigError, match=r"quality\.threshold"):
        load_with({"quality": {"threshold": 5}})


@pytest.mark.parametrize("key", ["severity", "action"])
def test_a_missing_rule_fails_and_names_it(load_with, key: str) -> None:
    value = "info" if key == "severity" else "flagged"
    mapping = full(value)
    del mapping["S7"]
    with pytest.raises(ConfigError, match=rf"quality\.{key}.*S7"):
        load_with({"quality": {key: mapping}})


@pytest.mark.parametrize("key", ["severity", "action"])
def test_an_unknown_rule_fails_and_names_it(load_with, key: str) -> None:
    value = "info" if key == "severity" else "flagged"
    with pytest.raises(ConfigError, match=rf"quality\.{key}.*S13"):
        load_with({"quality": {key: {**full(value), "S13": value}}})


@pytest.mark.parametrize("bad", ["critical", "", "HIGH", None])
def test_an_unknown_severity_level_fails_and_names_the_key(load_with, bad) -> None:
    with pytest.raises(ConfigError, match=r"quality\.severity"):
        load_with({"quality": {"severity": {**full("info"), "S3": bad}}})


@pytest.mark.parametrize("bad", ["dropped", "", "Flagged", None])
def test_an_unknown_action_fails_and_names_the_key(load_with, bad) -> None:
    with pytest.raises(ConfigError, match=r"quality\.action"):
        load_with({"quality": {"action": {**full("flagged"), "S3": bad}}})


@pytest.mark.parametrize("level", ["info", "warning", "high"])
def test_every_severity_level_is_allowed(load_with, level: str) -> None:
    assert set(load_with({"quality": {"severity": full(level)}}).quality.severity.values()) == {
        level
    }


@pytest.mark.parametrize("name", ["flagged", "excluded", "transformed", "recorded"])
def test_every_action_value_is_allowed(load_with, name: str) -> None:
    assert set(load_with({"quality": {"action": full(name)}}).quality.action.values()) == {name}


def test_changing_a_severity_or_an_action_changes_the_config_hash(load_with) -> None:
    base = load_with({"quality": {"severity": full("info")}}, name="a")
    other = load_with({"quality": {"severity": {**full("info"), "S1": "high"}}}, name="b")
    third = load_with({"quality": {"action": {**full("flagged"), "S1": "excluded"}}}, name="c")
    assert len({config_hash(base), config_hash(other), config_hash(third)}) == 3
