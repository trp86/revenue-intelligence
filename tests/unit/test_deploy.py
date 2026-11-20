"""Story #193: deploying by hand (API on Railway, frontend on Netlify behind a proxy)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from revint.cli import app as cli_app
from revint.config import ConfigError, load_settings

ROOT = Path(__file__).resolve().parents[2]
SETTINGS = ROOT / "config" / "settings.yaml"


# the settings overlay ------


def test_ac2_without_an_overlay_nothing_changes() -> None:
    assert load_settings(env={}).auth.cookie_secure is False


def test_ac2_the_production_overlay_is_merged_and_validates() -> None:
    settings = load_settings(env={"REVINT_SETTINGS_OVERLAY": "config/settings.production.yaml"})
    assert settings.auth.cookie_secure is True
    # everything else still comes from settings.yaml
    assert settings.net_sales.field == load_settings(env={}).net_sales.field


def test_ac2_an_overlay_merges_deeply_and_replaces_lists(tmp_path: Path) -> None:
    overlay = tmp_path / "overlay.yaml"
    overlay.write_text(
        "api:\n  port: 9999\n  cors_origins: [https://example.org]\n", encoding="utf-8"
    )
    api = load_settings(env={"REVINT_SETTINGS_OVERLAY": str(overlay)}).api
    assert (api.port, api.cors_origins) == (9999, ["https://example.org"])
    assert api.page_size_max == load_settings(env={}).api.page_size_max  # untouched keys stay


def test_ac2_an_unknown_key_in_the_overlay_still_fails(tmp_path: Path) -> None:
    overlay = tmp_path / "overlay.yaml"
    overlay.write_text("auth:\n  cookie_secrue: true\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="cookie_secrue"):
        load_settings(env={"REVINT_SETTINGS_OVERLAY": str(overlay)})


def test_ac2_a_missing_overlay_file_fails_clearly(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="overlay"):
        load_settings(env={"REVINT_SETTINGS_OVERLAY": str(tmp_path / "nope.yaml")})


def test_ac2_the_production_overlay_holds_no_secrets() -> None:
    text = (ROOT / "config" / "settings.production.yaml").read_text(encoding="utf-8").lower()
    for word in ("api_key", "password", "secret", "token", "$argon2"):
        assert word not in text


# revint serve --host/--port ------


def test_ac1_serve_takes_host_and_port_for_this_run(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda _app, host, port: seen.update(host=host, port=port))
    result = CliRunner().invoke(cli_app, ["serve", "--host", "0.0.0.0", "--port", "8123"])
    assert result.exit_code == 0, result.output
    assert seen == {"host": "0.0.0.0", "port": 8123}


def test_ac1_serve_defaults_to_the_config(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda _app, host, port: seen.update(host=host, port=port))
    CliRunner().invoke(cli_app, ["serve"])
    api = load_settings(env={}).api
    assert seen == {"host": api.host, "port": api.port}


# the upload is an allow-list ------


def _stage():
    """deploy/stage.py is a script, not a package module: load it from its file."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("stage", ROOT / "deploy" / "stage.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.stage


def test_ac6_the_stage_holds_only_what_the_api_needs(tmp_path: Path) -> None:
    stage = _stage()

    warehouse = tmp_path / "warehouse.duckdb"
    warehouse.write_bytes(b"fake warehouse")
    out = tmp_path / "stage"
    stage(out, warehouse)
    names = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}
    assert {
        "Dockerfile",
        "pyproject.toml",
        "uv.lock",
        "README.md",
        "config/settings.yaml",
        "config/settings.production.yaml",
        "config/definitions.yaml",
        "deploy/entrypoint.sh",
        "data/warehouse.duckdb",
    } <= names
    assert any(n.startswith("src/revint/") for n in names)
    for forbidden in (
        ".env",
        "users.json",
        "app.duckdb",
        "data/raw",
        "data/bronze",
        "frontend/",
        "tests/",
        ".venv",
        "__pycache__",
    ):
        assert not any(forbidden in n for n in names), forbidden


def test_ac6_the_stage_refuses_a_missing_warehouse(tmp_path: Path) -> None:
    stage = _stage()

    with pytest.raises(SystemExit, match="warehouse"):
        stage(tmp_path / "stage", tmp_path / "missing.duckdb")


def test_ac5_the_entrypoint_writes_users_and_serves_on_the_railway_port() -> None:
    script = (ROOT / "deploy" / "entrypoint.sh").read_text(encoding="utf-8")
    assert "REVINT_USERS_JSON" in script and "REVINT_PATHS_USERS" in script
    assert 'revint serve --host 0.0.0.0 --port "${PORT' in script
    assert "\r\n" not in script  # a shell script with Windows line endings would not run


def test_ac5_the_dockerfile_runs_as_a_non_root_user_from_the_lock_file() -> None:
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "uv sync --frozen --no-dev" in text
    assert "USER " in text and "USER root" not in text
    assert "REVINT_SETTINGS_OVERLAY=config/settings.production.yaml" in text


def test_ac5_the_users_json_written_by_the_cli_is_what_the_entrypoint_expects(
    tmp_path: Path,
) -> None:
    from revint import auth

    users = tmp_path / "users.json"
    auth.add_user(users, "anna", "a long enough password")
    body = json.loads(users.read_text(encoding="utf-8"))
    assert set(body) == {"users"} and "hash" in body["users"]["anna"]
