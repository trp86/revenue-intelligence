"""Story #18 AC5: smoke test that runs on a fresh clone with no data/."""

from __future__ import annotations

from datetime import date

import revint
from revint.config import DEFAULT_SETTINGS_FILE, Settings, config_hash, load_settings


def test_ac5_revint_imports() -> None:
    assert revint.__name__ == "revint"


def test_ac5_settings_loader_reads_the_committed_config() -> None:
    assert DEFAULT_SETTINGS_FILE.is_file()
    settings = load_settings(env={})
    assert isinstance(settings, Settings)
    assert settings.asof.date == date(2020, 2, 29)
    assert len(config_hash(settings)) == 64
