"""The API side of sign-in (story #191): the session cookie and the check every data endpoint
runs. The users, hashes and sessions themselves are `revint.auth`.
"""

from __future__ import annotations

from fastapi import Request

from revint.auth import SessionStore

COOKIE = "revint_session"


class NotSignedInError(Exception):
    """The request has no valid session; answered with 401."""


def require_user(request: Request, store: SessionStore) -> str:
    """The signed-in user of the request, or NotSignedInError."""
    user = store.user_for(request.cookies.get(COOKIE))
    if user is None:
        raise NotSignedInError
    return user
