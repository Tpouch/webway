"""Tests for the Textual main screen: channel switching and event handling."""
import asyncio

from textual.app import App

from webway.client.screens.main import MainScreen
from webway.client.widgets.channel_list import ChannelList
from webway.client.widgets.chat_log import ChatLog
from webway.client.widgets.member_list import MemberList
from webway.shared import protocol as p


class StubClient:
    def __init__(self):
        self.sent: list[dict] = []

    async def send(self, payload: dict) -> None:
        self.sent.append(payload)

    async def messages(self):
        if False:
            yield {}


def run(coro):
    return asyncio.run(coro)


def test_join_channel_switches_current_channel_and_sends_join():
    async def body():
        client = StubClient()

        class Harness(App):
            def on_mount(self) -> None:
                self.push_screen(MainScreen(client, "alice"))

        app = Harness()
        async with app.run_test() as pilot:
            screen = app.screen
            screen.query_one(ChannelList).add_channel(1, "general")
            await screen.handle_input("/join general")
            await pilot.pause()

            assert screen.current_channel_id == 1
            assert client.sent[-1] == {"type": p.C_CHANNEL_JOIN, "channel_id": 1}
    run(body())


def test_plain_text_sends_message_to_current_channel():
    async def body():
        client = StubClient()

        class Harness(App):
            def on_mount(self) -> None:
                self.push_screen(MainScreen(client, "alice"))

        app = Harness()
        async with app.run_test() as pilot:
            screen = app.screen
            screen.current_channel_id = 5
            await screen.handle_input("hello there")
            await pilot.pause()

            assert client.sent[-1] == {"type": p.C_MESSAGE_SEND, "channel_id": 5, "text": "hello there"}
    run(body())


def test_history_event_populates_chat_log():
    async def body():
        client = StubClient()

        class Harness(App):
            def on_mount(self) -> None:
                self.push_screen(MainScreen(client, "alice"))

        app = Harness()
        async with app.run_test() as pilot:
            screen = app.screen
            screen.current_channel_id = 5
            await screen._handle_event({
                "type": p.S_HISTORY, "channel_id": 5,
                "items": [{"id": 1, "username": "bob", "message_type": "msg", "text": "hi", "file": None}],
            })
            await pilot.pause()

            chat_log = screen.query_one(ChatLog)
            assert 1 in chat_log._message_widgets
    run(body())


def test_presence_event_updates_member_list():
    async def body():
        client = StubClient()

        class Harness(App):
            def on_mount(self) -> None:
                self.push_screen(MainScreen(client, "alice"))

        app = Harness()
        async with app.run_test() as pilot:
            screen = app.screen
            screen.current_channel_id = 5
            await screen._handle_event({"type": p.S_PRESENCE, "channel_id": 5, "users": ["alice", "bob"]})
            await pilot.pause()

            members = [child.children[0].content for child in screen.query_one(MemberList).children]
            assert [str(m) for m in members] == ["alice", "bob"]
    run(body())
