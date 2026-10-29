"""Story #16: Settings model and loader (spec 10 section 4)."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

from revint.config import ConfigError, Settings, config_hash, load_settings

ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR = Path(__file__).resolve().parent

VALID_YAML = """\
paths:
  raw: data/raw
  bronze: data/bronze
  warehouse: data/warehouse.duckdb
  app_db: data/app.duckdb
asof:
  date: 2020-02-29
"""


def write_settings(tmp_path: Path, text: str = VALID_YAML) -> Path:
    """Write a settings file at <tmp>/config/settings.yaml (project root = <tmp>)."""
    path = tmp_path / "config" / "settings.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# AC1: unknown keys fail and are named ---------------------------------------


def test_ac1_unknown_top_level_key_fails_and_names_key(tmp_path: Path) -> None:
    path = write_settings(tmp_path, VALID_YAML + "typo_section:\n  x: 1\n")
    with pytest.raises(ConfigError, match="typo_section"):
        load_settings(path, env={})


def test_ac1_unknown_nested_key_fails_and_names_key(tmp_path: Path) -> None:
    path = write_settings(tmp_path, VALID_YAML.replace("  raw:", "  rwa:"))
    with pytest.raises(ConfigError, match=r"paths\.rwa"):
        load_settings(path, env={})


# AC2: missing required keys fail and are named ------------------------------


def test_ac2_missing_nested_key_fails_and_names_key(tmp_path: Path) -> None:
    text = VALID_YAML.replace("  date: 2020-02-29\n", "")
    path = write_settings(tmp_path, text)
    with pytest.raises(ConfigError, match=r"asof\.date"):
        load_settings(path, env={})


def test_ac2_missing_path_key_fails_and_names_key(tmp_path: Path) -> None:
    text = VALID_YAML.replace("  warehouse: data/warehouse.duckdb\n", "")
    path = write_settings(tmp_path, text)
    with pytest.raises(ConfigError, match=r"paths\.warehouse"):
        load_settings(path, env={})


def test_ac2_missing_section_fails_and_names_section(tmp_path: Path) -> None:
    path = write_settings(tmp_path, "paths:\n  raw: a\n  bronze: b\n  warehouse: c\n  app_db: d\n")
    with pytest.raises(ConfigError, match="asof"):
        load_settings(path, env={})


def test_empty_file_fails_naming_sections(tmp_path: Path) -> None:
    path = write_settings(tmp_path, "")
    with pytest.raises(ConfigError, match="paths") as info:
        load_settings(path, env={})
    assert "asof" in str(info.value)


def test_missing_file_fails_with_path(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="settings.yaml"):
        load_settings(tmp_path / "config" / "settings.yaml", env={})


# AC4: env overrides for paths only ------------------------------------------


def test_ac4_env_override_for_path_is_applied(tmp_path: Path) -> None:
    other = tmp_path / "elsewhere" / "raw"
    path = write_settings(tmp_path)
    settings = load_settings(path, env={"REVINT_PATHS_RAW": str(other)})
    assert settings.paths.raw == other


def test_ac4_relative_env_override_resolves_against_project_root(tmp_path: Path) -> None:
    path = write_settings(tmp_path)
    settings = load_settings(path, env={"REVINT_PATHS_WAREHOUSE": "scratch/wh.duckdb"})
    assert settings.paths.warehouse == tmp_path / "scratch" / "wh.duckdb"


def test_ac4_empty_env_override_is_ignored(tmp_path: Path) -> None:
    path = write_settings(tmp_path)
    settings = load_settings(path, env={"REVINT_PATHS_RAW": ""})
    assert settings.paths.raw == tmp_path / "data" / "raw"


def test_ac4_env_override_for_business_key_is_ignored(tmp_path: Path) -> None:
    path = write_settings(tmp_path)
    settings = load_settings(
        path,
        env={"REVINT_ASOF_DATE": "2019-01-01", "REVINT_ASOF__DATE": "2019-01-01"},
    )
    assert settings.asof.date == date(2020, 2, 29)


# AC5: config hash -----------------------------------------------------------


def test_ac5_hash_is_identical_when_computed_twice(tmp_path: Path) -> None:
    settings = load_settings(write_settings(tmp_path), env={})
    first = config_hash(settings)
    assert re.fullmatch(r"[0-9a-f]{64}", first)
    assert config_hash(settings) == first


def test_ac5_hash_changes_when_one_value_changes(tmp_path: Path) -> None:
    base = load_settings(write_settings(tmp_path / "a"), env={})
    changed_text = VALID_YAML.replace("2020-02-29", "2020-01-31")
    changed = load_settings(write_settings(tmp_path / "b", changed_text), env={})
    assert config_hash(base) != config_hash(changed)


def test_ac5_hash_is_independent_of_key_order_in_the_file(tmp_path: Path) -> None:
    reordered = "asof:\n  date: 2020-02-29\n" + VALID_YAML.split("asof:")[0]
    a = load_settings(write_settings(tmp_path / "a"), env={})
    b = load_settings(write_settings(tmp_path / "b", reordered), env={})
    assert config_hash(a) == config_hash(b)


def test_ac5_hash_ignores_machine_specific_paths(tmp_path: Path) -> None:
    a = load_settings(write_settings(tmp_path / "a"), env={})
    b = load_settings(write_settings(tmp_path / "b"), env={"REVINT_PATHS_RAW": str(tmp_path / "x")})
    assert config_hash(a) == config_hash(b)


# AC6: every config section ships with a test --------------------------------


def test_ac6_every_section_has_its_own_test_module() -> None:
    sections = list(Settings.model_fields)
    assert sections, "Settings has no sections"
    for section in sections:
        module = TESTS_DIR / f"test_settings_{section}.py"
        assert module.is_file(), f"section '{section}' has no {module.name}"
        assert re.search(r"^def test_\w+", module.read_text(encoding="utf-8"), re.MULTILINE), (
            f"{module.name} contains no test"
        )


def test_ac6_rule_is_documented_in_the_spec() -> None:
    spec = (ROOT / "docs" / "specs" / "10-engineering.md").read_text(encoding="utf-8")
    assert "test_settings_<section>.py" in spec
