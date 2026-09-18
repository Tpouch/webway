"""Scrollable chat log rendering messages, reactions, and typing state."""
from __future__ import annotations

from rich.markup import escape as markup_escape
from textual.containers import VerticalScroll
from textual.widgets import Static


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
        widget = Static(self._render_line(message))
        self._message_widgets[message["id"]] = widget
        self.mount(widget)
        self.scroll_end(animate=False)

    def _render_line(self, message: dict) -> str:
        prefix = "* " if message.get("message_type") == "action" else f"{markup_escape(message['username'])}: "
        line = f"{prefix}{markup_escape(message['text'])}"
        if message.get("file"):
            line += f"  [file: {markup_escape(message['file']['filename'])}]"
        return line

    def add_reaction(self, message_id: int, emoji: str, username: str) -> None:
        widget = self._message_widgets.get(message_id)
        if widget is not None:
            widget.update(f"{widget.content}  {markup_escape(emoji)}")

    def set_typing(self, username: str, state: bool) -> None:
        if state:
            self._typing_users.add(username)
        else:
            self._typing_users.discard(username)
