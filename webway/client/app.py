"""Textual application entrypoint for the webway client."""
from __future__ import annotations

import argparse

from textual.app import App

from webway.client.net import WebwayClient
from webway.client.screens.login import LoginScreen
from webway.client.screens.main import MainScreen
from webway.shared import protocol as p


class WebwayApp(App):
    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.client = WebwayClient(base_url)

    def on_mount(self) -> None:
        self.push_screen(LoginScreen(self._handle_login))

    async def _handle_login(self, username: str, password: str) -> None:
        if self.client.ws is None:
            await self.client.open()
        await self.client.send({"type": p.C_AUTH, "username": username, "password": password})
        reply = await anext(self.client.messages())
        if reply["type"] == p.S_AUTH_ERROR:
            self.screen.show_error(reply["reason"])
            return
        self.client.session_token = reply["session_token"]
        await self.push_screen(MainScreen(self.client, reply["username"]))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("host")
    parser.add_argument("port", type=int)
    args = parser.parse_args()
    WebwayApp(f"http://{args.host}:{args.port}").run()


if __name__ == "__main__":
    main()
