"""Tests for the client transport wrapper, against a real (test) webway server."""
import asyncio
import os
import tempfile

import aiohttp
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


class _FakeMsg:
    def __init__(self, msg_type, data=None):
        self.type = msg_type
        self.data = data


class _FakeWS:
    """Minimal stand-in for aiohttp's ClientWebSocketResponse."""

    def __init__(self, msgs):
        self._msgs = msgs

    def __aiter__(self):
        async def gen():
            for msg in self._msgs:
                yield msg
        return gen()

    def exception(self):
        return RuntimeError("socket blew up")


def _collect(msgs):
    async def run():
        wc = WebwayClient("http://example.invalid")
        wc.ws = _FakeWS(msgs)
        return [event async for event in wc.messages()]
    return asyncio.run(run())


def test_messages_drops_malformed_frames_and_keeps_yielding():
    text = aiohttp.WSMsgType.TEXT
    events = _collect([
        _FakeMsg(text, p.encode({"type": p.S_MESSAGE, "text": "first"})),
        _FakeMsg(text, "{not json at all"),
        _FakeMsg(text, '"a bare string, not an object"'),
        _FakeMsg(text, p.encode({"type": p.S_MESSAGE, "text": "second"})),
    ])
    assert [e["text"] for e in events] == ["first", "second"]


def test_messages_ends_cleanly_on_websocket_error():
    text = aiohttp.WSMsgType.TEXT
    events = _collect([
        _FakeMsg(text, p.encode({"type": p.S_MESSAGE, "text": "first"})),
        _FakeMsg(aiohttp.WSMsgType.ERROR),
        _FakeMsg(text, p.encode({"type": p.S_MESSAGE, "text": "never seen"})),
    ])
    assert [e["text"] for e in events] == ["first"]


def test_backoff_delays_grow_and_cap():
    async def run():
        delays = []
        gen = backoff_delays()
        for _ in range(6):
            delays.append(await anext(gen))
        assert delays == [1, 2, 4, 8, 16, 30]
    asyncio.run(run())
