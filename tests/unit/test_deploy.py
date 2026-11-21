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


# Render and MotherDuck (story #195) ------


def _md_version() -> str:
    text = (ROOT / "deploy" / "md_import.py").read_text(encoding="utf-8")
    return text.split('MOTHERDUCK_DUCKDB = "', 1)[1].split('"', 1)[0]


def test_195_the_image_holds_no_data_and_pins_the_motherduck_duckdb() -> None:
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "warehouse.duckdb" not in text and "COPY data" not in text  # the data is in MotherDuck
    assert f"ARG MOTHERDUCK_DUCKDB={_md_version()}" in text
    assert 'uv pip install --python /app/.venv/bin/python "duckdb==${MOTHERDUCK_DUCKDB}"' in text
    assert "uv sync --frozen --no-dev" in text
    assert "USER " in text and "USER root" not in text
    assert "REVINT_SETTINGS_OVERLAY=config/settings.production.yaml" in text


def test_195_the_entrypoint_writes_users_and_serves_on_the_render_port() -> None:
    script = (ROOT / "deploy" / "entrypoint.sh").read_text(encoding="utf-8")
    assert "REVINT_USERS_JSON" in script and 'mkdir -p "$(dirname "$REVINT_PATHS_USERS")"' in script
    assert 'revint serve --host 0.0.0.0 --port "${PORT:-10000}"' in script
    assert chr(13) not in script  # a shell script with Windows line endings would not run


def test_195_the_render_blueprint_holds_no_secret_values() -> None:
    import yaml

    blueprint = yaml.safe_load((ROOT / "render.yaml").read_text(encoding="utf-8"))
    service = blueprint["services"][0]
    assert (service["runtime"], service["plan"], service["healthCheckPath"]) == (
        "docker",
        "free",
        "/api/v1/health",
    )
    secrets = {v["key"]: v for v in service["envVars"]}
    for key in ("MOTHERDUCK_TOKEN", "GEMINI_API_KEY", "REVINT_USERS_JSON"):
        assert secrets[key] == {"key": key, "sync": False}  # entered in the dashboard only


def test_195_no_data_env_or_database_file_is_tracked() -> None:
    """Checked before pushing to the private GitHub.com repo (docs/deploy.md)."""
    import subprocess

    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    bad = [
        f
        for f in tracked
        if f.startswith("data/")
        or f == ".env"
        or f.endswith((".duckdb", ".parquet", ".xlsx"))
        or f.endswith("users.json")
    ]
    assert bad == []


def test_195_the_upload_checks_on_the_motherduck_duckdb_before_uploading() -> None:
    text = (ROOT / "deploy" / "upload_warehouse.py").read_text(encoding="utf-8")
    check, upload = text.index("check_api.py"), text.index("uploading to MotherDuck")
    assert check < upload  # the API check on 1.5.6 runs first, and a failure stops the upload
    assert "nothing was uploaded" in text


def test_ac5_the_users_json_written_by_the_cli_is_what_the_entrypoint_expects(
    tmp_path: Path,
) -> None:
    from revint import auth

    users = tmp_path / "users.json"
    auth.add_user(users, "anna", "a long enough password")
    body = json.loads(users.read_text(encoding="utf-8"))
    assert set(body) == {"users"} and "hash" in body["users"]["anna"]
