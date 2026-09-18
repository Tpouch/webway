"""Integration tests for the webway aiohttp server: auth, channels, messages."""
import json
import os
import sqlite3
import tempfile

from aiohttp.test_utils import AioHTTPTestCase
from aiohttp import web

from webway.server.app import create_app
from webway.server.appkeys import CHANNELS_KEY, DB_KEY
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

    async def _setup_channel(self, ws, name="general"):
        """Authenticate, create a channel, join it. Returns the channel id."""
        await self._receive_until(ws, p.S_CHANNEL_LIST)
        await ws.send_str(p.encode({"type": p.C_CHANNEL_CREATE, "name": name, "topic": ""}))
        created = await self._receive_until(ws, p.S_CHANNEL_CREATED)
        await ws.send_str(p.encode({"type": p.C_CHANNEL_JOIN, "channel_id": created["id"]}))
        await self._receive_until(ws, p.S_HISTORY)
        return created["id"]

    async def test_message_to_unknown_channel_is_a_clean_error_and_connection_survives(self):
        async with self.client.ws_connect("/ws") as ws:
            await self._auth(ws, "alice")
            channel_id = await self._setup_channel(ws)

            await ws.send_str(p.encode({
                "type": p.C_MESSAGE_SEND, "channel_id": 999999, "text": "into the void",
            }))
            reply = await self._receive_until(ws, p.S_ERROR)
            self.assertEqual(reply["reason"], "no_such_channel")

            # The connection must still be usable afterwards.
            await ws.send_str(p.encode({
                "type": p.C_MESSAGE_SEND, "channel_id": channel_id, "text": "still here",
            }))
            msg = await self._receive_until(ws, p.S_MESSAGE)
            self.assertEqual(msg["text"], "still here")

    async def test_message_with_non_string_file_id_is_a_clean_error(self):
        async with self.client.ws_connect("/ws") as ws:
            await self._auth(ws, "alice")
            channel_id = await self._setup_channel(ws)

            await ws.send_str(p.encode({
                "type": p.C_MESSAGE_SEND, "channel_id": channel_id, "text": "hi", "file_id": 12345,
            }))
            reply = await self._receive_until(ws, p.S_ERROR)
            self.assertEqual(reply["reason"], "invalid_file_id")

            await ws.send_str(p.encode({
                "type": p.C_MESSAGE_SEND, "channel_id": channel_id, "text": "still here",
            }))
            msg = await self._receive_until(ws, p.S_MESSAGE)
            self.assertEqual(msg["text"], "still here")

    async def test_message_with_unknown_file_id_is_a_clean_error(self):
        async with self.client.ws_connect("/ws") as ws:
            await self._auth(ws, "alice")
            channel_id = await self._setup_channel(ws)

            await ws.send_str(p.encode({
                "type": p.C_MESSAGE_SEND, "channel_id": channel_id,
                "text": "hi", "file_id": "no-such-file",
            }))
            reply = await self._receive_until(ws, p.S_ERROR)
            self.assertEqual(reply["reason"], "no_such_file")

            await ws.send_str(p.encode({
                "type": p.C_MESSAGE_SEND, "channel_id": channel_id, "text": "still here",
            }))
            msg = await self._receive_until(ws, p.S_MESSAGE)
            self.assertEqual(msg["text"], "still here")

    async def test_server_side_error_does_not_break_other_connections(self):
        """Regression test for the cascading-crash bug.

        An unhandled exception while handling one client's message used to
        escape the `async for` loop, skipping disconnect cleanup and leaving a
        dead connection in the registry, which then poisoned every subsequent
        broadcast to that channel for everyone else.
        """
        async with self.client.ws_connect("/ws") as ws1, self.client.ws_connect("/ws") as ws2:
            await self._auth(ws1, "alice")
            channel_id = await self._setup_channel(ws1)
            await self._auth(ws2, "bob")
            await self._receive_until(ws2, p.S_CHANNEL_LIST)
            await ws2.send_str(p.encode({"type": p.C_CHANNEL_JOIN, "channel_id": channel_id}))
            await self._receive_until(ws2, p.S_HISTORY)

            # Force an unexpected server-side failure for the next message only.
            db = self.app[DB_KEY]
            original = db.create_message
            calls = []

            async def boom(*args, **kwargs):
                if not calls:
                    calls.append(1)
                    raise RuntimeError("synthetic DB failure")
                return await original(*args, **kwargs)

            db.create_message = boom
            try:
                await ws1.send_str(p.encode({
                    "type": p.C_MESSAGE_SEND, "channel_id": channel_id, "text": "boom",
                }))
                reply = await self._receive_until(ws1, p.S_ERROR)
                self.assertEqual(reply["reason"], "internal_error")

                # Alice's connection survived...
                await ws1.send_str(p.encode({
                    "type": p.C_MESSAGE_SEND, "channel_id": channel_id, "text": "after the error",
                }))
                mine = await self._receive_until(ws1, p.S_MESSAGE)
                self.assertEqual(mine["text"], "after the error")

                # ...and Bob still receives broadcasts normally.
                theirs = await self._receive_until(ws2, p.S_MESSAGE)
                self.assertEqual(theirs["text"], "after the error")
                self.assertEqual(theirs["username"], "alice")

                # Bob can still send, and Alice still receives.
                await ws2.send_str(p.encode({
                    "type": p.C_MESSAGE_SEND, "channel_id": channel_id, "text": "bob replies",
                }))
                back = await self._receive_until(ws1, p.S_MESSAGE)
                self.assertEqual(back["text"], "bob replies")
            finally:
                db.create_message = original

    async def test_disconnect_after_server_side_error_still_cleans_up_registry(self):
        channels = self.app[CHANNELS_KEY]
        async with self.client.ws_connect("/ws") as ws_keeper:
            await self._auth(ws_keeper, "keeper")
            channel_id = await self._setup_channel(ws_keeper)

            async with self.client.ws_connect("/ws") as ws:
                await self._auth(ws, "alice")
                await self._receive_until(ws, p.S_CHANNEL_LIST)
                await ws.send_str(p.encode({"type": p.C_CHANNEL_JOIN, "channel_id": channel_id}))
                await self._receive_until(ws, p.S_HISTORY)
                self.assertIn("alice", channels.members(channel_id))

                db = self.app[DB_KEY]
                original = db.create_message
                db.create_message = _always_raises
                try:
                    await ws.send_str(p.encode({
                        "type": p.C_MESSAGE_SEND, "channel_id": channel_id, "text": "boom",
                    }))
                    await self._receive_until(ws, p.S_ERROR)
                finally:
                    db.create_message = original

            # Closing the socket must run the disconnect cleanup even though the
            # connection hit a server-side error earlier.
            await self._receive_until(ws_keeper, p.S_PRESENCE)
            self.assertEqual(channels.members(channel_id), ["keeper"])

    async def test_channel_join_unsubscribes_from_the_previous_channel(self):
        channels = self.app[CHANNELS_KEY]
        async with self.client.ws_connect("/ws") as ws1, self.client.ws_connect("/ws") as ws2:
            await self._auth(ws1, "alice")
            channel_a = await self._setup_channel(ws1, "alpha")
            await ws1.send_str(p.encode({"type": p.C_CHANNEL_CREATE, "name": "beta", "topic": ""}))
            channel_b = (await self._receive_until(ws1, p.S_CHANNEL_CREATED))["id"]

            await self._auth(ws2, "bob")
            await self._receive_until(ws2, p.S_CHANNEL_LIST)
            await ws2.send_str(p.encode({"type": p.C_CHANNEL_JOIN, "channel_id": channel_a}))
            await self._receive_until(ws2, p.S_HISTORY)
            presence = await self._receive_until(ws1, p.S_PRESENCE)
            self.assertEqual(presence["users"], ["alice", "bob"])

            # Bob switches to beta: alpha's presence must drop him.
            await ws2.send_str(p.encode({"type": p.C_CHANNEL_JOIN, "channel_id": channel_b}))
            await self._receive_until(ws2, p.S_HISTORY)
            presence = await self._receive_until(ws1, p.S_PRESENCE)
            self.assertEqual(presence["channel_id"], channel_a)
            self.assertEqual(presence["users"], ["alice"])
            self.assertNotIn("bob", channels.members(channel_a))
            self.assertIn("bob", channels.members(channel_b))

    async def test_lost_registration_race_is_a_clean_auth_error(self):
        """Two connections registering the same brand-new username concurrently.

        The loser's create_user hits the UNIQUE constraint; it must surface as
        auth.error, not an uncaught IntegrityError that kills the connection.
        """
        db = self.app[DB_KEY]
        original = db.create_user

        async def racing_create_user(*args, **kwargs):
            raise sqlite3.IntegrityError("UNIQUE constraint failed: users.username")

        db.create_user = racing_create_user
        try:
            async with self.client.ws_connect("/ws") as ws:
                reply = await self._auth(ws, "contested")
                self.assertEqual(reply["type"], p.S_AUTH_ERROR)
                self.assertEqual(reply["reason"], "bad_credentials")
                # The connection survives; retrying with real credentials works.
                db.create_user = original
                reply = await self._auth(ws, "contested")
                self.assertEqual(reply["type"], p.S_AUTH_OK)
        finally:
            db.create_user = original

    async def test_over_long_password_is_a_clean_auth_error(self):
        async with self.client.ws_connect("/ws") as ws:
            reply = await self._auth(ws, "alice", "x" * 73)
            self.assertEqual(reply["type"], p.S_AUTH_ERROR)
            self.assertIn("too long", reply["reason"])
            # The connection is still usable: a valid password works.
            reply = await self._auth(ws, "alice", "pw")
            self.assertEqual(reply["type"], p.S_AUTH_OK)


async def _always_raises(*_args, **_kwargs):
    raise RuntimeError("synthetic DB failure")
