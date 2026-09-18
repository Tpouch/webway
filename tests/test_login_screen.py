"""Tests for the Textual login screen."""
import asyncio

from textual.app import App

from webway.client.screens.login import LoginScreen


def test_login_screen_submits_trimmed_credentials():
    async def run():
        submitted = {}

        async def on_submit(username, password):
            submitted["value"] = (username, password)

        class Harness(App):
            def on_mount(self) -> None:
                self.push_screen(LoginScreen(on_submit))

        app = Harness()
        async with app.run_test() as pilot:
            await pilot.click("#username")
            for ch in "  alice  ":
                await pilot.press(ch if ch != " " else "space")
            await pilot.click("#password")
            for ch in "secret":
                await pilot.press(ch)
            await pilot.click("#connect")
            await pilot.pause()

        assert submitted["value"] == ("alice", "secret")

    asyncio.run(run())


def test_login_screen_blocks_empty_submission():
    async def run():
        calls = []

        async def on_submit(username, password):
            calls.append((username, password))

        class Harness(App):
            def on_mount(self) -> None:
                self.push_screen(LoginScreen(on_submit))

        app = Harness()
        async with app.run_test() as pilot:
            await pilot.click("#connect")
            await pilot.pause()

        assert calls == []

    asyncio.run(run())
