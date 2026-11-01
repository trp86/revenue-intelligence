"""Story #104: the E3 config sections (spec 03 section 6).

Covers `recovery`, `dormancy`, `whitespace`, `crosssell`, `scoring`, `value` and `opportunities`.
Each section also has its own small module (`test_settings_<section>.py`) that the
section-per-test rule in `test_settings.py` requires; the full set of checks is here.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
import yaml

from revint.config import ConfigError, Settings, config_hash, load_settings
from revint.pipeline import settings_parameters

ROOT = Path(__file__).resolve().parents[2]
Loader = Callable[..., Settings]
SECTIONS = ("recovery", "dormancy", "whitespace", "crosssell", "scoring", "value", "opportunities")


# AC1: the committed config and the defaults ------


def test_ac1_committed_recovery_defaults() -> None:
    r = load_settings(env={}).recovery
    assert (r.window_months, r.min_decline_pct, r.min_prior_orders) == (3, 20, 3)


def test_ac1_committed_dormancy_defaults() -> None:
    d = load_settings(env={}).dormancy
    assert (d.min_orders, d.interval_multiple, d.min_days, d.lookback_months) == (4, 2.0, 45, 12)


def test_ac1_committed_whitespace_defaults() -> None:
    w = load_settings(env={}).whitespace
    assert (w.min_peer_penetration, w.lookback_months) == (0.5, 12)


def test_ac1_committed_crosssell_defaults() -> None:
    c = load_settings(env={}).crosssell
    assert (c.min_support, c.min_confidence, c.min_lift, c.lookback_months) == (30, 0.3, 1.2, 12)


def test_ac1_committed_scoring_defaults() -> None:
    s = load_settings(env={}).scoring
    assert (s.weight_value, s.weight_evidence, s.weight_urgency, s.weight_data_quality) == (
        0.40,
        0.30,
        0.20,
        0.10,
    )
    assert (s.priority_high, s.priority_medium) == (70, 40)
    assert (s.confidence_high, s.confidence_medium) == (0.7, 0.4)


def test_ac1_committed_value_defaults() -> None:
    v = load_settings(env={}).value
    assert (v.low_factor, v.high_factor) == (0.25, 0.75)


def test_ac1_defaults_apply_when_the_sections_are_absent(load_with: Loader) -> None:
    s = load_with()
    committed = load_settings(env={})
    for section in SECTIONS:
        assert getattr(s, section) == getattr(committed, section), section


def test_ac1_the_committed_file_lists_every_new_section() -> None:
    data = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text(encoding="utf-8"))
    for section in SECTIONS:
        assert section in data, section


# AC2: the two blank defaults are provisional ------


def test_ac2_min_prior_sales_defaults_to_no_minimum() -> None:
    assert load_settings(env={}).recovery.min_prior_sales == 0


def test_ac2_top_n_per_type_defaults_to_no_limit() -> None:
    assert load_settings(env={}).opportunities.top_n_per_type is None


def test_ac2_both_are_marked_provisional_in_the_config_and_the_spec() -> None:
    config = (ROOT / "config" / "settings.yaml").read_text(encoding="utf-8")
    spec = (ROOT / "docs" / "specs" / "03-opportunity-engines.md").read_text(encoding="utf-8")
    for key in ("min_prior_sales", "top_n_per_type"):
        line = next(line for line in config.splitlines() if line.strip().startswith(key))
        assert "provisional" in line.lower(), key
        row = next(
            line
            for line in spec.splitlines()
            if line.startswith("| `") and (f"`{key}`" in line or f".{key}`" in line)
        )
        assert "provisional" in row.lower(), key


def test_ac2_both_can_be_set(load_with: Loader) -> None:
    s = load_with(
        {"recovery": {"min_prior_sales": 50000}, "opportunities": {"top_n_per_type": 200}}
    )
    assert (s.recovery.min_prior_sales, s.opportunities.top_n_per_type) == (50000, 200)


# AC3: invalid values fail and name the key ------


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("recovery", "window_months", 0),
        ("recovery", "window_months", 13),
        ("recovery", "min_decline_pct", -1),
        ("recovery", "min_decline_pct", 101),
        ("recovery", "min_prior_sales", -1),
        ("recovery", "min_prior_orders", 0),
        ("dormancy", "min_orders", 1),
        ("dormancy", "interval_multiple", 0.9),
        ("dormancy", "min_days", -1),
        ("dormancy", "lookback_months", 0),
        ("whitespace", "min_peer_penetration", 0),
        ("whitespace", "min_peer_penetration", 1.5),
        ("whitespace", "lookback_months", 0),
        ("crosssell", "min_support", 0),
        ("crosssell", "min_confidence", 1.5),
        ("crosssell", "min_lift", -0.1),
        ("crosssell", "lookback_months", 0),
        ("scoring", "priority_high", 101),
        ("scoring", "confidence_medium", -0.1),
        ("value", "low_factor", -0.1),
        ("opportunities", "top_n_per_type", 0),
    ],
)
def test_ac3_an_out_of_range_value_fails_and_names_the_key(
    load_with: Loader, section: str, key: str, value: object
) -> None:
    with pytest.raises(ConfigError, match=rf"{section}\.{key}"):
        load_with({section: {key: value}})


@pytest.mark.parametrize("value", ["three", True, 1.5])
def test_ac3_an_integer_key_refuses_text_booleans_and_fractions(
    load_with: Loader, value: object
) -> None:
    with pytest.raises(ConfigError, match=r"recovery\.window_months"):
        load_with({"recovery": {"window_months": value}})


def test_ac3_priority_high_must_be_above_priority_medium(load_with: Loader) -> None:
    with pytest.raises(ConfigError, match=r"scoring.*priority_high.*priority_medium"):
        load_with({"scoring": {"priority_high": 40, "priority_medium": 40}})


def test_ac3_confidence_high_must_be_above_confidence_medium(load_with: Loader) -> None:
    with pytest.raises(ConfigError, match=r"scoring.*confidence_high.*confidence_medium"):
        load_with({"scoring": {"confidence_high": 0.3, "confidence_medium": 0.4}})


def test_ac3_weights_must_sum_to_one(load_with: Loader) -> None:
    with pytest.raises(ConfigError, match=r"scoring.*weights.*1"):
        load_with({"scoring": {"weight_value": 0.5}})


def test_ac3_weights_that_sum_to_one_with_rounding_are_accepted(load_with: Loader) -> None:
    weights = {"weight_value": 0.1, "weight_evidence": 0.2, "weight_urgency": 0.3}
    s = load_with({"scoring": {**weights, "weight_data_quality": 0.4}})
    assert s.scoring.weight_data_quality == 0.4


def test_ac3_a_negative_weight_fails(load_with: Loader) -> None:
    with pytest.raises(ConfigError, match=r"scoring\.weight_urgency"):
        load_with(
            {
                "scoring": {
                    "weight_value": 0.6,
                    "weight_evidence": 0.3,
                    "weight_urgency": -0.1,
                    "weight_data_quality": 0.2,
                }
            }
        )


def test_ac3_low_factor_must_be_below_high_factor(load_with: Loader) -> None:
    with pytest.raises(ConfigError, match=r"value.*low_factor.*high_factor"):
        load_with({"value": {"low_factor": 0.75, "high_factor": 0.75}})


def test_ac3_unknown_keys_fail_and_name_them(load_with: Loader) -> None:
    for section in SECTIONS:
        with pytest.raises(ConfigError, match=rf"{section}\.nope"):
            load_with({section: {"nope": 1}})


# AC4: whitespace.min_peer_size is not a key ------


def test_ac4_whitespace_min_peer_size_is_refused(load_with: Loader) -> None:
    with pytest.raises(ConfigError, match=r"whitespace\.min_peer_size"):
        load_with({"whitespace": {"min_peer_size": 10}})


def test_ac4_the_minimum_group_size_is_peer_groups_min_size() -> None:
    assert load_settings(env={}).peer_groups.min_size == 10


def test_ac4_the_spec_no_longer_lists_whitespace_min_peer_size() -> None:
    spec = (ROOT / "docs" / "specs" / "03-opportunity-engines.md").read_text(encoding="utf-8")
    assert "whitespace.min_peer_size" not in spec
    assert "peer_groups.min_size" in spec


# AC5: a changed key changes the hash and is a SQL parameter ------

CHANGES = [
    {"recovery": {"window_months": 6}},
    {"recovery": {"min_prior_sales": 1000}},
    {"dormancy": {"interval_multiple": 3.0}},
    {"whitespace": {"min_peer_penetration": 0.6}},
    {"crosssell": {"min_lift": 1.5}},
    {"crosssell": {"lookback_months": 6}},
    {"scoring": {"priority_high": 80}},
    {"value": {"high_factor": 0.9}},
    {"opportunities": {"top_n_per_type": 100}},
]


@pytest.mark.parametrize(
    "change", CHANGES, ids=lambda c: f"{next(iter(c))}-{next(iter(c.values()))}"
)
def test_ac5_a_changed_key_changes_the_config_hash(load_with: Loader, change: dict) -> None:
    assert config_hash(load_with(name="a")) != config_hash(load_with(change, name="b"))


def test_ac5_the_sections_are_sql_parameters_with_no_runner_change() -> None:
    params = settings_parameters(load_settings(env={}))
    assert params["recovery_window_months"] == 3
    assert params["recovery_min_prior_sales"] == 0
    assert params["dormancy_interval_multiple"] == 2.0
    assert params["whitespace_min_peer_penetration"] == 0.5
    assert params["crosssell_lookback_months"] == 12
    assert params["scoring_weight_value"] == 0.40
    assert params["value_low_factor"] == 0.25
    assert params["opportunities_top_n_per_type"] is None


# AC6: each section has its own test module ------


@pytest.mark.parametrize("section", SECTIONS)
def test_ac6_each_new_section_has_its_own_test_module(section: str) -> None:
    assert (ROOT / "tests" / "unit" / f"test_settings_{section}.py").is_file()
    assert section in Settings.model_fields
