"""Retro terminal color themes: green phosphor and amber, cycled with Ctrl+T."""
from __future__ import annotations

from textual.theme import Theme

PHOSPHOR_GREEN = Theme(
    name="phosphor-green",
    primary="#33ff66",
    secondary="#1aff8c",
    accent="#33ff66",
    warning="#ffcc00",
    error="#ff3333",
    success="#33ff66",
    foreground="#33ff66",
    background="#000000",
    surface="#001a00",
    panel="#002200",
    dark=True,
)

AMBER = Theme(
    name="amber",
    primary="#ffb000",
    secondary="#ff8800",
    accent="#ffb000",
    warning="#ffdd00",
    error="#ff4444",
    success="#ffb000",
    foreground="#ffb000",
    background="#000000",
    surface="#1a1000",
    panel="#221600",
    dark=True,
)

THEMES = [PHOSPHOR_GREEN, AMBER]
THEME_NAMES = [theme.name for theme in THEMES]


def next_theme_name(current_name: str) -> str:
    """Return the theme name that follows ``current_name`` in the cycle, wrapping around."""
    try:
        index = THEME_NAMES.index(current_name)
    except ValueError:
        return THEME_NAMES[0]
    return THEME_NAMES[(index + 1) % len(THEME_NAMES)]
