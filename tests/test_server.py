"""Integration tests for the webway aiohttp server: auth, channels, messages."""
import json
import os
import tempfile

from aiohttp.test_utils import AioHTTPTestCase
from aiohttp import web

from webway.server.app import create_app
from webway.shared import protocol as p


class ServerTestCase(AioHTTPTestCase):
    async def get_application(self) -> web.Application:
        self.tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(self.tmpdir, "test.db")
        upload_dir = os.path.join(self.tmpdir, "uploads")
        return create_app(db_path, upload_dir)

    async def _auth(self, ws, username, password="pw"):
        await ws.send_str(p.encode({"type": p.C_AUTH, "username": username, "password": password}))
        return json.loads(await ws.receive_str())

    async def _receive_until(self, ws, msg_type):
        while True:
            payload = json.loads(await ws.receive_str())
            if payload["type"] == msg_type:
                return payload

    async def test_auth_creates_account_on_first_use(self):
        async with self.client.ws_connect("/ws") as ws:
            reply = await self._auth(ws, "alice")
            self.assertEqual(reply["type"], p.S_AUTH_OK)
            self.assertEqual(reply["username"], "alice")

    async def test_auth_rejects_wrong_password(self):
        async with self.client.ws_connect("/ws") as ws:
            await self._auth(ws, "bob", "correct")
        async with self.client.ws_connect("/ws") as ws:
            reply = await self._auth(ws, "bob", "wrong")
            self.assertEqual(reply["type"], p.S_AUTH_ERROR)

    async def test_channel_create_join_and_message_broadcast(self):
        async with self.client.ws_connect("/ws") as ws1, self.client.ws_connect("/ws") as ws2:
            await self._auth(ws1, "alice")
            await self._receive_until(ws1, p.S_CHANNEL_LIST)
            await self._auth(ws2, "bob")
            await self._receive_until(ws2, p.S_CHANNEL_LIST)

            await ws1.send_str(p.encode({"type": p.C_CHANNEL_CREATE, "name": "general", "topic": "chat"}))
            created = await self._receive_until(ws1, p.S_CHANNEL_CREATED)
            await self._receive_until(ws2, p.S_CHANNEL_CREATED)
            channel_id = created["id"]

            await ws1.send_str(p.encode({"type": p.C_CHANNEL_JOIN, "channel_id": channel_id}))
            history = await self._receive_until(ws1, p.S_HISTORY)
            self.assertEqual(history["items"], [])

            await ws2.send_str(p.encode({"type": p.C_CHANNEL_JOIN, "channel_id": channel_id}))
            await self._receive_until(ws2, p.S_HISTORY)

            await ws1.send_str(p.encode({"type": p.C_MESSAGE_SEND, "channel_id": channel_id, "text": "hi bob"}))
            msg1 = await self._receive_until(ws1, p.S_MESSAGE)
            msg2 = await self._receive_until(ws2, p.S_MESSAGE)
            self.assertEqual(msg1["text"], "hi bob")
            self.assertEqual(msg2["message_type"], "msg")
            self.assertEqual(msg2["username"], "alice")

    async def test_reaction_is_broadcast_to_channel(self):
        async with self.client.ws_connect("/ws") as ws1, self.client.ws_connect("/ws") as ws2:
            await self._auth(ws1, "alice")
            await self._receive_until(ws1, p.S_CHANNEL_LIST)
            await self._auth(ws2, "bob")
            await self._receive_until(ws2, p.S_CHANNEL_LIST)

            await ws1.send_str(p.encode({"type": p.C_CHANNEL_CREATE, "name": "general", "topic": ""}))
            created = await self._receive_until(ws1, p.S_CHANNEL_CREATED)
            await self._receive_until(ws2, p.S_CHANNEL_CREATED)
            channel_id = created["id"]

            await ws1.send_str(p.encode({"type": p.C_CHANNEL_JOIN, "channel_id": channel_id}))
            await self._receive_until(ws1, p.S_HISTORY)
            await ws2.send_str(p.encode({"type": p.C_CHANNEL_JOIN, "channel_id": channel_id}))
            await self._receive_until(ws2, p.S_HISTORY)

            await ws1.send_str(p.encode({"type": p.C_MESSAGE_SEND, "channel_id": channel_id, "text": "hi"}))
            msg = await self._receive_until(ws2, p.S_MESSAGE)

            await ws2.send_str(p.encode({"type": p.C_REACTION_ADD, "message_id": msg["id"], "emoji": "⭐"}))
            reaction = await self._receive_until(ws1, p.S_REACTION)
            self.assertEqual(reaction["message_id"], msg["id"])
            self.assertEqual(reaction["username"], "bob")

    async def test_unauthenticated_message_is_rejected(self):
        async with self.client.ws_connect("/ws") as ws:
            await ws.send_str(p.encode({"type": p.C_MESSAGE_SEND, "channel_id": 1, "text": "hi"}))
            reply = json.loads(await ws.receive_str())
            self.assertEqual(reply["type"], p.S_ERROR)
            self.assertEqual(reply["reason"], "not_authenticated")
