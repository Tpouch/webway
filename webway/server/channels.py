"""In-memory channel subscription and broadcast bookkeeping.

Channel rows themselves live in SQLite (see db.py); this module only
tracks which live WebSocket connections are subscribed to which channel,
for broadcast and presence purposes.
"""
from __future__ import annotations

import logging
from typing import Protocol

from webway.shared.protocol import encode

logger = logging.getLogger("webway.server.channels")


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

    async def _send_isolated(self, ws: Connection, message: str) -> None:
        """Send to one connection, swallowing any failure.

        A connection can report ``closed is False`` and still raise from
        ``send_str`` (mid-close, transport already reset). One such failure
        must never abort the broadcast loop for the remaining subscribers,
        nor propagate into whatever caller triggered the broadcast.
        """
        if ws.closed:
            return
        try:
            await ws.send_str(message)
        except Exception:
            logger.warning("dropping broadcast to failed connection", exc_info=True)

    async def broadcast(self, channel_id: int, payload: dict) -> None:
        message = encode(payload)
        for ws in self.connections(channel_id):
            await self._send_isolated(ws, message)

    async def broadcast_global(self, payload: dict) -> None:
        message = encode(payload)
        for ws in list(self._all_connections):
            await self._send_isolated(ws, message)
