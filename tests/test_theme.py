"""Tests for the retro theme cycling helper."""
from webway.client.theme import THEME_NAMES, next_theme_name


def test_next_theme_name_cycles_forward():
    assert next_theme_name("phosphor-green") == "amber"


def test_next_theme_name_wraps_around():
    assert next_theme_name("amber") == "phosphor-green"


def test_next_theme_name_falls_back_to_first_for_unknown_name():
    assert next_theme_name("does-not-exist") == THEME_NAMES[0]
