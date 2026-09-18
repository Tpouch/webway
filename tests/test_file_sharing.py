"""Tests for the /upload command and inline-image fallback behavior."""
import asyncio
import os

from textual.app import App

from webway.client.screens.main import MainScreen
from webway.client.widgets.chat_log import ChatLog
from webway.shared import protocol as p


class BlockingClient:
    """Mock client with blocking message stream to prevent reconnect loop."""
    async def send(self, payload):
        pass
    async def messages(self):
        # Never yield - block indefinitely waiting for an event that never comes
        # This makes it an async generator that never yields
        while True:
            await asyncio.sleep(100)
            if False:
                yield {}  # pragma: no cover - unreachable, but makes this an async generator


class StubClient:
    def __init__(self):
        self.sent: list[dict] = []
        self.session_token = "tok"

    async def send(self, payload: dict) -> None:
        self.sent.append(payload)

    async def messages(self):
        if False:
            yield {}

    async def upload_file(self, path: str) -> dict:
        return {"file_id": "abc123", "url": "/files/abc123"}

    async def download_file(self, file_id: str, dest_path: str) -> None:
        with open(dest_path, "wb") as fh:
            fh.write(b"fake-image-bytes")


def run(coro):
    return asyncio.run(coro)


def test_upload_command_uploads_then_sends_message_with_file_id(tmp_path):
    async def body():
        client = StubClient()
        src = tmp_path / "cat.png"
        src.write_bytes(b"fake-image-bytes")

        class Harness(App):
            def on_mount(self) -> None:
                self.push_screen(MainScreen(client, "alice"))

            async def reconnect(self):
                return BlockingClient()

        app = Harness()
        async with app.run_test() as pilot:
            screen = app.screen
            screen.current_channel_id = 5
            await screen.handle_input(f"/upload {src}")
            await pilot.pause()

            assert client.sent[-1]["file_id"] == "abc123"
            assert client.sent[-1]["type"] == p.C_MESSAGE_SEND
    run(body())


def test_upload_command_rejects_oversized_file(tmp_path, monkeypatch):
    async def body():
        import webway.client.screens.main as main_module

        monkeypatch.setattr(main_module, "MAX_UPLOAD_SIZE", 4)
        client = StubClient()
        src = tmp_path / "big.bin"
        src.write_bytes(b"way more than four bytes")

        class Harness(App):
            def on_mount(self) -> None:
                self.push_screen(MainScreen(client, "alice"))

            async def reconnect(self):
                return BlockingClient()

        app = Harness()
        async with app.run_test() as pilot:
            screen = app.screen
            screen.current_channel_id = 5
            await screen.handle_input(f"/upload {src}")
            await pilot.pause()

            assert not any(msg.get("type") == p.C_MESSAGE_SEND for msg in client.sent)
    run(body())


def test_upload_command_reports_missing_file():
    async def body():
        client = StubClient()

        class Harness(App):
            def on_mount(self) -> None:
                self.push_screen(MainScreen(client, "alice"))

            async def reconnect(self):
                return BlockingClient()

        app = Harness()
        async with app.run_test() as pilot:
            screen = app.screen
            screen.current_channel_id = 5
            await screen.handle_input("/upload /no/such/file.png")
            await pilot.pause()

            assert not any(msg.get("type") == p.C_MESSAGE_SEND for msg in client.sent)
    run(body())


def test_file_indicator_uses_parens_and_is_visible():
    async def body():
        class Harness(App):
            def compose(self):
                yield ChatLog(id="chat-log")

        app = Harness()
        async with app.run_test() as pilot:
            log = app.query_one(ChatLog)
            log.add_message({
                "id": 1, "username": "bob", "message_type": "msg", "text": "look",
                "file": {"filename": "cat.png"},
            })
            await pilot.pause()

            widget = log._message_widgets.get(1)
            assert widget is not None
            # Square brackets are Rich markup and would silently swallow this
            # substring; parens require no escaping and render as literal text.
            assert "(file: cat.png)" in widget.content
    run(body())


def test_missing_file_notice_does_not_double_escape_bracket_in_path():
    async def body():
        client = StubClient()

        class Harness(App):
            def on_mount(self) -> None:
                self.push_screen(MainScreen(client, "alice"))

        app = Harness()
        async with app.run_test() as pilot:
            screen = app.screen
            screen.current_channel_id = 5
            await screen.handle_input("/upload /no/such/weird[name].png")
            await pilot.pause()

            chat_log = screen.query_one(ChatLog)
            widget = chat_log._message_widgets.get(-1)
            assert widget is not None
            # widget.content is the raw Rich markup source (escape sequences
            # intact, not yet rendered). ChatLog._render_line already escapes
            # the whole text field once, so the bracket should appear
            # singly-escaped ("\[") here. Pre-escaping the path too would
            # double-escape it to "\\\[", leaving a visible stray backslash
            # once Rich renders the markup.
            assert "weird\\[name].png" in widget.content
            assert "\\\\[" not in widget.content
    run(body())


def test_download_and_show_sanitizes_path_traversal_filename(tmp_path, monkeypatch):
    async def body():
        import webway.client.screens.main as main_module

        monkeypatch.setattr(main_module, "CACHE_DIR", str(tmp_path))
        client = StubClient()

        class Harness(App):
            def on_mount(self) -> None:
                self.push_screen(MainScreen(client, "alice"))

            async def reconnect(self):
                return BlockingClient()

        app = Harness()
        async with app.run_test() as pilot:
            screen = app.screen
            for malicious_filename in ("../../../etc/passwd", "/etc/passwd"):
                file_meta = {"id": "fid1", "filename": malicious_filename, "mime": "image/png"}
                await screen._download_and_show(1, file_meta)
                await pilot.pause()

                # The written file must be a plain filename directly inside CACHE_DIR:
                # no path-traversal or absolute-path component from the (attacker-
                # controlled) filename may reach the filesystem call.
                entries = os.listdir(tmp_path)
                assert entries == ["fid1_passwd"], entries
                cache_path = os.path.join(str(tmp_path), entries[0])
                assert os.path.commonpath([str(tmp_path), os.path.abspath(cache_path)]) == str(tmp_path)

                os.remove(cache_path)
    run(body())


def test_mount_image_falls_back_to_text_on_render_failure(monkeypatch):
    async def body():
        import webway.client.widgets.chat_log as chat_log_module

        def boom(path):
            raise RuntimeError("terminal doesn't support graphics")

        monkeypatch.setattr(chat_log_module, "Image", boom)

        class Harness(App):
            def compose(self):
                yield ChatLog(id="chat-log")

        app = Harness()
        async with app.run_test() as pilot:
            log = app.query_one(ChatLog)
            log.mount_image(1, "/tmp/does-not-matter.png")
            await pilot.pause()
            assert len(log.children) == 1
    run(body())
