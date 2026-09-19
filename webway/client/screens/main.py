"""Main chat screen: channel list, chat log, member list, input box."""
from __future__ import annotations

import asyncio
import os

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Input

from webway.client.widgets.channel_list import ChannelList
from webway.client.widgets.chat_log import ChatLog
from webway.client.widgets.member_list import MemberList
from webway.shared import protocol as p

CACHE_DIR = os.path.expanduser("~/.cache/webway")
MAX_UPLOAD_SIZE = 15 * 1024 * 1024  # must match webway.server.files.MAX_UPLOAD_SIZE


class MainScreen(Screen):
    def __init__(self, client, username: str):
        super().__init__()
        self.client = client
        self.username = username
        self.current_channel_id: int | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        channel_list = ChannelList(id="channel-list")
        channel_list.border_title = "CANAUX"
        member_list = MemberList(id="member-list")
        member_list.border_title = "MEMBRES"
        chat_pane = Vertical(
            ChatLog(id="chat-log"),
            Input(placeholder="> message... (/join <nom> pour changer de canal)", id="message-input"),
            id="chat-pane",
        )
        chat_pane.border_title = "MESSAGES"
        yield Horizontal(channel_list, chat_pane, member_list)
        yield Footer()

    def on_mount(self) -> None:
        self.run_worker(self._listen(), exclusive=True)
        self.run_worker(self.client.send({"type": p.C_CHANNEL_LIST}))

    async def _listen(self) -> None:
        while True:
            async for event in self.client.messages():
                await self._handle_event(event)
            new_client = await self.app.reconnect()
            self.client = new_client
            if self.current_channel_id is not None:
                await self.client.send({
                    "type": p.C_CHANNEL_JOIN, "channel_id": self.current_channel_id,
                })

    async def _handle_event(self, event: dict) -> None:
        etype = event["type"]
        if etype == p.S_CHANNEL_LIST:
            self.query_one(ChannelList).update_channels(event["channels"])
        elif etype == p.S_CHANNEL_CREATED:
            self.query_one(ChannelList).add_channel(event["id"], event["name"])
        elif etype == p.S_HISTORY and event["channel_id"] == self.current_channel_id:
            self.query_one(ChatLog).load_history(event["items"])
            for item in event["items"]:
                self._maybe_render_file(item["id"], item.get("file"))
        elif etype == p.S_MESSAGE and event["channel_id"] == self.current_channel_id:
            self.query_one(ChatLog).add_message(event)
            self._maybe_render_file(event["id"], event.get("file"))
        elif etype == p.S_TYPING and event["channel_id"] == self.current_channel_id:
            self.query_one(ChatLog).set_typing(event["username"], event["state"])
        elif etype == p.S_REACTION:
            self.query_one(ChatLog).add_reaction(event["message_id"], event["emoji"], event["username"])
        elif etype == p.S_PRESENCE and event["channel_id"] == self.current_channel_id:
            self.query_one(MemberList).update_members(event["users"])
        elif etype == p.S_ERROR:
            self.query_one(ChatLog).add_message({
                "id": -1, "username": "system", "message_type": "msg",
                "text": f"erreur : {event.get('reason', 'inconnue')}", "file": None,
            })

    async def join_channel(self, channel_id: int) -> None:
        self.current_channel_id = channel_id
        self.query_one(ChatLog).clear()
        await self.client.send({"type": p.C_CHANNEL_JOIN, "channel_id": channel_id})

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "message-input":
            return
        text = event.value.strip()
        event.input.value = ""
        await self.handle_input(text)

    async def handle_input(self, text: str) -> None:
        if not text:
            return
        if text.startswith("/join "):
            name = text[len("/join "):].strip()
            channel_id = self.query_one(ChannelList).id_for_name(name)
            if channel_id is not None:
                await self.join_channel(channel_id)
            return
        if text.startswith("/create "):
            rest = text[len("/create "):].strip()
            if not rest:
                return
            parts = rest.split(maxsplit=1)
            name = parts[0]
            topic = parts[1] if len(parts) > 1 else ""
            await self.client.send({"type": p.C_CHANNEL_CREATE, "name": name, "topic": topic})
            return
        if self.current_channel_id is None:
            return
        if text.startswith("/upload "):
            path = text[len("/upload "):].strip()
            if not os.path.exists(path):
                self.query_one(ChatLog).add_message({
                    "id": -1, "username": "system", "message_type": "msg",
                    "text": f"fichier introuvable : {path}", "file": None,
                })
                return
            if os.path.getsize(path) > MAX_UPLOAD_SIZE:
                self.query_one(ChatLog).add_message({
                    "id": -1, "username": "system", "message_type": "msg",
                    "text": f"fichier trop volumineux (max {MAX_UPLOAD_SIZE // (1024 * 1024)}Mo) : {path}",
                    "file": None,
                })
                return
            result = await self.client.upload_file(path)
            if "file_id" not in result:
                self.query_one(ChatLog).add_message({
                    "id": -1, "username": "system", "message_type": "msg",
                    "text": f"échec de l'envoi : {result.get('reason', 'erreur inconnue')}", "file": None,
                })
                return
            await self.client.send({
                "type": p.C_MESSAGE_SEND, "channel_id": self.current_channel_id,
                "text": os.path.basename(path), "file_id": result["file_id"],
            })
            return
        await self.client.send({
            "type": p.C_MESSAGE_SEND, "channel_id": self.current_channel_id, "text": text,
        })

    def _maybe_render_file(self, message_id: int, file_meta: dict | None) -> None:
        if file_meta and file_meta["mime"].startswith("image/"):
            self.run_worker(self._download_and_show(message_id, file_meta), exclusive=False)

    async def _download_and_show(self, message_id: int, file_meta: dict) -> None:
        os.makedirs(CACHE_DIR, exist_ok=True)
        safe_filename = os.path.basename(file_meta["filename"])
        cache_path = os.path.join(CACHE_DIR, f"{file_meta['id']}_{safe_filename}")
        if not os.path.exists(cache_path):
            await self.client.download_file(file_meta["id"], cache_path)
        self.query_one(ChatLog).mount_image(message_id, cache_path)
