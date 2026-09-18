# Webway Textual Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single-room curses PoC (`server.py` + `client.py`) with a real multi-channel terminal chat app: an `aiohttp` server (WebSocket events + HTTP file transfer) backed by SQLite, and a new Textual client with inline image/GIF rendering.

**Architecture:** One `aiohttp` process serves `/ws` (all realtime events), `POST /upload` and `GET /files/{id}` (file transfer) over a single port, persisting users/channels/messages/reactions/files to SQLite. The client is a Textual app talking to that server over one `aiohttp.ClientSession` (WebSocket + HTTP calls), rendering images inline via `textual-image`.

**Tech Stack:** Python 3.11+, `aiohttp`, `textual`, `textual-image`, `bcrypt`, stdlib `sqlite3`/`asyncio`. No new test-only dependencies — async tests call `asyncio.run(...)` directly instead of pulling in `pytest-asyncio`.

**Spec:** `docs/superpowers/specs/2026-09-17-textual-rewrite-design.md`

## Global Constraints

- Package layout: `webway/{server,client,shared}/...`, tests under `tests/`. Replaces `server.py`/`client.py` (deleted once the new entrypoints work).
- Dependencies limited to `aiohttp`, `textual`, `textual-image`, `bcrypt` plus stdlib. Do not add `pytest-asyncio` or similar — async tests use `asyncio.run(...)`.
- File uploads capped at 15MB, enforced server-side (`webway/server/files.py`); server also caps `aiohttp.web.Application(client_max_size=...)` to match.
- Auth is implicit registration: first `username`+`password` pair seen creates the account (bcrypt-hashed); a known username with the wrong password is rejected. No email/OAuth/roles.
- Session tokens are issued on successful WebSocket auth and passed as the `X-Session-Token` header on HTTP upload calls — there is no separate login endpoint.
- Out of scope, do not build: direct messages, roles/permissions beyond "any authenticated user can create a channel", voice/video, multi-server/guilds, message editing/deletion, load/performance testing.
- `run_server.sh` / `run_client.sh` keep their current venv-bootstrap shape; only the final invoked command changes to `python3 -m webway.server` / `python3 -m webway.client`.

---

### Task 1: Project scaffolding + shared protocol module

**Files:**
- Create: `pyproject.toml`
- Create: `webway/__init__.py`, `webway/server/__init__.py`, `webway/client/__init__.py`, `webway/shared/__init__.py`
- Create: `webway/shared/protocol.py`
- Modify: `requirements.txt`
- Test: `tests/test_protocol.py`

**Interfaces:**
- Produces: `webway.shared.protocol` module with constants `MAX_TEXT_LENGTH`, `MAX_USERNAME_LENGTH`, `MAX_CHANNEL_NAME_LENGTH`, message-type constants (`C_AUTH`, `C_CHANNEL_CREATE`, `C_CHANNEL_JOIN`, `C_CHANNEL_LIST`, `C_MESSAGE_SEND`, `C_MESSAGE_ACTION`, `C_TYPING`, `C_REACTION_ADD`, `S_AUTH_OK`, `S_AUTH_ERROR`, `S_CHANNEL_LIST`, `S_CHANNEL_CREATED`, `S_HISTORY`, `S_MESSAGE`, `S_TYPING`, `S_REACTION`, `S_PRESENCE`, `S_ERROR`), exception `ProtocolError`, functions `encode(payload: dict) -> str`, `decode(raw: str) -> dict`, `require_str(payload, key, max_length) -> str`, `require_int(payload, key) -> int`. Every later task imports from this module.

- [ ] **Step 1: Create the package skeleton and pytest config**

```toml
# pyproject.toml
[tool.pytest.ini_options]
pythonpath = ["."]
```

```bash
mkdir -p webway/server webway/client/screens webway/client/widgets webway/shared tests
touch webway/__init__.py webway/server/__init__.py webway/client/__init__.py \
      webway/client/screens/__init__.py webway/client/widgets/__init__.py webway/shared/__init__.py
```

- [ ] **Step 2: Write the failing tests for the protocol module**

```python
# tests/test_protocol.py
"""Unit tests for the shared wire protocol: encoding, decoding, validation."""
import pytest

from webway.shared import protocol as p


def test_encode_decode_round_trip():
    payload = {"type": p.C_AUTH, "username": "alice", "password": "pw"}
    assert p.decode(p.encode(payload)) == payload


def test_decode_rejects_invalid_json():
    with pytest.raises(p.ProtocolError):
        p.decode("not json")


def test_decode_rejects_missing_type():
    with pytest.raises(p.ProtocolError):
        p.decode('{"username": "alice"}')


def test_require_str_trims_and_accepts():
    assert p.require_str({"name": "  general  "}, "name", 64) == "general"


def test_require_str_rejects_empty():
    with pytest.raises(p.ProtocolError):
        p.require_str({"name": "   "}, "name", 64)


def test_require_str_rejects_oversized():
    with pytest.raises(p.ProtocolError):
        p.require_str({"name": "x" * 100}, "name", 64)


def test_require_int_rejects_bool_and_non_int():
    with pytest.raises(p.ProtocolError):
        p.require_int({"channel_id": True}, "channel_id")
    with pytest.raises(p.ProtocolError):
        p.require_int({"channel_id": "1"}, "channel_id")
    assert p.require_int({"channel_id": 3}, "channel_id") == 3
```

- [ ] **Step 2b: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_protocol.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'webway.shared.protocol'` (or similar import error).

- [ ] **Step 3: Implement the protocol module**

```python
# webway/shared/protocol.py
"""Wire protocol shared between the webway server and client.

Every WebSocket frame is a single JSON object with a "type" key.
"""
from __future__ import annotations

import json
from typing import Any

MAX_TEXT_LENGTH = 2000
MAX_USERNAME_LENGTH = 32
MAX_CHANNEL_NAME_LENGTH = 64

# Client -> server
C_AUTH = "auth"
C_CHANNEL_CREATE = "channel.create"
C_CHANNEL_JOIN = "channel.join"
C_CHANNEL_LIST = "channel.list"
C_MESSAGE_SEND = "message.send"
C_MESSAGE_ACTION = "message.action"
C_TYPING = "typing"
C_REACTION_ADD = "reaction.add"

# Server -> client
S_AUTH_OK = "auth.ok"
S_AUTH_ERROR = "auth.error"
S_CHANNEL_LIST = "channel.list"
S_CHANNEL_CREATED = "channel.created"
S_HISTORY = "history"
S_MESSAGE = "message"
S_TYPING = "typing"
S_REACTION = "reaction"
S_PRESENCE = "presence"
S_ERROR = "error"


class ProtocolError(ValueError):
    """Raised when an incoming frame fails validation."""


def encode(payload: dict[str, Any]) -> str:
    return json.dumps(payload)


def decode(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"invalid JSON: {exc}") from exc
    if not isinstance(payload, dict) or "type" not in payload:
        raise ProtocolError("frame must be a JSON object with a 'type' key")
    return payload


def require_str(payload: dict[str, Any], key: str, max_length: int) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProtocolError(f"'{key}' must be a non-empty string")
    value = value.strip()
    if len(value) > max_length:
        raise ProtocolError(f"'{key}' exceeds {max_length} characters")
    return value


def require_int(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ProtocolError(f"'{key}' must be an integer")
    return value
```

- [ ] **Step 4: Update requirements.txt**

```
# requirements.txt
aiohttp
textual
textual-image
bcrypt
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pip install -r requirements.txt && python3 -m pytest tests/test_protocol.py -v`
Expected: PASS (7 tests)

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml webway requirements.txt tests/test_protocol.py
git commit -m "feat: scaffold webway package and shared wire protocol"
```

---

### Task 2: SQLite persistence layer

**Files:**
- Create: `webway/server/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: nothing (leaf module).
- Produces: `Database(path: str)` with async methods `get_user_by_username(username) -> Row|None`, `create_user(username, password_hash) -> int`, `list_channels() -> list[Row]`, `create_channel(name, topic, created_by) -> int`, `get_channel(channel_id) -> Row|None`, `create_file(uploader_id, filename, mime, size, path) -> str`, `get_file(file_id) -> Row|None`, `create_message(channel_id, user_id, mtype, text, file_id) -> int`, `get_message(message_id) -> Row|None`, `get_history(channel_id, limit=50) -> list[Row]` (rows include a joined `username`, oldest first), `add_reaction(message_id, user_id, emoji) -> bool` (False if duplicate), `get_reactions(message_id) -> list[Row]` (rows include joined `username`), and sync `close()`. Rows are `sqlite3.Row` (dict-like, `row["col"]`). Used by every server task from here on.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_db.py
"""Tests for the SQLite persistence layer."""
import asyncio
import sqlite3

import pytest

from webway.server.db import Database


def run(coro):
    return asyncio.run(coro)


def test_create_and_get_user(tmp_path):
    async def body():
        db = Database(str(tmp_path / "t.db"))
        try:
            user_id = await db.create_user("alice", "hash123")
            row = await db.get_user_by_username("alice")
            assert row["id"] == user_id
            assert row["password_hash"] == "hash123"
            assert await db.get_user_by_username("nobody") is None
        finally:
            db.close()
    run(body())


def test_username_is_unique(tmp_path):
    async def body():
        db = Database(str(tmp_path / "t.db"))
        try:
            await db.create_user("alice", "hash1")
            with pytest.raises(sqlite3.IntegrityError):
                await db.create_user("alice", "hash2")
        finally:
            db.close()
    run(body())


def test_channel_create_list_get(tmp_path):
    async def body():
        db = Database(str(tmp_path / "t.db"))
        try:
            user_id = await db.create_user("alice", "hash")
            channel_id = await db.create_channel("general", "chit chat", user_id)
            rows = await db.list_channels()
            assert [r["name"] for r in rows] == ["general"]
            row = await db.get_channel(channel_id)
            assert row["topic"] == "chit chat"
            assert await db.get_channel(9999) is None
        finally:
            db.close()
    run(body())


def test_message_history_and_get(tmp_path):
    async def body():
        db = Database(str(tmp_path / "t.db"))
        try:
            user_id = await db.create_user("alice", "hash")
            channel_id = await db.create_channel("general", "", user_id)
            id1 = await db.create_message(channel_id, user_id, "msg", "hi", None)
            id2 = await db.create_message(channel_id, user_id, "msg", "there", None)
            history = await db.get_history(channel_id, limit=10)
            assert [r["id"] for r in history] == [id1, id2]
            assert history[0]["username"] == "alice"
            row = await db.get_message(id1)
            assert row["channel_id"] == channel_id
            assert await db.get_message(9999) is None
        finally:
            db.close()
    run(body())


def test_files_round_trip(tmp_path):
    async def body():
        db = Database(str(tmp_path / "t.db"))
        try:
            user_id = await db.create_user("alice", "hash")
            file_id = await db.create_file(user_id, "cat.png", "image/png", 1234, "/tmp/cat.png")
            row = await db.get_file(file_id)
            assert row["filename"] == "cat.png"
            assert row["size"] == 1234
            assert await db.get_file("does-not-exist") is None
        finally:
            db.close()
    run(body())


def test_reactions_are_deduplicated_per_user_emoji(tmp_path):
    async def body():
        db = Database(str(tmp_path / "t.db"))
        try:
            user_id = await db.create_user("alice", "hash")
            channel_id = await db.create_channel("general", "", user_id)
            message_id = await db.create_message(channel_id, user_id, "msg", "hi", None)
            assert await db.add_reaction(message_id, user_id, "⭐") is True
            assert await db.add_reaction(message_id, user_id, "⭐") is False
            rows = await db.get_reactions(message_id)
            assert len(rows) == 1
            assert rows[0]["username"] == "alice"
        finally:
            db.close()
    run(body())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'webway.server.db'`

- [ ] **Step 3: Implement the persistence layer**

```python
# webway/server/db.py
"""SQLite persistence for webway: users, channels, messages, reactions, files."""
from __future__ import annotations

import asyncio
import sqlite3
import time
import uuid

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    topic TEXT NOT NULL DEFAULT '',
    created_by INTEGER NOT NULL REFERENCES users(id),
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS files (
    id TEXT PRIMARY KEY,
    uploader_id INTEGER NOT NULL REFERENCES users(id),
    filename TEXT NOT NULL,
    mime TEXT NOT NULL,
    size INTEGER NOT NULL,
    path TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id INTEGER NOT NULL REFERENCES channels(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    type TEXT NOT NULL,
    text TEXT NOT NULL,
    file_id TEXT REFERENCES files(id),
    ts REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS reactions (
    message_id INTEGER NOT NULL REFERENCES messages(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    emoji TEXT NOT NULL,
    UNIQUE(message_id, user_id, emoji)
);
"""


class Database:
    """Async-friendly wrapper around a single sqlite3 connection.

    sqlite3 calls are synchronous; each public method runs its query in a
    worker thread via asyncio.to_thread so the event loop is never blocked.
    """

    def __init__(self, path: str):
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # --- users ---

    async def get_user_by_username(self, username: str) -> sqlite3.Row | None:
        return await asyncio.to_thread(self._get_user_by_username, username)

    def _get_user_by_username(self, username: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()

    async def create_user(self, username: str, password_hash: str) -> int:
        return await asyncio.to_thread(self._create_user, username, password_hash)

    def _create_user(self, username: str, password_hash: str) -> int:
        cur = self._conn.execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            (username, password_hash, time.time()),
        )
        self._conn.commit()
        return cur.lastrowid

    # --- channels ---

    async def list_channels(self) -> list[sqlite3.Row]:
        return await asyncio.to_thread(self._list_channels)

    def _list_channels(self) -> list[sqlite3.Row]:
        return self._conn.execute("SELECT * FROM channels ORDER BY name").fetchall()

    async def create_channel(self, name: str, topic: str, created_by: int) -> int:
        return await asyncio.to_thread(self._create_channel, name, topic, created_by)

    def _create_channel(self, name: str, topic: str, created_by: int) -> int:
        cur = self._conn.execute(
            "INSERT INTO channels (name, topic, created_by, created_at) VALUES (?, ?, ?, ?)",
            (name, topic, created_by, time.time()),
        )
        self._conn.commit()
        return cur.lastrowid

    async def get_channel(self, channel_id: int) -> sqlite3.Row | None:
        return await asyncio.to_thread(self._get_channel, channel_id)

    def _get_channel(self, channel_id: int) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM channels WHERE id = ?", (channel_id,)
        ).fetchone()

    # --- files ---

    async def create_file(self, uploader_id: int, filename: str, mime: str, size: int, path: str) -> str:
        file_id = uuid.uuid4().hex
        await asyncio.to_thread(self._create_file, file_id, uploader_id, filename, mime, size, path)
        return file_id

    def _create_file(self, file_id, uploader_id, filename, mime, size, path) -> None:
        self._conn.execute(
            "INSERT INTO files (id, uploader_id, filename, mime, size, path, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (file_id, uploader_id, filename, mime, size, path, time.time()),
        )
        self._conn.commit()

    async def get_file(self, file_id: str) -> sqlite3.Row | None:
        return await asyncio.to_thread(self._get_file, file_id)

    def _get_file(self, file_id: str) -> sqlite3.Row | None:
        return self._conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()

    # --- messages ---

    async def create_message(self, channel_id: int, user_id: int, mtype: str, text: str, file_id: str | None) -> int:
        return await asyncio.to_thread(self._create_message, channel_id, user_id, mtype, text, file_id)

    def _create_message(self, channel_id, user_id, mtype, text, file_id) -> int:
        cur = self._conn.execute(
            "INSERT INTO messages (channel_id, user_id, type, text, file_id, ts) VALUES (?, ?, ?, ?, ?, ?)",
            (channel_id, user_id, mtype, text, file_id, time.time()),
        )
        self._conn.commit()
        return cur.lastrowid

    async def get_message(self, message_id: int) -> sqlite3.Row | None:
        return await asyncio.to_thread(self._get_message, message_id)

    def _get_message(self, message_id: int) -> sqlite3.Row | None:
        return self._conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()

    async def get_history(self, channel_id: int, limit: int = 50) -> list[sqlite3.Row]:
        return await asyncio.to_thread(self._get_history, channel_id, limit)

    def _get_history(self, channel_id: int, limit: int) -> list[sqlite3.Row]:
        rows = self._conn.execute(
            "SELECT m.*, u.username FROM messages m "
            "JOIN users u ON u.id = m.user_id "
            "WHERE m.channel_id = ? ORDER BY m.id DESC LIMIT ?",
            (channel_id, limit),
        ).fetchall()
        return list(reversed(rows))

    # --- reactions ---

    async def add_reaction(self, message_id: int, user_id: int, emoji: str) -> bool:
        return await asyncio.to_thread(self._add_reaction, message_id, user_id, emoji)

    def _add_reaction(self, message_id: int, user_id: int, emoji: str) -> bool:
        try:
            self._conn.execute(
                "INSERT INTO reactions (message_id, user_id, emoji) VALUES (?, ?, ?)",
                (message_id, user_id, emoji),
            )
            self._conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    async def get_reactions(self, message_id: int) -> list[sqlite3.Row]:
        return await asyncio.to_thread(self._get_reactions, message_id)

    def _get_reactions(self, message_id: int) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT r.*, u.username FROM reactions r JOIN users u ON u.id = r.user_id WHERE message_id = ?",
            (message_id,),
        ).fetchall()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_db.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add webway/server/db.py tests/test_db.py
git commit -m "feat: add SQLite persistence layer for users/channels/messages/files/reactions"
```

---

### Task 3: Auth (account creation/verification, session tokens)

**Files:**
- Create: `webway/server/auth.py`
- Test: `tests/test_auth.py`

**Interfaces:**
- Consumes: `webway.server.db.Database` (Task 2) — `get_user_by_username`, `create_user`.
- Produces: `AuthError(Exception)`, `async authenticate(db: Database, username: str, password: str) -> int` (returns user id, creates account on first use, raises `AuthError` on wrong password), `SessionStore` with `issue(user_id: int) -> str`, `resolve(token: str) -> int | None`, `revoke(token: str) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_auth.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_auth.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'webway.server.auth'`

- [ ] **Step 3: Implement auth**

```python
# webway/server/auth.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_auth.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add webway/server/auth.py tests/test_auth.py
git commit -m "feat: add implicit-registration auth and session tokens"
```

---

### Task 4: Channel subscription/broadcast registry

**Files:**
- Create: `webway/server/channels.py`
- Test: `tests/test_channels.py`

**Interfaces:**
- Consumes: `webway.shared.protocol.encode` (Task 1).
- Produces: `Connection` (Protocol: `.closed: bool`, `async .send_str(data: str)`), `ChannelRegistry` with `register(ws, username)`, `unregister(ws)`, `subscribe(channel_id, ws, username)`, `unsubscribe_all(ws) -> list[int]`, `members(channel_id) -> list[str]` (sorted), `connections(channel_id) -> list[Connection]`, `async broadcast(channel_id, payload: dict)`, `async broadcast_global(payload: dict)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_channels.py
"""Tests for in-memory channel subscription and broadcast bookkeeping."""
import asyncio
import json

from webway.server.channels import ChannelRegistry


class FakeConnection:
    def __init__(self):
        self.closed = False
        self.sent: list[str] = []

    async def send_str(self, data: str) -> None:
        self.sent.append(data)


def run(coro):
    return asyncio.run(coro)


def test_members_returns_sorted_usernames():
    registry = ChannelRegistry()
    registry.subscribe(1, FakeConnection(), "bob")
    registry.subscribe(1, FakeConnection(), "alice")
    assert registry.members(1) == ["alice", "bob"]


def test_broadcast_reaches_subscribers_only():
    registry = ChannelRegistry()
    a, b = FakeConnection(), FakeConnection()
    registry.subscribe(1, a, "alice")
    registry.subscribe(2, b, "bob")
    run(registry.broadcast(1, {"type": "message", "text": "hi"}))
    assert len(a.sent) == 1
    assert json.loads(a.sent[0])["text"] == "hi"
    assert b.sent == []


def test_broadcast_skips_closed_connections():
    registry = ChannelRegistry()
    a = FakeConnection()
    a.closed = True
    registry.subscribe(1, a, "alice")
    run(registry.broadcast(1, {"type": "message"}))
    assert a.sent == []


def test_unsubscribe_all_returns_affected_channels_and_removes_membership():
    registry = ChannelRegistry()
    ws = FakeConnection()
    registry.subscribe(1, ws, "alice")
    registry.subscribe(2, ws, "alice")
    affected = registry.unsubscribe_all(ws)
    assert sorted(affected) == [1, 2]
    assert registry.members(1) == []
    assert registry.members(2) == []


def test_broadcast_global_reaches_all_registered_connections():
    registry = ChannelRegistry()
    a, b = FakeConnection(), FakeConnection()
    registry.register(a, "alice")
    registry.register(b, "bob")
    run(registry.broadcast_global({"type": "channel.created", "name": "general"}))
    assert len(a.sent) == 1
    assert len(b.sent) == 1
    registry.unregister(a)
    run(registry.broadcast_global({"type": "channel.created", "name": "random"}))
    assert len(a.sent) == 1
    assert len(b.sent) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_channels.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'webway.server.channels'`

- [ ] **Step 3: Implement the registry**

```python
# webway/server/channels.py
"""In-memory channel subscription and broadcast bookkeeping.

Channel rows themselves live in SQLite (see db.py); this module only
tracks which live WebSocket connections are subscribed to which channel,
for broadcast and presence purposes.
"""
from __future__ import annotations

from typing import Protocol

from webway.shared.protocol import encode


class Connection(Protocol):
    closed: bool

    async def send_str(self, data: str) -> None: ...


class ChannelRegistry:
    def __init__(self):
        self._subscribers: dict[int, dict[Connection, str]] = {}
        self._all_connections: dict[Connection, str] = {}

    def register(self, ws: Connection, username: str) -> None:
        self._all_connections[ws] = username

    def unregister(self, ws: Connection) -> None:
        self._all_connections.pop(ws, None)

    def subscribe(self, channel_id: int, ws: Connection, username: str) -> None:
        self._subscribers.setdefault(channel_id, {})[ws] = username

    def unsubscribe_all(self, ws: Connection) -> list[int]:
        affected = []
        for channel_id, members in self._subscribers.items():
            if ws in members:
                del members[ws]
                affected.append(channel_id)
        return affected

    def members(self, channel_id: int) -> list[str]:
        return sorted(self._subscribers.get(channel_id, {}).values())

    def connections(self, channel_id: int) -> list[Connection]:
        return list(self._subscribers.get(channel_id, {}).keys())

    async def broadcast(self, channel_id: int, payload: dict) -> None:
        message = encode(payload)
        for ws in self.connections(channel_id):
            if not ws.closed:
                await ws.send_str(message)

    async def broadcast_global(self, payload: dict) -> None:
        message = encode(payload)
        for ws in list(self._all_connections):
            if not ws.closed:
                await ws.send_str(message)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_channels.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add webway/server/channels.py tests/test_channels.py
git commit -m "feat: add in-memory channel subscription and broadcast registry"
```

---

### Task 5: aiohttp app + WebSocket protocol handler

**Files:**
- Create: `webway/server/app.py`
- Create: `webway/server/ws_protocol.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `Database` (Task 2), `authenticate`/`AuthError`/`SessionStore` (Task 3), `ChannelRegistry` (Task 4), `webway.shared.protocol` (Task 1).
- Produces: `create_app(db_path: str, upload_dir: str) -> aiohttp.web.Application` with `app["db"]`, `app["sessions"]`, `app["channels"]`, `app["upload_dir"]` set, routes `GET /ws` wired to `websocket_handler`; `main()` CLI entrypoint. `websocket_handler(request) -> web.WebSocketResponse` implementing the full client->server protocol from the spec except file upload/download (Task 6 adds those routes to the same app). Wire message envelope for `S_MESSAGE` uses key `message_type` (not `type`) to carry `"msg"`/`"action"`, since `type` is reserved for the envelope's routing value (`"message"`) — every later task that reads a message payload must use `message_type` for msg-vs-action.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_server.py
"""Integration tests for the webway aiohttp server: auth, channels, messages."""
import json
import os
import tempfile

from aiohttp.test_utils import AioHTTPTestCase
from aiohttp import web

from webway.server.app import create_app
from webway.shared import protocol as p


class ServerTestCase(AioHTTPTestCase):
    async def get_application(self) -> web.Application:
        self.tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(self.tmpdir, "test.db")
        upload_dir = os.path.join(self.tmpdir, "uploads")
        return create_app(db_path, upload_dir)

    async def _auth(self, ws, username, password="pw"):
        await ws.send_str(p.encode({"type": p.C_AUTH, "username": username, "password": password}))
        return await self._receive_until(ws, p.S_AUTH_OK) if False else json.loads(await ws.receive_str())

    async def _receive_until(self, ws, msg_type):
        while True:
            payload = json.loads(await ws.receive_str())
            if payload["type"] == msg_type:
                return payload

    async def test_auth_creates_account_on_first_use(self):
        async with self.client.ws_connect("/ws") as ws:
            reply = await self._auth(ws, "alice")
            self.assertEqual(reply["type"], p.S_AUTH_OK)
            self.assertEqual(reply["username"], "alice")

    async def test_auth_rejects_wrong_password(self):
        async with self.client.ws_connect("/ws") as ws:
            await self._auth(ws, "bob", "correct")
        async with self.client.ws_connect("/ws") as ws:
            reply = await self._auth(ws, "bob", "wrong")
            self.assertEqual(reply["type"], p.S_AUTH_ERROR)

    async def test_channel_create_join_and_message_broadcast(self):
        async with self.client.ws_connect("/ws") as ws1, self.client.ws_connect("/ws") as ws2:
            await self._auth(ws1, "alice")
            await self._receive_until(ws1, p.S_CHANNEL_LIST)
            await self._auth(ws2, "bob")
            await self._receive_until(ws2, p.S_CHANNEL_LIST)

            await ws1.send_str(p.encode({"type": p.C_CHANNEL_CREATE, "name": "general", "topic": "chat"}))
            created = await self._receive_until(ws1, p.S_CHANNEL_CREATED)
            await self._receive_until(ws2, p.S_CHANNEL_CREATED)
            channel_id = created["id"]

            await ws1.send_str(p.encode({"type": p.C_CHANNEL_JOIN, "channel_id": channel_id}))
            history = await self._receive_until(ws1, p.S_HISTORY)
            self.assertEqual(history["items"], [])

            await ws2.send_str(p.encode({"type": p.C_CHANNEL_JOIN, "channel_id": channel_id}))
            await self._receive_until(ws2, p.S_HISTORY)

            await ws1.send_str(p.encode({"type": p.C_MESSAGE_SEND, "channel_id": channel_id, "text": "hi bob"}))
            msg1 = await self._receive_until(ws1, p.S_MESSAGE)
            msg2 = await self._receive_until(ws2, p.S_MESSAGE)
            self.assertEqual(msg1["text"], "hi bob")
            self.assertEqual(msg2["message_type"], "msg")
            self.assertEqual(msg2["username"], "alice")

    async def test_reaction_is_broadcast_to_channel(self):
        async with self.client.ws_connect("/ws") as ws1, self.client.ws_connect("/ws") as ws2:
            await self._auth(ws1, "alice")
            await self._receive_until(ws1, p.S_CHANNEL_LIST)
            await self._auth(ws2, "bob")
            await self._receive_until(ws2, p.S_CHANNEL_LIST)

            await ws1.send_str(p.encode({"type": p.C_CHANNEL_CREATE, "name": "general", "topic": ""}))
            created = await self._receive_until(ws1, p.S_CHANNEL_CREATED)
            await self._receive_until(ws2, p.S_CHANNEL_CREATED)
            channel_id = created["id"]

            await ws1.send_str(p.encode({"type": p.C_CHANNEL_JOIN, "channel_id": channel_id}))
            await self._receive_until(ws1, p.S_HISTORY)
            await ws2.send_str(p.encode({"type": p.C_CHANNEL_JOIN, "channel_id": channel_id}))
            await self._receive_until(ws2, p.S_HISTORY)

            await ws1.send_str(p.encode({"type": p.C_MESSAGE_SEND, "channel_id": channel_id, "text": "hi"}))
            msg = await self._receive_until(ws2, p.S_MESSAGE)

            await ws2.send_str(p.encode({"type": p.C_REACTION_ADD, "message_id": msg["id"], "emoji": "⭐"}))
            reaction = await self._receive_until(ws1, p.S_REACTION)
            self.assertEqual(reaction["message_id"], msg["id"])
            self.assertEqual(reaction["username"], "bob")

    async def test_unauthenticated_message_is_rejected(self):
        async with self.client.ws_connect("/ws") as ws:
            await ws.send_str(p.encode({"type": p.C_MESSAGE_SEND, "channel_id": 1, "text": "hi"}))
            reply = json.loads(await ws.receive_str())
            self.assertEqual(reply["type"], p.S_ERROR)
            self.assertEqual(reply["reason"], "not_authenticated")
```

Remove the dead `if False else` in `_auth` before running — it was left in accidentally; the helper should just be:

```python
    async def _auth(self, ws, username, password="pw"):
        await ws.send_str(p.encode({"type": p.C_AUTH, "username": username, "password": password}))
        return json.loads(await ws.receive_str())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_server.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'webway.server.app'`

- [ ] **Step 3: Implement the WebSocket protocol handler**

```python
# webway/server/ws_protocol.py
"""Per-connection WebSocket message handling."""
from __future__ import annotations

import logging
import time

from aiohttp import web

from webway.server.auth import AuthError, authenticate
from webway.shared import protocol as p

logger = logging.getLogger("webway.server.ws")

HISTORY_LIMIT = 50


def _file_meta_dict(row) -> dict:
    return {
        "id": row["id"],
        "filename": row["filename"],
        "mime": row["mime"],
        "size": row["size"],
        "url": f"/files/{row['id']}",
    }


async def _build_history_items(db, rows) -> list[dict]:
    items = []
    for row in rows:
        file_meta = await db.get_file(row["file_id"]) if row["file_id"] else None
        reaction_rows = await db.get_reactions(row["id"])
        items.append({
            "id": row["id"],
            "channel_id": row["channel_id"],
            "user_id": row["user_id"],
            "username": row["username"],
            "message_type": row["type"],
            "text": row["text"],
            "ts": row["ts"],
            "file": _file_meta_dict(file_meta) if file_meta else None,
            "reactions": [{"emoji": r["emoji"], "username": r["username"]} for r in reaction_rows],
        })
    return items


async def websocket_handler(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    db = request.app["db"]
    sessions = request.app["sessions"]
    channels = request.app["channels"]

    user_id: int | None = None
    username: str | None = None

    async for msg in ws:
        if msg.type != web.WSMsgType.TEXT:
            continue
        try:
            payload = p.decode(msg.data)
        except p.ProtocolError as exc:
            logger.warning("dropped malformed frame: %s", exc)
            continue

        mtype = payload["type"]

        if mtype == p.C_AUTH:
            try:
                uname = p.require_str(payload, "username", p.MAX_USERNAME_LENGTH)
                password = payload.get("password")
                if not isinstance(password, str) or not password:
                    raise p.ProtocolError("'password' must be a non-empty string")
                user_id = await authenticate(db, uname, password)
                username = uname
                token = sessions.issue(user_id)
                channels.register(ws, username)
                await ws.send_str(p.encode({
                    "type": p.S_AUTH_OK, "user_id": user_id, "username": username, "session_token": token,
                }))
                rows = await db.list_channels()
                await ws.send_str(p.encode({
                    "type": p.S_CHANNEL_LIST,
                    "channels": [{"id": r["id"], "name": r["name"], "topic": r["topic"]} for r in rows],
                }))
            except (p.ProtocolError, AuthError) as exc:
                await ws.send_str(p.encode({"type": p.S_AUTH_ERROR, "reason": str(exc)}))
            continue

        if user_id is None:
            await ws.send_str(p.encode({"type": p.S_ERROR, "reason": "not_authenticated"}))
            continue

        try:
            if mtype == p.C_CHANNEL_LIST:
                rows = await db.list_channels()
                await ws.send_str(p.encode({
                    "type": p.S_CHANNEL_LIST,
                    "channels": [{"id": r["id"], "name": r["name"], "topic": r["topic"]} for r in rows],
                }))

            elif mtype == p.C_CHANNEL_CREATE:
                name = p.require_str(payload, "name", p.MAX_CHANNEL_NAME_LENGTH)
                topic = str(payload.get("topic", ""))[:200]
                channel_id = await db.create_channel(name, topic, user_id)
                await channels.broadcast_global({
                    "type": p.S_CHANNEL_CREATED, "id": channel_id, "name": name, "topic": topic,
                })

            elif mtype == p.C_CHANNEL_JOIN:
                channel_id = p.require_int(payload, "channel_id")
                channel = await db.get_channel(channel_id)
                if channel is None:
                    await ws.send_str(p.encode({"type": p.S_ERROR, "reason": "no_such_channel"}))
                    continue
                channels.subscribe(channel_id, ws, username)
                history_rows = await db.get_history(channel_id, HISTORY_LIMIT)
                items = await _build_history_items(db, history_rows)
                await ws.send_str(p.encode({"type": p.S_HISTORY, "channel_id": channel_id, "items": items}))
                await channels.broadcast(channel_id, {
                    "type": p.S_PRESENCE, "channel_id": channel_id, "users": channels.members(channel_id),
                })

            elif mtype in (p.C_MESSAGE_SEND, p.C_MESSAGE_ACTION):
                channel_id = p.require_int(payload, "channel_id")
                text = p.require_str(payload, "text", p.MAX_TEXT_LENGTH)
                file_id = payload.get("file_id")
                msg_type = "action" if mtype == p.C_MESSAGE_ACTION else "msg"
                message_id = await db.create_message(channel_id, user_id, msg_type, text, file_id)
                file_row = await db.get_file(file_id) if file_id else None
                await channels.broadcast(channel_id, {
                    "type": p.S_MESSAGE, "id": message_id, "channel_id": channel_id,
                    "user_id": user_id, "username": username, "message_type": msg_type, "text": text,
                    "ts": time.time(), "file": _file_meta_dict(file_row) if file_row else None,
                })

            elif mtype == p.C_TYPING:
                channel_id = p.require_int(payload, "channel_id")
                state = bool(payload.get("state"))
                await channels.broadcast(channel_id, {
                    "type": p.S_TYPING, "channel_id": channel_id, "username": username, "state": state,
                })

            elif mtype == p.C_REACTION_ADD:
                message_id = p.require_int(payload, "message_id")
                emoji = p.require_str(payload, "emoji", 8)
                message_row = await db.get_message(message_id)
                if message_row is None:
                    await ws.send_str(p.encode({"type": p.S_ERROR, "reason": "no_such_message"}))
                    continue
                added = await db.add_reaction(message_id, user_id, emoji)
                if added:
                    await channels.broadcast(message_row["channel_id"], {
                        "type": p.S_REACTION, "message_id": message_id, "emoji": emoji, "username": username,
                    })

        except p.ProtocolError as exc:
            await ws.send_str(p.encode({"type": p.S_ERROR, "reason": str(exc)}))

    if username is not None:
        channels.unregister(ws)
        affected = channels.unsubscribe_all(ws)
        for channel_id in affected:
            await channels.broadcast(channel_id, {
                "type": p.S_PRESENCE, "channel_id": channel_id, "users": channels.members(channel_id),
            })

    return ws
```

- [ ] **Step 4: Implement the aiohttp app wiring**

```python
# webway/server/app.py
"""aiohttp application wiring for the webway server."""
from __future__ import annotations

import argparse
import logging
import os

from aiohttp import web

from webway.server.auth import SessionStore
from webway.server.channels import ChannelRegistry
from webway.server.db import Database
from webway.server.ws_protocol import websocket_handler

DEFAULT_PORT = 5555
DEFAULT_DB_PATH = "webway.db"
UPLOAD_DIR = "uploads"


def create_app(db_path: str = DEFAULT_DB_PATH, upload_dir: str = UPLOAD_DIR) -> web.Application:
    app = web.Application(client_max_size=20 * 1024 * 1024)
    app["db"] = Database(db_path)
    app["sessions"] = SessionStore()
    app["channels"] = ChannelRegistry()
    app["upload_dir"] = upload_dir
    os.makedirs(upload_dir, exist_ok=True)

    app.router.add_get("/ws", websocket_handler)

    app.on_cleanup.append(_on_cleanup)
    return app


async def _on_cleanup(app: web.Application) -> None:
    app["db"].close()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("port", nargs="?", type=int, default=DEFAULT_PORT)
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--uploads", default=UPLOAD_DIR)
    args = parser.parse_args()

    app = create_app(args.db, args.uploads)
    web.run_app(app, host="0.0.0.0", port=args.port)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_server.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Commit**

```bash
git add webway/server/app.py webway/server/ws_protocol.py tests/test_server.py
git commit -m "feat: add aiohttp app and WebSocket protocol handler"
```

---

### Task 6: HTTP file upload/download

**Files:**
- Create: `webway/server/files.py`
- Modify: `webway/server/app.py` (register the two new routes)
- Test: `tests/test_files.py`

**Interfaces:**
- Consumes: `app["db"]`, `app["sessions"]`, `app["upload_dir"]` (Task 5).
- Produces: `handle_upload(request) -> web.Response` (JSON `{file_id, url}` on success, `401`/`400`/`413` on failure), `handle_download(request) -> web.StreamResponse` (`404` if unknown), `MAX_UPLOAD_SIZE` constant (15MB). Routed at `POST /upload` and `GET /files/{file_id}`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_files.py
"""Tests for the HTTP file upload/download endpoints."""
import os
import tempfile

from aiohttp import FormData
from aiohttp.test_utils import AioHTTPTestCase
from aiohttp import web

from webway.server import files as files_module
from webway.server.app import create_app
from webway.shared import protocol as p


class FilesTestCase(AioHTTPTestCase):
    async def get_application(self) -> web.Application:
        self.tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(self.tmpdir, "test.db")
        upload_dir = os.path.join(self.tmpdir, "uploads")
        return create_app(db_path, upload_dir)

    async def _session_token(self, username="alice"):
        async with self.client.ws_connect("/ws") as ws:
            await ws.send_str(p.encode({"type": p.C_AUTH, "username": username, "password": "pw"}))
            import json
            reply = json.loads(await ws.receive_str())
            return reply["session_token"]

    async def test_upload_without_token_is_rejected(self):
        data = FormData()
        data.add_field("file", b"hello", filename="hello.txt", content_type="text/plain")
        resp = await self.client.post("/upload", data=data)
        self.assertEqual(resp.status, 401)

    async def test_upload_and_download_round_trip(self):
        token = await self._session_token()
        data = FormData()
        data.add_field("file", b"hello world", filename="hello.txt", content_type="text/plain")
        resp = await self.client.post("/upload", data=data, headers={"X-Session-Token": token})
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertIn("file_id", body)

        download = await self.client.get(f"/files/{body['file_id']}")
        self.assertEqual(download.status, 200)
        content = await download.read()
        self.assertEqual(content, b"hello world")

    async def test_download_unknown_file_is_404(self):
        resp = await self.client.get("/files/does-not-exist")
        self.assertEqual(resp.status, 404)

    async def test_upload_over_size_limit_is_rejected(self):
        original = files_module.MAX_UPLOAD_SIZE
        files_module.MAX_UPLOAD_SIZE = 4
        try:
            token = await self._session_token()
            data = FormData()
            data.add_field("file", b"this is too big", filename="big.bin", content_type="application/octet-stream")
            resp = await self.client.post("/upload", data=data, headers={"X-Session-Token": token})
            self.assertEqual(resp.status, 413)
        finally:
            files_module.MAX_UPLOAD_SIZE = original
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_files.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'webway.server.files'`

- [ ] **Step 3: Implement upload/download handlers**

```python
# webway/server/files.py
"""HTTP handlers for file upload and download."""
from __future__ import annotations

import os
import uuid

from aiohttp import web

MAX_UPLOAD_SIZE = 15 * 1024 * 1024


async def handle_upload(request: web.Request) -> web.Response:
    token = request.headers.get("X-Session-Token")
    sessions = request.app["sessions"]
    user_id = sessions.resolve(token) if token else None
    if user_id is None:
        return web.json_response({"reason": "not_authenticated"}, status=401)

    reader = await request.multipart()
    field = await reader.next()
    if field is None or field.name != "file":
        return web.json_response({"reason": "missing_file_field"}, status=400)

    filename = field.filename or "upload.bin"
    mime = field.headers.get("Content-Type", "application/octet-stream")

    upload_dir = request.app["upload_dir"]
    disk_path = os.path.join(upload_dir, uuid.uuid4().hex)

    size = 0
    with open(disk_path, "wb") as fh:
        while True:
            chunk = await field.read_chunk()
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_UPLOAD_SIZE:
                fh.close()
                os.remove(disk_path)
                return web.json_response({"reason": "file_too_large"}, status=413)
            fh.write(chunk)

    db = request.app["db"]
    file_id = await db.create_file(user_id, filename, mime, size, disk_path)
    return web.json_response({"file_id": file_id, "url": f"/files/{file_id}"})


async def handle_download(request: web.Request) -> web.StreamResponse:
    file_id = request.match_info["file_id"]
    db = request.app["db"]
    row = await db.get_file(file_id)
    if row is None:
        return web.json_response({"reason": "no_such_file"}, status=404)
    return web.FileResponse(
        path=row["path"],
        headers={
            "Content-Type": row["mime"] or "application/octet-stream",
            "Content-Disposition": f'inline; filename="{row["filename"]}"',
        },
    )
```

- [ ] **Step 4: Register the routes in app.py**

```python
# webway/server/app.py — modify create_app
from webway.server.files import handle_download, handle_upload  # add to imports

# inside create_app, after app.router.add_get("/ws", websocket_handler):
    app.router.add_post("/upload", handle_upload)
    app.router.add_get("/files/{file_id}", handle_download)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_files.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add webway/server/files.py webway/server/app.py tests/test_files.py
git commit -m "feat: add HTTP file upload/download endpoints"
```

---

### Task 7: Server entrypoint wiring and script update

**Files:**
- Modify: `run_server.sh`
- Delete: `server.py`, `__pycache__/server.cpython-314.pyc`

**Interfaces:**
- Consumes: `webway.server.app.main` (Task 5).
- Produces: `run_server.sh` invoking `python3 -m webway.server`.

- [ ] **Step 1: Update run_server.sh**

```bash
# run_server.sh
#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi

source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt

python3 -m webway.server "$@"
```

- [ ] **Step 2: Remove the old flat server script**

```bash
git rm server.py
rm -rf __pycache__
```

- [ ] **Step 3: Manually verify the server boots**

Run: `./run_server.sh 5599 &` then `sleep 1 && curl -sf http://127.0.0.1:5599/ws -H "Connection: Upgrade" -H "Upgrade: websocket" -H "Sec-WebSocket-Version: 13" -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" -o /dev/null -w "%{http_code}\n"; kill %1`
Expected: prints `101` (WebSocket upgrade accepted), server process exits cleanly on `kill`.

- [ ] **Step 4: Commit**

```bash
git add run_server.sh
git commit -m "chore: point run_server.sh at the new webway.server entrypoint"
```

---

### Task 8: Client networking layer

**Files:**
- Create: `webway/client/net.py`
- Test: `tests/test_net.py`

**Interfaces:**
- Consumes: `webway.shared.protocol` (Task 1), `webway.server.app.create_app` (Task 5, test-only, to stand up a real server to test against).
- Produces: `WebwayClient(base_url: str)` with `async open()`, `async close()`, `session_token: str | None` attribute, `async send(payload: dict)`, `async messages()` (async generator yielding decoded frames), `async upload_file(path: str) -> dict`, `async download_file(file_id: str, dest_path: str) -> None`. Also `async def backoff_delays()` (async generator yielding `1, 2, 4, 8, 16, 30, 30, ...`) for the client's reconnect loop (Task 12 consumes it).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_net.py
"""Tests for the client transport wrapper, against a real (test) webway server."""
import asyncio
import os
import tempfile

from aiohttp.test_utils import TestClient, TestServer

from webway.client.net import WebwayClient, backoff_delays
from webway.server.app import create_app
from webway.shared import protocol as p


async def _start_test_server():
    tmpdir = tempfile.mkdtemp()
    app = create_app(os.path.join(tmpdir, "test.db"), os.path.join(tmpdir, "uploads"))
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    return client, tmpdir


def test_auth_round_trip():
    async def run():
        client, _ = await _start_test_server()
        try:
            wc = WebwayClient(str(client.make_url("")))
            await wc.open()
            await wc.send({"type": p.C_AUTH, "username": "alice", "password": "pw"})
            reply = await anext(wc.messages())
            assert reply["type"] == p.S_AUTH_OK
            assert reply["username"] == "alice"
            await wc.close()
        finally:
            await client.close()
    asyncio.run(run())


def test_upload_and_download_round_trip():
    async def run():
        client, tmpdir = await _start_test_server()
        try:
            wc = WebwayClient(str(client.make_url("")))
            await wc.open()
            await wc.send({"type": p.C_AUTH, "username": "alice", "password": "pw"})
            auth_reply = await anext(wc.messages())
            wc.session_token = auth_reply["session_token"]

            src_path = os.path.join(tmpdir, "hello.txt")
            with open(src_path, "wb") as fh:
                fh.write(b"hello world")

            result = await wc.upload_file(src_path)
            assert "file_id" in result

            dest_path = os.path.join(tmpdir, "downloaded.txt")
            await wc.download_file(result["file_id"], dest_path)
            with open(dest_path, "rb") as fh:
                assert fh.read() == b"hello world"

            await wc.close()
        finally:
            await client.close()
    asyncio.run(run())


def test_backoff_delays_grow_and_cap():
    async def run():
        delays = []
        gen = backoff_delays()
        for _ in range(6):
            delays.append(await anext(gen))
        assert delays == [1, 2, 4, 8, 16, 30]
    asyncio.run(run())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_net.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'webway.client.net'`

- [ ] **Step 3: Implement the networking layer**

```python
# webway/client/net.py
"""Async transport wrapper: WebSocket for events, HTTP for file transfer."""
from __future__ import annotations

import os

import aiohttp

from webway.shared import protocol


class WebwayClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.session: aiohttp.ClientSession | None = None
        self.ws: aiohttp.ClientWebSocketResponse | None = None
        self.session_token: str | None = None

    async def open(self) -> None:
        self.session = aiohttp.ClientSession()
        self.ws = await self.session.ws_connect(f"{self.base_url}/ws")

    async def close(self) -> None:
        if self.ws is not None:
            await self.ws.close()
        if self.session is not None:
            await self.session.close()

    async def send(self, payload: dict) -> None:
        await self.ws.send_str(protocol.encode(payload))

    async def messages(self):
        async for msg in self.ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                yield protocol.decode(msg.data)

    async def upload_file(self, path: str) -> dict:
        data = aiohttp.FormData()
        with open(path, "rb") as fh:
            data.add_field("file", fh.read(), filename=os.path.basename(path))
        headers = {"X-Session-Token": self.session_token} if self.session_token else {}
        async with self.session.post(f"{self.base_url}/upload", data=data, headers=headers) as resp:
            return await resp.json()

    async def download_file(self, file_id: str, dest_path: str) -> None:
        async with self.session.get(f"{self.base_url}/files/{file_id}") as resp:
            resp.raise_for_status()
            with open(dest_path, "wb") as fh:
                async for chunk in resp.content.iter_chunked(65536):
                    fh.write(chunk)


async def backoff_delays():
    """Yields reconnect delays in seconds: 1, 2, 4, 8, 16, 30, 30, ..."""
    delay = 1
    while True:
        yield delay
        delay = min(delay * 2, 30)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_net.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add webway/client/net.py tests/test_net.py
git commit -m "feat: add client WebSocket/HTTP transport wrapper"
```

---

### Task 9: Textual login screen

**Files:**
- Create: `webway/client/screens/login.py`
- Test: `tests/test_login_screen.py`

**Interfaces:**
- Consumes: nothing beyond Textual itself.
- Produces: `LoginScreen(on_submit: Callable[[str, str], Awaitable[None]])` — a `textual.screen.Screen` with `#username`/`#password`/`#connect` widgets, calling `on_submit(username, password)` when the form is valid, and `show_error(reason: str) -> None` to display a server-side rejection.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_login_screen.py
"""Tests for the Textual login screen."""
import asyncio

from textual.app import App

from webway.client.screens.login import LoginScreen


def test_login_screen_submits_trimmed_credentials():
    async def run():
        submitted = {}

        async def on_submit(username, password):
            submitted["value"] = (username, password)

        class Harness(App):
            def on_mount(self) -> None:
                self.push_screen(LoginScreen(on_submit))

        app = Harness()
        async with app.run_test() as pilot:
            await pilot.click("#username")
            for ch in "  alice  ":
                await pilot.press(ch if ch != " " else "space")
            await pilot.click("#password")
            for ch in "secret":
                await pilot.press(ch)
            await pilot.click("#connect")
            await pilot.pause()

        assert submitted["value"] == ("alice", "secret")

    asyncio.run(run())


def test_login_screen_blocks_empty_submission():
    async def run():
        calls = []

        async def on_submit(username, password):
            calls.append((username, password))

        class Harness(App):
            def on_mount(self) -> None:
                self.push_screen(LoginScreen(on_submit))

        app = Harness()
        async with app.run_test() as pilot:
            await pilot.click("#connect")
            await pilot.pause()

        assert calls == []

    asyncio.run(run())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_login_screen.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'webway.client.screens.login'`

- [ ] **Step 3: Implement the login screen**

```python
# webway/client/screens/login.py
"""Login screen: collects username/password and authenticates against the server."""
from __future__ import annotations

from typing import Awaitable, Callable

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Input, Label


class LoginScreen(Screen):
    def __init__(self, on_submit: Callable[[str, str], Awaitable[None]]):
        super().__init__()
        self._on_submit = on_submit

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("webway", id="login-title"),
            Input(placeholder="username", id="username"),
            Input(placeholder="password", password=True, id="password"),
            Button("Connect", id="connect", variant="primary"),
            Label("", id="login-error"),
            id="login-form",
        )

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "connect":
            return
        username = self.query_one("#username", Input).value.strip()
        password = self.query_one("#password", Input).value
        if not username or not password:
            self.show_error("username and password are required")
            return
        await self._on_submit(username, password)

    def show_error(self, reason: str) -> None:
        self.query_one("#login-error", Label).update(f"Error: {reason}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_login_screen.py -v`
Expected: PASS (2 tests). If `pilot.press("space")` doesn't insert a literal space in your installed Textual version, replace those presses with `self.query_one("#username", Input).value = "  alice  "` set directly in the test instead — functionally equivalent for this test's purpose.

- [ ] **Step 5: Commit**

```bash
git add webway/client/screens/login.py tests/test_login_screen.py
git commit -m "feat: add Textual login screen"
```

---

### Task 10: Main screen shell + channel/chat/member widgets, wired to live events

**Files:**
- Create: `webway/client/widgets/channel_list.py`
- Create: `webway/client/widgets/chat_log.py`
- Create: `webway/client/widgets/member_list.py`
- Create: `webway/client/screens/main.py`
- Test: `tests/test_main_screen.py`

**Interfaces:**
- Consumes: `WebwayClient` (Task 8), `webway.shared.protocol` (Task 1).
- Produces: `ChannelList` (`ListView` subclass) — `update_channels(channels: list[dict])`, `add_channel(channel_id, name)`, `id_for_name(name) -> int | None`. `ChatLog` (`VerticalScroll` subclass) — `clear()`, `load_history(items)`, `add_message(message: dict)`, `add_reaction(message_id, emoji, username)`, `set_typing(username, state)`. `MemberList` (`ListView` subclass) — `update_members(usernames: list[str])`. `MainScreen(client, username)` — `current_channel_id: int | None`, `async handle_input(text: str)` (routes `/join <name>` vs a plain message send), `async join_channel(channel_id: int)`. Message dicts read `message_type` (not `type`) for msg/action, matching Task 5's wire format.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_main_screen.py
"""Tests for the Textual main screen: channel switching and event handling."""
import asyncio

from textual.app import App

from webway.client.screens.main import MainScreen
from webway.client.widgets.channel_list import ChannelList
from webway.client.widgets.chat_log import ChatLog
from webway.client.widgets.member_list import MemberList
from webway.shared import protocol as p


class StubClient:
    def __init__(self):
        self.sent: list[dict] = []

    async def send(self, payload: dict) -> None:
        self.sent.append(payload)

    async def messages(self):
        if False:
            yield {}


def run(coro):
    return asyncio.run(coro)


def test_join_channel_switches_current_channel_and_sends_join():
    async def body():
        client = StubClient()

        class Harness(App):
            def on_mount(self) -> None:
                self.push_screen(MainScreen(client, "alice"))

        app = Harness()
        async with app.run_test() as pilot:
            screen = app.screen
            screen.query_one(ChannelList).add_channel(1, "general")
            await screen.handle_input("/join general")
            await pilot.pause()

            assert screen.current_channel_id == 1
            assert client.sent[-1] == {"type": p.C_CHANNEL_JOIN, "channel_id": 1}
    run(body())


def test_plain_text_sends_message_to_current_channel():
    async def body():
        client = StubClient()

        class Harness(App):
            def on_mount(self) -> None:
                self.push_screen(MainScreen(client, "alice"))

        app = Harness()
        async with app.run_test() as pilot:
            screen = app.screen
            screen.current_channel_id = 5
            await screen.handle_input("hello there")
            await pilot.pause()

            assert client.sent[-1] == {"type": p.C_MESSAGE_SEND, "channel_id": 5, "text": "hello there"}
    run(body())


def test_history_event_populates_chat_log():
    async def body():
        client = StubClient()

        class Harness(App):
            def on_mount(self) -> None:
                self.push_screen(MainScreen(client, "alice"))

        app = Harness()
        async with app.run_test() as pilot:
            screen = app.screen
            screen.current_channel_id = 5
            await screen._handle_event({
                "type": p.S_HISTORY, "channel_id": 5,
                "items": [{"id": 1, "username": "bob", "message_type": "msg", "text": "hi", "file": None}],
            })
            await pilot.pause()

            chat_log = screen.query_one(ChatLog)
            assert 1 in chat_log._message_widgets
    run(body())


def test_presence_event_updates_member_list():
    async def body():
        client = StubClient()

        class Harness(App):
            def on_mount(self) -> None:
                self.push_screen(MainScreen(client, "alice"))

        app = Harness()
        async with app.run_test() as pilot:
            screen = app.screen
            screen.current_channel_id = 5
            await screen._handle_event({"type": p.S_PRESENCE, "channel_id": 5, "users": ["alice", "bob"]})
            await pilot.pause()

            members = [child.children[0].renderable for child in screen.query_one(MemberList).children]
            assert [str(m) for m in members] == ["alice", "bob"]
    run(body())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_main_screen.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'webway.client.screens.main'`

- [ ] **Step 3: Implement the widgets**

```python
# webway/client/widgets/channel_list.py
"""Sidebar widget listing available channels."""
from __future__ import annotations

from textual.widgets import Label, ListItem, ListView


class ChannelList(ListView):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._id_by_name: dict[str, int] = {}

    def update_channels(self, channels: list[dict]) -> None:
        self.clear()
        self._id_by_name.clear()
        for channel in channels:
            self.add_channel(channel["id"], channel["name"])

    def add_channel(self, channel_id: int, name: str) -> None:
        self._id_by_name[name] = channel_id
        self.append(ListItem(Label(f"# {name}")))

    def id_for_name(self, name: str) -> int | None:
        return self._id_by_name.get(name)
```

```python
# webway/client/widgets/chat_log.py
"""Scrollable chat log rendering messages, reactions, and typing state."""
from __future__ import annotations

from textual.containers import VerticalScroll
from textual.widgets import Static


class ChatLog(VerticalScroll):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._message_widgets: dict[int, Static] = {}
        self._typing_users: set[str] = set()

    def clear(self) -> None:
        self._message_widgets.clear()
        self._typing_users.clear()
        self.remove_children()

    def load_history(self, items: list[dict]) -> None:
        self.clear()
        for item in items:
            self.add_message(item)

    def add_message(self, message: dict) -> None:
        widget = Static(self._render_line(message))
        self._message_widgets[message["id"]] = widget
        self.mount(widget)
        self.scroll_end(animate=False)

    def _render_line(self, message: dict) -> str:
        prefix = "* " if message.get("message_type") == "action" else f"{message['username']}: "
        line = f"{prefix}{message['text']}"
        if message.get("file"):
            line += f"  [file: {message['file']['filename']}]"
        return line

    def add_reaction(self, message_id: int, emoji: str, username: str) -> None:
        widget = self._message_widgets.get(message_id)
        if widget is not None:
            widget.update(f"{widget.renderable}  {emoji}")

    def set_typing(self, username: str, state: bool) -> None:
        if state:
            self._typing_users.add(username)
        else:
            self._typing_users.discard(username)
```

```python
# webway/client/widgets/member_list.py
"""Sidebar widget listing users currently present in the active channel."""
from __future__ import annotations

from textual.widgets import Label, ListItem, ListView


class MemberList(ListView):
    def update_members(self, usernames: list[str]) -> None:
        self.clear()
        for username in usernames:
            self.append(ListItem(Label(username)))
```

- [ ] **Step 4: Implement the main screen**

```python
# webway/client/screens/main.py
"""Main chat screen: channel list, chat log, member list, input box."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Input

from webway.client.widgets.channel_list import ChannelList
from webway.client.widgets.chat_log import ChatLog
from webway.client.widgets.member_list import MemberList
from webway.shared import protocol as p


class MainScreen(Screen):
    def __init__(self, client, username: str):
        super().__init__()
        self.client = client
        self.username = username
        self.current_channel_id: int | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Horizontal(
            ChannelList(id="channel-list"),
            Vertical(
                ChatLog(id="chat-log"),
                Input(placeholder="Message... (/join <name> to switch channel)", id="message-input"),
                id="chat-pane",
            ),
            MemberList(id="member-list"),
        )
        yield Footer()

    def on_mount(self) -> None:
        self.run_worker(self._listen(), exclusive=True)
        self.run_worker(self.client.send({"type": p.C_CHANNEL_LIST}))

    async def _listen(self) -> None:
        async for event in self.client.messages():
            await self._handle_event(event)

    async def _handle_event(self, event: dict) -> None:
        etype = event["type"]
        if etype == p.S_CHANNEL_LIST:
            self.query_one(ChannelList).update_channels(event["channels"])
        elif etype == p.S_CHANNEL_CREATED:
            self.query_one(ChannelList).add_channel(event["id"], event["name"])
        elif etype == p.S_HISTORY and event["channel_id"] == self.current_channel_id:
            self.query_one(ChatLog).load_history(event["items"])
        elif etype == p.S_MESSAGE and event["channel_id"] == self.current_channel_id:
            self.query_one(ChatLog).add_message(event)
        elif etype == p.S_TYPING and event["channel_id"] == self.current_channel_id:
            self.query_one(ChatLog).set_typing(event["username"], event["state"])
        elif etype == p.S_REACTION:
            self.query_one(ChatLog).add_reaction(event["message_id"], event["emoji"], event["username"])
        elif etype == p.S_PRESENCE and event["channel_id"] == self.current_channel_id:
            self.query_one(MemberList).update_members(event["users"])

    async def join_channel(self, channel_id: int) -> None:
        self.current_channel_id = channel_id
        self.query_one(ChatLog).clear()
        await self.client.send({"type": p.C_CHANNEL_JOIN, "channel_id": channel_id})

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "message-input":
            return
        text = event.value.strip()
        event.input.value = ""
        await self.handle_input(text)

    async def handle_input(self, text: str) -> None:
        if not text:
            return
        if text.startswith("/join "):
            name = text[len("/join "):].strip()
            channel_id = self.query_one(ChannelList).id_for_name(name)
            if channel_id is not None:
                await self.join_channel(channel_id)
            return
        if self.current_channel_id is None:
            return
        await self.client.send({
            "type": p.C_MESSAGE_SEND, "channel_id": self.current_channel_id, "text": text,
        })
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_main_screen.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add webway/client/widgets webway/client/screens/main.py tests/test_main_screen.py
git commit -m "feat: add main chat screen with channel/chat/member widgets"
```

---

### Task 11: File sharing UI, inline image rendering, client entrypoint

**Files:**
- Modify: `webway/client/widgets/chat_log.py` (add `mount_image`)
- Modify: `webway/client/screens/main.py` (add `/upload` command, file-render dispatch)
- Create: `webway/client/app.py`
- Modify: `run_client.sh`
- Delete: `client.py`
- Test: `tests/test_file_sharing.py`

**Interfaces:**
- Consumes: `ChatLog` (Task 10), `MainScreen.handle_input` (Task 10), `WebwayClient.upload_file`/`download_file` (Task 8), `LoginScreen` (Task 9).
- Produces: `ChatLog.mount_image(message_id: int, path: str) -> None`. `MainScreen.handle_input` recognizes `/upload <path>`. `WebwayApp(base_url: str)` — Textual `App` entrypoint wiring `LoginScreen` -> `MainScreen`. `main()` CLI entrypoint for `python -m webway.client`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_file_sharing.py
"""Tests for the /upload command and inline-image fallback behavior."""
import asyncio

from textual.app import App

from webway.client.screens.main import MainScreen
from webway.client.widgets.chat_log import ChatLog
from webway.shared import protocol as p


class StubClient:
    def __init__(self):
        self.sent: list[dict] = []
        self.session_token = "tok"

    async def send(self, payload: dict) -> None:
        self.sent.append(payload)

    async def messages(self):
        if False:
            yield {}

    async def upload_file(self, path: str) -> dict:
        return {"file_id": "abc123", "url": "/files/abc123"}

    async def download_file(self, file_id: str, dest_path: str) -> None:
        with open(dest_path, "wb") as fh:
            fh.write(b"fake-image-bytes")


def run(coro):
    return asyncio.run(coro)


def test_upload_command_uploads_then_sends_message_with_file_id(tmp_path):
    async def body():
        client = StubClient()
        src = tmp_path / "cat.png"
        src.write_bytes(b"fake-image-bytes")

        class Harness(App):
            def on_mount(self) -> None:
                self.push_screen(MainScreen(client, "alice"))

        app = Harness()
        async with app.run_test() as pilot:
            screen = app.screen
            screen.current_channel_id = 5
            await screen.handle_input(f"/upload {src}")
            await pilot.pause()

            assert client.sent[-1]["file_id"] == "abc123"
            assert client.sent[-1]["type"] == p.C_MESSAGE_SEND
    run(body())


def test_upload_command_rejects_oversized_file(tmp_path, monkeypatch):
    async def body():
        import webway.client.screens.main as main_module

        monkeypatch.setattr(main_module, "MAX_UPLOAD_SIZE", 4)
        client = StubClient()
        src = tmp_path / "big.bin"
        src.write_bytes(b"way more than four bytes")

        class Harness(App):
            def on_mount(self) -> None:
                self.push_screen(MainScreen(client, "alice"))

        app = Harness()
        async with app.run_test() as pilot:
            screen = app.screen
            screen.current_channel_id = 5
            await screen.handle_input(f"/upload {src}")
            await pilot.pause()

            assert client.sent == []
    run(body())


def test_upload_command_reports_missing_file():
    async def body():
        client = StubClient()

        class Harness(App):
            def on_mount(self) -> None:
                self.push_screen(MainScreen(client, "alice"))

        app = Harness()
        async with app.run_test() as pilot:
            screen = app.screen
            screen.current_channel_id = 5
            await screen.handle_input("/upload /no/such/file.png")
            await pilot.pause()

            assert client.sent == []
    run(body())


def test_mount_image_falls_back_to_text_on_render_failure(monkeypatch):
    async def body():
        import webway.client.widgets.chat_log as chat_log_module

        def boom(path):
            raise RuntimeError("terminal doesn't support graphics")

        monkeypatch.setattr(chat_log_module, "Image", boom)

        class Harness(App):
            def compose(self):
                yield ChatLog(id="chat-log")

        app = Harness()
        async with app.run_test() as pilot:
            log = app.query_one(ChatLog)
            log.mount_image(1, "/tmp/does-not-matter.png")
            await pilot.pause()
            assert len(log.children) == 1
    run(body())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_file_sharing.py -v`
Expected: FAIL — `handle_input` doesn't recognize `/upload` yet, and `chat_log` has no `mount_image`/`Image`.

- [ ] **Step 3: Add inline image rendering to ChatLog**

```python
# webway/client/widgets/chat_log.py — add import and method
from textual_image.widget import Image  # add near the top, alongside the Static import

# add as a new method on ChatLog:
    def mount_image(self, message_id: int, path: str) -> None:
        try:
            widget = Image(path)
        except Exception:
            widget = Static(f"[could not render image: {path}]")
        self.mount(widget)
        self.scroll_end(animate=False)
```

`textual-image`'s exact `Image` constructor may differ slightly between versions — check `python3 -c "from textual_image.widget import Image; help(Image)"` against the installed version and adjust the call above if it takes a `PIL.Image` object instead of a path string (in that case, load with `PIL.Image.open(path)` first and pass that in).

- [ ] **Step 4: Add the /upload command and file-render dispatch to MainScreen**

```python
# webway/client/screens/main.py — modify imports and handle_input, add helpers
import os

CACHE_DIR = os.path.expanduser("~/.cache/webway")
MAX_UPLOAD_SIZE = 15 * 1024 * 1024  # must match webway.server.files.MAX_UPLOAD_SIZE

# extend handle_input, inserting this branch before the current-channel guard:
    async def handle_input(self, text: str) -> None:
        if not text:
            return
        if text.startswith("/join "):
            name = text[len("/join "):].strip()
            channel_id = self.query_one(ChannelList).id_for_name(name)
            if channel_id is not None:
                await self.join_channel(channel_id)
            return
        if self.current_channel_id is None:
            return
        if text.startswith("/upload "):
            path = text[len("/upload "):].strip()
            if not os.path.exists(path):
                self.query_one(ChatLog).add_message({
                    "id": -1, "username": "system", "message_type": "msg",
                    "text": f"file not found: {path}", "file": None,
                })
                return
            if os.path.getsize(path) > MAX_UPLOAD_SIZE:
                self.query_one(ChatLog).add_message({
                    "id": -1, "username": "system", "message_type": "msg",
                    "text": f"file too large (max {MAX_UPLOAD_SIZE // (1024 * 1024)}MB): {path}", "file": None,
                })
                return
            result = await self.client.upload_file(path)
            await self.client.send({
                "type": p.C_MESSAGE_SEND, "channel_id": self.current_channel_id,
                "text": os.path.basename(path), "file_id": result["file_id"],
            })
            return
        await self.client.send({
            "type": p.C_MESSAGE_SEND, "channel_id": self.current_channel_id, "text": text,
        })

# extend _handle_event's S_MESSAGE and S_HISTORY branches to also render files:
        elif etype == p.S_MESSAGE and event["channel_id"] == self.current_channel_id:
            self.query_one(ChatLog).add_message(event)
            self._maybe_render_file(event["id"], event.get("file"))
        elif etype == p.S_HISTORY and event["channel_id"] == self.current_channel_id:
            self.query_one(ChatLog).load_history(event["items"])
            for item in event["items"]:
                self._maybe_render_file(item["id"], item.get("file"))

# add new helper methods on MainScreen:
    def _maybe_render_file(self, message_id: int, file_meta: dict | None) -> None:
        if file_meta and file_meta["mime"].startswith("image/"):
            self.run_worker(self._download_and_show(message_id, file_meta), exclusive=False)

    async def _download_and_show(self, message_id: int, file_meta: dict) -> None:
        os.makedirs(CACHE_DIR, exist_ok=True)
        cache_path = os.path.join(CACHE_DIR, f"{file_meta['id']}_{file_meta['filename']}")
        if not os.path.exists(cache_path):
            await self.client.download_file(file_meta["id"], cache_path)
        self.query_one(ChatLog).mount_image(message_id, cache_path)
```

- [ ] **Step 5: Implement the app entrypoint**

```python
# webway/client/app.py
"""Textual application entrypoint for the webway client."""
from __future__ import annotations

import argparse

from textual.app import App

from webway.client.net import WebwayClient
from webway.client.screens.login import LoginScreen
from webway.client.screens.main import MainScreen
from webway.shared import protocol as p


class WebwayApp(App):
    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.client = WebwayClient(base_url)

    def on_mount(self) -> None:
        self.push_screen(LoginScreen(self._handle_login))

    async def _handle_login(self, username: str, password: str) -> None:
        if self.client.ws is None:
            await self.client.open()
        await self.client.send({"type": p.C_AUTH, "username": username, "password": password})
        reply = await anext(self.client.messages())
        if reply["type"] == p.S_AUTH_ERROR:
            self.screen.show_error(reply["reason"])
            return
        self.client.session_token = reply["session_token"]
        await self.push_screen(MainScreen(self.client, reply["username"]))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("host")
    parser.add_argument("port", type=int)
    args = parser.parse_args()
    WebwayApp(f"http://{args.host}:{args.port}").run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Update run_client.sh and remove the old flat client script**

```bash
# run_client.sh
#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi

source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt

python3 -m webway.client "$@"
```

```bash
git rm client.py
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_file_sharing.py -v`
Expected: PASS (4 tests)

- [ ] **Step 8: Run the full test suite**

Run: `python3 -m pytest tests/ -v`
Expected: PASS (all tests across every task)

- [ ] **Step 9: Manual smoke test**

Run `./run_server.sh 5555` in one terminal, then `./run_client.sh 127.0.0.1 5555` in another; log in with a new username/password, create a channel, send a message from a second client instance logged in as a different user, confirm both see it live, then `/upload <path-to-a-small-png>` and confirm it renders (or shows a file card, depending on terminal support).

- [ ] **Step 10: Commit**

```bash
git add webway/client tests/test_file_sharing.py run_client.sh
git commit -m "feat: add file sharing UI, inline image rendering, and client entrypoint"
```

---

### Task 12: Reconnect with backoff and re-auth

**Files:**
- Modify: `webway/client/app.py` (add `reconnect()`, retain credentials)
- Modify: `webway/client/screens/main.py` (`_listen` calls `self.app.reconnect()` when the stream ends)
- Test: `tests/test_reconnect.py`

**Interfaces:**
- Consumes: `WebwayClient`, `backoff_delays` (Task 8), `WebwayApp` (Task 11).
- Produces: `WebwayApp.reconnect() -> WebwayClient` — retries `WebwayClient(...).open()` + re-`auth` with exponential backoff (via `backoff_delays()`) until it succeeds, updates `self.client`, and returns the new client. `MainScreen._listen` restarts its receive loop against the new client and re-sends `channel.join` for `current_channel_id` if one was set, once the previous client's message stream ends (i.e. the connection dropped).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_reconnect.py
"""Tests for client reconnect-with-backoff and its wiring into MainScreen."""
import asyncio

from textual.app import App

import webway.client.app as app_module
from webway.client.screens.main import MainScreen
from webway.shared import protocol as p


class _FailThenSucceedClient:
    attempts = 0

    def __init__(self, base_url):
        self.base_url = base_url
        self.session_token = None
        self.sent = []

    async def open(self):
        _FailThenSucceedClient.attempts += 1
        if _FailThenSucceedClient.attempts < 3:
            raise ConnectionError("refused")

    async def send(self, payload):
        self.sent.append(payload)

    async def messages(self):
        yield {"type": p.S_AUTH_OK, "session_token": "tok2"}


async def _instant_sleep(*_args, **_kwargs):
    return None


def test_reconnect_retries_until_open_succeeds(monkeypatch):
    _FailThenSucceedClient.attempts = 0
    monkeypatch.setattr(app_module, "WebwayClient", _FailThenSucceedClient)
    monkeypatch.setattr(app_module.asyncio, "sleep", _instant_sleep)

    async def run():
        app = app_module.WebwayApp("http://example.invalid")
        app._username = "alice"
        app._password = "secret"

        new_client = await app.reconnect()

        assert _FailThenSucceedClient.attempts == 3
        assert new_client.session_token == "tok2"
        assert app.client is new_client

    asyncio.run(run())


def test_listen_reconnects_when_message_stream_ends():
    async def run():
        reconnect_calls = []

        class EndsImmediately:
            def __init__(self):
                self.sent = []

            async def send(self, payload):
                self.sent.append(payload)

            async def messages(self):
                return
                yield  # pragma: no cover (unreachable; makes this an async generator)

        class StaysOpen:
            def __init__(self):
                self.sent = []

            async def send(self, payload):
                self.sent.append(payload)

            async def messages(self):
                if False:
                    yield {}

        class Harness(App):
            def on_mount(self) -> None:
                self.push_screen(MainScreen(EndsImmediately(), "alice"))

            async def reconnect(self):
                reconnect_calls.append(1)
                new_client = StaysOpen()
                self.screen.client = new_client
                return new_client

        app = Harness()
        async with app.run_test() as pilot:
            screen = app.screen
            screen.current_channel_id = 5
            await pilot.pause()
            await pilot.pause()
            await pilot.pause()

        assert reconnect_calls == [1]
        assert isinstance(screen.client, StaysOpen)
        assert screen.client.sent == [{"type": p.C_CHANNEL_JOIN, "channel_id": 5}]

    asyncio.run(run())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_reconnect.py -v`
Expected: FAIL — `WebwayApp` has no `reconnect` method yet, and `MainScreen._listen` never calls it.

- [ ] **Step 3: Add reconnect() to WebwayApp**

```python
# webway/client/app.py — add imports and fields, add reconnect()
import asyncio

import aiohttp

from webway.client.net import WebwayClient, backoff_delays  # extend existing net import

class WebwayApp(App):
    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.client = WebwayClient(base_url)
        self._username: str | None = None
        self._password: str | None = None

    def on_mount(self) -> None:
        self.push_screen(LoginScreen(self._handle_login))

    async def _handle_login(self, username: str, password: str) -> None:
        if self.client.ws is None:
            await self.client.open()
        await self.client.send({"type": p.C_AUTH, "username": username, "password": password})
        reply = await anext(self.client.messages())
        if reply["type"] == p.S_AUTH_ERROR:
            self.screen.show_error(reply["reason"])
            return
        self._username = username
        self._password = password
        self.client.session_token = reply["session_token"]
        await self.push_screen(MainScreen(self.client, reply["username"]))

    async def reconnect(self) -> WebwayClient:
        """Reopen the connection with exponential backoff, then re-authenticate."""
        async for delay in backoff_delays():
            try:
                new_client = WebwayClient(self.base_url)
                await new_client.open()
                await new_client.send({
                    "type": p.C_AUTH, "username": self._username, "password": self._password,
                })
                reply = await anext(new_client.messages())
                if reply["type"] == p.S_AUTH_OK:
                    new_client.session_token = reply["session_token"]
                    self.client = new_client
                    return new_client
            except (ConnectionError, OSError, aiohttp.ClientError):
                pass
            await asyncio.sleep(delay)
```

- [ ] **Step 4: Make MainScreen reconnect when the stream ends**

```python
# webway/client/screens/main.py — replace the existing _listen method
    async def _listen(self) -> None:
        while True:
            async for event in self.client.messages():
                await self._handle_event(event)
            new_client = await self.app.reconnect()
            self.client = new_client
            if self.current_channel_id is not None:
                await self.client.send({
                    "type": p.C_CHANNEL_JOIN, "channel_id": self.current_channel_id,
                })
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_reconnect.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Run the full test suite**

Run: `python3 -m pytest tests/ -v`
Expected: PASS (all tests)

- [ ] **Step 7: Commit**

```bash
git add webway/client/app.py webway/client/screens/main.py tests/test_reconnect.py
git commit -m "feat: reconnect with exponential backoff and automatic re-auth"
```

---

### Task 13: Update README

**Files:**
- Modify: `README.md`

**Interfaces:** None — documentation only.

- [ ] **Step 1: Rewrite README.md to describe the new architecture**

Replace the curses/single-room description with: how to run the server and client (`./run_server.sh [port]`, `./run_client.sh <ip> <port>`), that login now takes a username *and* password (first use creates the account), how to create/switch channels (`/join <name>`, and mention channel creation happens via the UI), and how to share a file (`/upload <path>`), plus the file/image inline-rendering caveat (falls back to a text notice on terminals without graphics protocol support). Drop the animation-specific sections (Matrix rain, confetti, rainbow mode, etc.) that no longer apply to the rewritten client, unless a later task re-adds them as polish.

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: rewrite README for the Textual multi-channel client"
```

---

### Task 14: Add /create channel command (gap fill)

> Added after Task 13 during final verification: the server has always fully implemented `channel.create` (Task 5), but no task ever wired a client-side command to trigger it — `MainScreen.handle_input` only recognized `/join` and `/upload`. This closes that gap against the spec's core goal of user-creatable channels.

**Files:**
- Modify: `webway/client/screens/main.py`
- Modify: `README.md`
- Test: `tests/test_main_screen.py`

**Interfaces:**
- Consumes: `webway.shared.protocol.C_CHANNEL_CREATE` (Task 1), `MainScreen.handle_input` (Task 10/11, extending it further).
- Produces: `handle_input` recognizes `/create <name> [topic...]`, sending `{"type": p.C_CHANNEL_CREATE, "name": name, "topic": topic}` (topic defaults to `""` if omitted). No new interface beyond this — the server already broadcasts `channel.created` globally (Task 5) and `MainScreen._handle_event`'s existing `S_CHANNEL_CREATED` branch (Task 10) already adds it to `ChannelList`, so no other client-side wiring is needed.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_main_screen.py — add these two tests
def test_create_channel_sends_channel_create_with_topic():
    async def body():
        client = StubClient()

        class Harness(App):
            def on_mount(self) -> None:
                self.push_screen(MainScreen(client, "alice"))

        app = Harness()
        async with app.run_test() as pilot:
            screen = app.screen
            await screen.handle_input("/create general a place to chat")
            await pilot.pause()

            assert client.sent[-1] == {
                "type": p.C_CHANNEL_CREATE, "name": "general", "topic": "a place to chat",
            }
    run(body())


def test_create_channel_without_topic_defaults_empty():
    async def body():
        client = StubClient()

        class Harness(App):
            def on_mount(self) -> None:
                self.push_screen(MainScreen(client, "alice"))

        app = Harness()
        async with app.run_test() as pilot:
            screen = app.screen
            await screen.handle_input("/create random")
            await pilot.pause()

            assert client.sent[-1] == {"type": p.C_CHANNEL_CREATE, "name": "random", "topic": ""}
    run(body())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_main_screen.py -v`
Expected: FAIL — `/create` currently falls through to a plain `message.send` (or is silently dropped if no channel is joined yet), not a `channel.create` frame.

- [ ] **Step 3: Add the /create branch to handle_input**

```python
# webway/client/screens/main.py — modify handle_input, insert this branch
# right after the existing "/join " branch, BEFORE the
# "if self.current_channel_id is None: return" guard (creating a channel
# must not require already being in one):
        if text.startswith("/create "):
            rest = text[len("/create "):].strip()
            if not rest:
                return
            parts = rest.split(maxsplit=1)
            name = parts[0]
            topic = parts[1] if len(parts) > 1 else ""
            await self.client.send({"type": p.C_CHANNEL_CREATE, "name": name, "topic": topic})
            return
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_main_screen.py -v`
Expected: PASS (all tests, including the two new ones)

- [ ] **Step 5: Update README.md**

Add a line documenting `/create <name> [topic]` alongside the existing `/join`/`/upload` command documentation, matching the README's existing style and correcting the earlier vague "channel creation happens via the UI" phrasing from Task 13 with the actual command.

- [ ] **Step 6: Run the full test suite**

Run: `python3 -m pytest tests/ -v`
Expected: PASS (all tests)

- [ ] **Step 7: Commit**

```bash
git add webway/client/screens/main.py tests/test_main_screen.py README.md
git commit -m "feat: add /create command for user-creatable channels"
```
