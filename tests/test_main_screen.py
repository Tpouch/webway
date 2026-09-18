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
        await asyncio.Event().wait()  # never set — blocks forever, representing an open connection with no new messages
        yield {}  # pragma: no cover (unreachable; keeps this an async generator)


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


def test_add_reaction_works_without_crash():
    async def body():
        client = StubClient()

        class Harness(App):
            def on_mount(self) -> None:
                self.push_screen(MainScreen(client, "alice"))


        app = Harness()
        async with app.run_test() as pilot:
            screen = app.screen
            chat_log = screen.query_one(ChatLog)
            # Add a message first
            chat_log.add_message({"id": 1, "username": "bob", "message_type": "msg", "text": "hello", "file": None})
            # Then add a reaction
            chat_log.add_reaction(1, "👍", "alice")
            await pilot.pause()

            # Verify the reaction was added to the widget content
            widget = chat_log._message_widgets.get(1)
            assert widget is not None
            assert "👍" in widget.content
    run(body())


def test_markup_injection_is_escaped():
    async def body():
        client = StubClient()

        class Harness(App):
            def on_mount(self) -> None:
                self.push_screen(MainScreen(client, "alice"))


        app = Harness()
        async with app.run_test() as pilot:
            screen = app.screen
            chat_log = screen.query_one(ChatLog)
            # Add a message with markup characters
            chat_log.add_message({
                "id": 1,
                "username": "[bold]hacker[/bold]",
                "message_type": "msg",
                "text": "[link=file:///etc/passwd]click[/link]",
                "file": None
            })
            await pilot.pause()

            widget = chat_log._message_widgets.get(1)
            assert widget is not None
            # The escaped markup should appear as literal text, not be interpreted
            assert r"\[bold]" in widget.content
            assert r"\[link=" in widget.content


def test_create_channel_sends_channel_create_with_topic():
    async def body():
        client = StubClient()

        class Harness(App):
            def on_mount(self) -> None:
                self.push_screen(MainScreen(client, "alice"))

        app = Harness()
        async with app.run_test() as pilot:
            screen = app.screen
            await screen.handle_input("/create general a place to chat")
            await pilot.pause()

            assert client.sent[-1] == {
                "type": p.C_CHANNEL_CREATE, "name": "general", "topic": "a place to chat",
            }
    run(body())


def test_create_channel_without_topic_defaults_empty():
    async def body():
        client = StubClient()

        class Harness(App):
            def on_mount(self) -> None:
                self.push_screen(MainScreen(client, "alice"))

        app = Harness()
        async with app.run_test() as pilot:
            screen = app.screen
            await screen.handle_input("/create random")
            await pilot.pause()

            assert client.sent[-1] == {"type": p.C_CHANNEL_CREATE, "name": "random", "topic": ""}
    run(body())
