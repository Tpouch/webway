"""Sidebar widget listing users currently present in the active channel."""
from __future__ import annotations

from rich.markup import escape as markup_escape
from textual.widgets import Label, ListItem, ListView


class MemberList(ListView):
    def update_members(self, usernames: list[str]) -> None:
        self.clear()
        for username in usernames:
            self.append(ListItem(Label(markup_escape(username))))
