"""Story #16: the `paths` section of config/settings.yaml (AC3, AC6)."""

from __future__ import annotations

from pathlib import Path

from revint.config import DEFAULT_SETTINGS_FILE, load_settings

ROOT = Path(__file__).resolve().parents[2]


def test_ac3_committed_config_exists_at_default_location() -> None:
    assert DEFAULT_SETTINGS_FILE == ROOT / "config" / "settings.yaml"
    assert DEFAULT_SETTINGS_FILE.is_file()


def test_ac3_paths_resolve_to_absolute_paths_under_the_project_root() -> None:
    paths = load_settings(env={}).paths
    assert paths.raw == ROOT / "data" / "raw"
    assert paths.bronze == ROOT / "data" / "bronze"
    assert paths.warehouse == ROOT / "data" / "warehouse.duckdb"
    assert paths.app_db == ROOT / "data" / "app.duckdb"


def test_ac3_paths_do_not_depend_on_the_working_directory(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert load_settings(env={}).paths.raw == ROOT / "data" / "raw"
