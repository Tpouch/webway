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
