"""Scrollable chat log rendering messages, reactions, and typing state."""
from __future__ import annotations

import zlib

from rich.markup import escape as markup_escape
from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import Static
from textual_image.widget import Image

# A fixed palette of colors readable on a dark background, cycled by a hash of
# the username so each person gets a consistent color, Discord-style.
USERNAME_COLORS = [
    "cyan", "magenta", "yellow", "bright_blue", "bright_red",
    "bright_magenta", "bright_cyan", "orange3", "deep_pink3", "turquoise2",
]


def _color_for_username(username: str) -> str:
    index = zlib.crc32(username.encode("utf-8")) % len(USERNAME_COLORS)
    return USERNAME_COLORS[index]


class ChatLog(VerticalScroll):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._message_widgets: dict[int, Static] = {}
        self._typing_users: set[str] = set()

    def clear(self) -> None:
        self._message_widgets.clear()
        self._typing_users.clear()
        self.remove_children()

    def load_history(self, items: list[dict]) -> None:
        self.clear()
        for item in items:
            self.add_message(item)

    def add_message(self, message: dict) -> None:
        # Static(markup_string) does not apply color spans in the installed
        # Textual — only a pre-parsed Text object renders styled spans.
        widget = Static(Text.from_markup(self._render_line(message)))
        self._message_widgets[message["id"]] = widget
        self.mount(widget)
        self.scroll_end(animate=False)

    def _render_line(self, message: dict) -> str:
        username = message["username"]
        if message.get("message_type") == "action":
            prefix = f"* {markup_escape(username)} "
        else:
            color = _color_for_username(username)
            prefix = f"[{color}]{markup_escape(username)}[/{color}]: "
        line = f"{prefix}{markup_escape(message['text'])}"
        if message.get("file"):
            line += f"  (fichier : {markup_escape(message['file']['filename'])})"
        return line

    def mount_image(self, message_id: int, path: str) -> None:
        def fallback(exc: Exception) -> Static:
            return Static(f"(image illisible : {markup_escape(path)})")

        try:
            widget = Image(path, on_error=fallback)
        except Exception:
            widget = fallback(None)
        self.mount(widget)
        self.scroll_end(animate=False)

    def add_reaction(self, message_id: int, emoji: str, username: str) -> None:
        widget = self._message_widgets.get(message_id)
        if widget is not None:
            text = widget.content
            # Append as plain (unparsed) text so the emoji can never be read
            # back as markup, and the existing username color span survives.
            text.append(f"  {emoji}")
            widget.update(text)

    def set_typing(self, username: str, state: bool) -> None:
        if state:
            self._typing_users.add(username)
        else:
            self._typing_users.discard(username)
