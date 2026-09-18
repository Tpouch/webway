"""Sidebar widget listing available channels."""
from __future__ import annotations

from rich.markup import escape as markup_escape
from textual.widgets import Label, ListItem, ListView


class ChannelList(ListView):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._id_by_name: dict[str, int] = {}

    def update_channels(self, channels: list[dict]) -> None:
        self.clear()
        self._id_by_name.clear()
        for channel in channels:
            self.add_channel(channel["id"], channel["name"])

    def add_channel(self, channel_id: int, name: str) -> None:
        self._id_by_name[name] = channel_id
        self.append(ListItem(Label(f"# {markup_escape(name)}")))


    def id_for_name(self, name: str) -> int | None:
        return self._id_by_name.get(name)
