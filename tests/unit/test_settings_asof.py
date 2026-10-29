"""Story #16: the `asof` section of config/settings.yaml (AC3, AC6)."""

from __future__ import annotations

from datetime import date

from revint.config import load_settings


def test_ac3_asof_date_is_2020_02_29_in_committed_config() -> None:
    assert load_settings(env={}).asof.date == date(2020, 2, 29)
