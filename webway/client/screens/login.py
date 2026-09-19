"""Login screen: collects username/password and authenticates against the server."""
from __future__ import annotations

from typing import Awaitable, Callable

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Input, Label


class LoginScreen(Screen):
    def __init__(self, on_submit: Callable[[str, str], Awaitable[None]]):
        super().__init__()
        self._on_submit = on_submit

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("WEBWAY", id="login-title"),
            Input(placeholder="nom d'utilisateur", id="username"),
            Input(placeholder="mot de passe", password=True, id="password"),
            Button("Connexion", id="connect", variant="primary"),
            Label("", id="login-error"),
            id="login-form",
        )

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "connect":
            return
        username = self.query_one("#username", Input).value.strip()
        password = self.query_one("#password", Input).value
        if not username or not password:
            self.show_error("nom d'utilisateur et mot de passe requis")
            return
        await self._on_submit(username, password)

    def show_error(self, reason: str) -> None:
        self.query_one("#login-error", Label).update(f"Erreur : {reason}")
