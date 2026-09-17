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
