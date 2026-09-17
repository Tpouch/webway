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
