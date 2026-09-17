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
