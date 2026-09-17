"""Tests for account creation/verification and session tokens."""
import asyncio

import pytest

from webway.server.auth import AuthError, SessionStore, authenticate
from webway.server.db import Database


def run(coro):
    return asyncio.run(coro)


def test_first_use_creates_account(tmp_path):
    async def body():
        db = Database(str(tmp_path / "t.db"))
        try:
            user_id = await authenticate(db, "alice", "secret")
            row = await db.get_user_by_username("alice")
            assert row["id"] == user_id
        finally:
            db.close()
    run(body())


def test_correct_password_reuses_account(tmp_path):
    async def body():
        db = Database(str(tmp_path / "t.db"))
        try:
            first = await authenticate(db, "alice", "secret")
            second = await authenticate(db, "alice", "secret")
            assert first == second
        finally:
            db.close()
    run(body())


def test_wrong_password_is_rejected(tmp_path):
    async def body():
        db = Database(str(tmp_path / "t.db"))
        try:
            await authenticate(db, "alice", "secret")
            with pytest.raises(AuthError):
                await authenticate(db, "alice", "wrong")
        finally:
            db.close()
    run(body())


def test_session_store_issue_resolve_revoke():
    store = SessionStore()
    token = store.issue(42)
    assert store.resolve(token) == 42
    store.revoke(token)
    assert store.resolve(token) is None
