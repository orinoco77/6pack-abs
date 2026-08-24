"""Tests for InputAction enum and keyboard mapping."""
from __future__ import annotations

from sixpack.input.actions import InputAction


def test_all_actions_are_unique():
    values = [a.value for a in InputAction]
    assert len(values) == len(set(values))


def test_action_names():
    expected = {
        "UP", "DOWN", "LEFT", "RIGHT",
        "SELECT", "BACK",
        "PLAY_PAUSE", "STOP",
        "SEEK_FORWARD", "SEEK_BACK",
        "SEEK_FORWARD_LONG", "SEEK_BACK_LONG",
        "NEXT_CHAPTER", "PREV_CHAPTER",
        "NEXT_ITEM", "PREV_ITEM",
        "MENU",
    }
    actual = {a.name for a in InputAction}
    assert actual == expected


def test_action_equality():
    assert InputAction.UP == InputAction.UP
    assert InputAction.UP != InputAction.DOWN
