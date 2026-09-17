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
