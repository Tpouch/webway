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


class RaisingConnection(FakeConnection):
    """Reports itself open but fails on send, like a mid-close transport."""

    async def send_str(self, data: str) -> None:
        raise ConnectionResetError("transport gone")


def test_broadcast_isolates_a_failing_connection():
    registry = ChannelRegistry()
    bad, good = RaisingConnection(), FakeConnection()
    registry.subscribe(1, bad, "bad")
    registry.subscribe(1, good, "good")
    run(registry.broadcast(1, {"type": "message", "text": "hi"}))
    assert len(good.sent) == 1


def test_broadcast_global_isolates_a_failing_connection():
    registry = ChannelRegistry()
    bad, good = RaisingConnection(), FakeConnection()
    registry.register(bad, "bad")
    registry.register(good, "good")
    run(registry.broadcast_global({"type": "channel.created", "name": "general"}))
    assert len(good.sent) == 1


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
