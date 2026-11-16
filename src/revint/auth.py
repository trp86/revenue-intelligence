"""Sign-in for the app (story #191): users, password hashes, sessions and lockouts.

- Users and their argon2id password hashes live in `paths.users` (data/users.json by default),
  which is git-ignored and created by `revint user add`. A password is never stored or logged.
- Without a users file nobody can sign in: the app fails closed.
- Sessions and failed attempts are kept in the API process's memory, so restarting the API
  signs everyone out. That is enough for the POC, which runs one API process.
- Only a SHA-256 of each session token is kept, so a memory dump holds no usable token.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

log = logging.getLogger("revint.auth")

_HASHER = PasswordHasher()  # argon2id with the library's recommended cost parameters
_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{1,39}$")
# a real hash to verify against when the user name is unknown, so both cases take as long
_DUMMY_HASH = _HASHER.hash("not a real password, only for timing")


class AuthError(Exception):
    """A user could not be added or removed (bad name, short password, unknown user)."""


def _now() -> float:
    return time.time()


def load_users(path: Path) -> dict[str, str]:
    """User name to password hash; empty when the file does not exist (nobody can sign in)."""
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {name: entry["hash"] for name, entry in data.get("users", {}).items()}


def _save(path: Path, users: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"users": {name: {"hash": users[name]} for name in sorted(users)}}
    path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")


def add_user(path: Path, name: str, password: str, min_length: int = 12) -> None:
    """Add a user, or replace the password of an existing one."""
    if not _NAME.match(name):
        raise AuthError("a user name is 2 to 40 characters: a-z, 0-9, dot, dash or underscore")
    if len(password) < min_length:
        raise AuthError(f"a password needs at least {min_length} characters")
    users = load_users(path)
    users[name] = _HASHER.hash(password)
    _save(path, users)


def remove_user(path: Path, name: str) -> None:
    users = load_users(path)
    if name not in users:
        raise AuthError(f"no user named {name}")
    del users[name]
    _save(path, users)


def verify(path: Path, name: str, password: str) -> bool:
    """True when the password matches the user's hash."""
    stored = load_users(path).get(name)
    try:
        return _HASHER.verify(stored or _DUMMY_HASH, password) and stored is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass
class SessionStore:
    """Sessions and failed attempts of one API process."""

    session_hours: int
    max_attempts: int
    lockout_minutes: int
    _sessions: dict[str, tuple[str, float]] = field(default_factory=dict)
    _failures: dict[str, int] = field(default_factory=dict)
    _locked_until: dict[str, float] = field(default_factory=dict)

    def is_locked(self, name: str) -> bool:
        until = self._locked_until.get(name)
        if until is None:
            return False
        if _now() >= until:
            del self._locked_until[name]
            return False
        return True

    def record_failure(self, name: str) -> None:
        count = self._failures.get(name, 0) + 1
        log.warning("failed sign-in for user %s (%d in a row)", name, count)
        if count >= self.max_attempts:
            self._locked_until[name] = _now() + self.lockout_minutes * 60
            self._failures.pop(name, None)
            log.warning("user %s is locked for %d minutes", name, self.lockout_minutes)
        else:
            self._failures[name] = count

    def start(self, name: str) -> str:
        """A new session for `name`; returns the token for the cookie."""
        self._failures.pop(name, None)
        token = secrets.token_urlsafe(32)
        self._sessions[_digest(token)] = (name, _now() + self.session_hours * 3600)
        return token

    def user_for(self, token: str | None) -> str | None:
        if not token:
            return None
        key = _digest(token)
        found = self._sessions.get(key)
        if found is None:
            return None
        name, expires = found
        if _now() >= expires:
            del self._sessions[key]
            return None
        return name

    def end(self, token: str | None) -> None:
        if token:
            self._sessions.pop(_digest(token), None)
