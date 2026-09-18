"""Main chat screen: channel list, chat log, member list, input box."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Input

from webway.client.widgets.channel_list import ChannelList
from webway.client.widgets.chat_log import ChatLog
from webway.client.widgets.member_list import MemberList
from webway.shared import protocol as p


class MainScreen(Screen):
    def __init__(self, client, username: str):
        super().__init__()
        self.client = client
        self.username = username
        self.current_channel_id: int | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Horizontal(
            ChannelList(id="channel-list"),
            Vertical(
                ChatLog(id="chat-log"),
                Input(placeholder="Message... (/join <name> to switch channel)", id="message-input"),
                id="chat-pane",
            ),
            MemberList(id="member-list"),
        )
        yield Footer()

    def on_mount(self) -> None:
        self.run_worker(self._listen(), exclusive=True)
        self.run_worker(self.client.send({"type": p.C_CHANNEL_LIST}))

    async def _listen(self) -> None:
        async for event in self.client.messages():
            await self._handle_event(event)

    async def _handle_event(self, event: dict) -> None:
        etype = event["type"]
        if etype == p.S_CHANNEL_LIST:
            self.query_one(ChannelList).update_channels(event["channels"])
        elif etype == p.S_CHANNEL_CREATED:
            self.query_one(ChannelList).add_channel(event["id"], event["name"])
        elif etype == p.S_HISTORY and event["channel_id"] == self.current_channel_id:
            self.query_one(ChatLog).load_history(event["items"])
        elif etype == p.S_MESSAGE and event["channel_id"] == self.current_channel_id:
            self.query_one(ChatLog).add_message(event)
        elif etype == p.S_TYPING and event["channel_id"] == self.current_channel_id:
            self.query_one(ChatLog).set_typing(event["username"], event["state"])
        elif etype == p.S_REACTION:
            self.query_one(ChatLog).add_reaction(event["message_id"], event["emoji"], event["username"])
        elif etype == p.S_PRESENCE and event["channel_id"] == self.current_channel_id:
            self.query_one(MemberList).update_members(event["users"])

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
        if self.current_channel_id is None:
            return
        await self.client.send({
            "type": p.C_MESSAGE_SEND, "channel_id": self.current_channel_id, "text": text,
        })
