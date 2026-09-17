"""Account creation and verification, plus in-memory session tokens."""
from __future__ import annotations

import secrets

import bcrypt

from webway.server.db import Database


class AuthError(Exception):
    """Raised when credentials are invalid."""


class SessionStore:
    """Maps session tokens to user ids. Purely in-memory, not persisted."""

    def __init__(self):
        self._tokens: dict[str, int] = {}

    def issue(self, user_id: int) -> str:
        token = secrets.token_hex(32)
        self._tokens[token] = user_id
        return token

    def resolve(self, token: str) -> int | None:
        return self._tokens.get(token)

    def revoke(self, token: str) -> None:
        self._tokens.pop(token, None)


async def authenticate(db: Database, username: str, password: str) -> int:
    """Verify credentials, creating the account on first use. Returns the user id."""
    row = await db.get_user_by_username(username)
    if row is None:
        password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        return await db.create_user(username, password_hash)
    if not bcrypt.checkpw(password.encode("utf-8"), row["password_hash"].encode("utf-8")):
        raise AuthError("bad_credentials")
    return row["id"]
