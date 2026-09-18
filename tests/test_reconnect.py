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
                await asyncio.Event().wait()  # never set — blocks forever, representing an open connection with no messages
                yield {}  # pragma: no cover (unreachable; keeps this an async generator)

        class Harness(App):
            def on_mount(self) -> None:
                self.push_screen(MainScreen(EndsImmediately(), "alice"))
                # Set current_channel_id on the pushed screen
                self.screen.current_channel_id = 5

            async def reconnect(self):
                reconnect_calls.append(1)
                new_client = StaysOpen()
                self.screen.client = new_client
                return new_client

        app = Harness()
        async with app.run_test() as pilot:
            screen = app.screen
            await pilot.pause()
            await pilot.pause()
            await pilot.pause()

        assert reconnect_calls == [1]
        assert isinstance(screen.client, StaysOpen)
        assert screen.client.sent == [{"type": p.C_CHANNEL_JOIN, "channel_id": 5}]

    asyncio.run(run())
