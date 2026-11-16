"""Story #191: sign-in with a user name and password; every data endpoint needs a session.

These tests use the real login check (marker `real_auth`); the other API tests run with the
check replaced by a stand-in user (tests/unit/conftest.py).
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from revint import auth
from revint.api.app import create_app
from revint.cli import app as cli_app
from revint.config import Settings, load_settings

pytestmark = pytest.mark.real_auth

API = "/api/v1"
PASSWORD = "correct horse battery"
PROTECTED = [
    ("get", "/definitions"),
    ("get", "/overview"),
    ("get", "/opportunities"),
    ("get", "/opportunities/x"),
    ("get", "/opportunities/x/brief"),
    ("post", "/opportunities/x/brief"),
    ("get", "/auth/me"),
]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    base = load_settings(env={})
    users = tmp_path / "users.json"
    auth.add_user(users, "anna", PASSWORD)
    return base.model_copy(
        update={
            "paths": base.paths.model_copy(
                update={"users": users, "app_db": tmp_path / "app.duckdb"}
            ),
            "auth": base.auth.model_copy(update={"max_attempts": 3, "lockout_minutes": 15}),
        }
    )


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


def sign_in(client: TestClient, name: str = "anna", password: str = PASSWORD):
    return client.post(f"{API}/auth/login", json={"username": name, "password": password})


# AC2: the API is protected, not just the screen ------


@pytest.mark.parametrize(("method", "path"), PROTECTED)
def test_ac2_every_data_endpoint_needs_a_session(
    client: TestClient, method: str, path: str
) -> None:
    response = getattr(client, method)(API + path)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_signed_in"


def test_ac2_health_and_login_stay_open(client: TestClient) -> None:
    assert client.get(f"{API}/health").status_code == 200
    assert sign_in(client, password="wrong password!").status_code == 401  # reachable, refused


def test_ac2_a_signed_in_user_reaches_the_data(client: TestClient) -> None:
    assert sign_in(client).status_code == 200
    assert client.get(f"{API}/auth/me").json() == {"user": "anna"}
    assert client.get(f"{API}/definitions").status_code == 200


def test_ac2_no_users_file_means_nobody_gets_in(settings: Settings, tmp_path: Path) -> None:
    """Fail closed: without users nothing opens up."""
    empty = settings.model_copy(
        update={"paths": settings.paths.model_copy(update={"users": tmp_path / "none.json"})}
    )
    client = TestClient(create_app(empty))
    assert sign_in(client).status_code == 401
    assert client.get(f"{API}/overview").status_code == 401


# AC3: credentials are never in git, and hashed ------


def test_ac3_passwords_are_stored_as_argon2id_hashes(settings: Settings) -> None:
    text = settings.paths.users.read_text(encoding="utf-8")
    stored = json.loads(text)["users"]["anna"]["hash"]
    assert stored.startswith("$argon2id$")
    assert PASSWORD not in text


def test_ac3_the_users_file_is_git_ignored_and_not_tracked() -> None:
    default = load_settings(env={}).paths.users
    root = Path(__file__).resolve().parents[2]
    check = subprocess.run(
        ["git", "check-ignore", "-q", str(default.relative_to(root))], cwd=root, check=False
    )
    assert check.returncode == 0, "paths.users must be git-ignored"
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True
    ).stdout
    assert "users.json" not in tracked


def test_ac3_the_cli_adds_a_user_without_echoing_the_password(tmp_path: Path) -> None:
    users = tmp_path / "users.json"
    result = CliRunner().invoke(
        cli_app,
        ["user", "add", "ben", "--users-file", str(users)],
        input=f"{PASSWORD}\n{PASSWORD}\n",
    )
    assert result.exit_code == 0, result.output
    assert PASSWORD not in result.output
    assert auth.verify(users, "ben", PASSWORD)
    assert not auth.verify(users, "ben", "something else entirely")


def test_ac3_a_short_password_is_refused(tmp_path: Path) -> None:
    with pytest.raises(auth.AuthError, match="at least"):
        auth.add_user(tmp_path / "users.json", "carl", "short")


# AC4: sessions ------


def test_ac4_the_session_cookie_is_httponly_and_follows_the_config(client: TestClient) -> None:
    cookie = sign_in(client).headers["set-cookie"].lower()
    assert "revint_session=" in cookie
    assert "httponly" in cookie
    assert "samesite=lax" in cookie  # the local default; none + secure for cross-site hosting
    assert "max-age=" in cookie


def test_ac4_samesite_none_requires_secure() -> None:
    with pytest.raises(ValueError, match="cookie_secure"):
        load_settings(env={}).auth.model_validate(
            {"cookie_samesite": "none", "cookie_secure": False}
        )


def test_ac4_a_session_expires_after_session_hours(
    client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [1_000_000.0]
    monkeypatch.setattr(auth, "_now", lambda: now[0])
    sign_in(client)
    assert client.get(f"{API}/auth/me").status_code == 200
    now[0] += settings.auth.session_hours * 3600 + 1
    assert client.get(f"{API}/auth/me").status_code == 401


def test_ac4_sign_out_ends_the_session(client: TestClient) -> None:
    sign_in(client)
    token = client.cookies.get("revint_session")
    assert client.post(f"{API}/auth/logout").status_code == 200
    client.cookies.set("revint_session", token)  # even a kept copy of the cookie no longer works
    assert client.get(f"{API}/auth/me").status_code == 401


# AC5: brute force is limited ------


def test_ac5_too_many_failures_lock_the_user_name(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="revint.auth")
    for _ in range(3):
        assert sign_in(client, password="wrong password!").status_code == 401
    locked = sign_in(client)  # even the right password is refused while locked
    assert locked.status_code == 429
    assert locked.json()["error"]["code"] == "locked"
    assert "failed sign-in" in caplog.text and "anna" in caplog.text
    assert "wrong password!" not in caplog.text and PASSWORD not in caplog.text


def test_ac5_the_lock_ends_after_lockout_minutes(
    client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [2_000_000.0]
    monkeypatch.setattr(auth, "_now", lambda: now[0])
    for _ in range(3):
        sign_in(client, password="wrong password!")
    assert sign_in(client).status_code == 429
    now[0] += settings.auth.lockout_minutes * 60 + 1
    assert sign_in(client).status_code == 200
