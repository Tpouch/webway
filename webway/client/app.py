"""Textual application entrypoint for the webway client."""
from __future__ import annotations

import argparse
import asyncio
import logging

import aiohttp
from textual.app import App
from textual.binding import Binding

from webway.client.net import WebwayClient, backoff_delays
from webway.client.screens.login import LoginScreen
from webway.client.screens.main import MainScreen
from webway.client.theme import PHOSPHOR_GREEN, THEMES, next_theme_name
from webway.shared import protocol as p

logger = logging.getLogger("webway.client.app")


class WebwayApp(App):
    CSS_PATH = "webway.tcss"
    BINDINGS = [Binding("ctrl+t", "cycle_theme", "Thème suivant", show=True)]

    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.client = WebwayClient(base_url)
        self._username: str | None = None
        self._password: str | None = None
        for theme in THEMES:
            self.register_theme(theme)
        self.theme = PHOSPHOR_GREEN.name

    def action_cycle_theme(self) -> None:
        self.theme = next_theme_name(self.theme)

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
        """Reopen the connection with exponential backoff, then re-authenticate.

        Every failure mode here is retryable: a refused connection, a socket
        dropped mid-handshake (``StopAsyncIteration`` from the empty message
        stream), a malformed reply, or an ``auth.error``. None of them may
        escape, or the caller's receive worker dies for good.
        """
        async for delay in backoff_delays():
            new_client = WebwayClient(self.base_url)
            try:
                await new_client.open()
                await new_client.send({
                    "type": p.C_AUTH, "username": self._username, "password": self._password,
                })
                reply = await anext(new_client.messages())
                if reply["type"] == p.S_AUTH_OK:
                    new_client.session_token = reply["session_token"]
                    self.client = new_client
                    return new_client
                # Anything else (including auth.error, e.g. the password changed
                # while we were away) is not a usable connection: keep retrying.
                logger.warning("reconnect rejected: %s", reply.get("reason", reply["type"]))
            except (ConnectionError, OSError, aiohttp.ClientError,
                    StopAsyncIteration, p.ProtocolError) as exc:
                logger.warning("reconnect attempt failed: %r", exc)
            # Failed attempts must not leak their aiohttp.ClientSession.
            try:
                await new_client.close()
            except Exception:
                logger.warning("failed to close abandoned client", exc_info=True)
            await asyncio.sleep(delay)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("host")
    parser.add_argument("port", type=int)
    args = parser.parse_args()
    WebwayApp(f"http://{args.host}:{args.port}").run()


if __name__ == "__main__":
    main()
