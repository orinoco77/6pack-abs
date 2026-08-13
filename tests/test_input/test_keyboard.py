"""Tests for keyboard → InputAction mapping (Kodi-aligned)."""
from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt

from sixpack.input.actions import InputAction
from sixpack.input.keyboard import key_to_action


# ---- Navigation mode ----

@pytest.mark.parametrize("key,expected", [
    (Qt.Key.Key_Up, InputAction.UP),
    (Qt.Key.Key_Down, InputAction.DOWN),
    (Qt.Key.Key_Left, InputAction.LEFT),
    (Qt.Key.Key_Right, InputAction.RIGHT),
    (Qt.Key.Key_Return, InputAction.SELECT),
    (Qt.Key.Key_Enter, InputAction.SELECT),
    (Qt.Key.Key_Escape, InputAction.BACK),
    (Qt.Key.Key_Backspace, InputAction.BACK),
])
def test_nav_mode_mappings(key, expected):
    assert key_to_action(key, player_mode=False) == expected


def test_nav_mode_space_unmapped():
    """Space is not SELECT in nav mode — Kodi reserves it for play/pause."""
    assert key_to_action(Qt.Key.Key_Space, player_mode=False) is None


def test_nav_mode_unmapped_key():
    assert key_to_action(Qt.Key.Key_A, player_mode=False) is None


# ---- Player mode ----

@pytest.mark.parametrize("key,expected", [
    (Qt.Key.Key_Space, InputAction.PLAY_PAUSE),
    (Qt.Key.Key_P, InputAction.PLAY_PAUSE),
    (Qt.Key.Key_X, InputAction.STOP),
    (Qt.Key.Key_Right, InputAction.SEEK_FORWARD),
    (Qt.Key.Key_Left, InputAction.SEEK_BACK),
    (Qt.Key.Key_F, InputAction.SEEK_FORWARD_LONG),
    (Qt.Key.Key_R, InputAction.SEEK_BACK_LONG),
    (Qt.Key.Key_Period, InputAction.NEXT_CHAPTER),
    (Qt.Key.Key_Comma, InputAction.PREV_CHAPTER),
    (Qt.Key.Key_PageUp, InputAction.NEXT_ITEM),
    (Qt.Key.Key_PageDown, InputAction.PREV_ITEM),
    (Qt.Key.Key_N, InputAction.NEXT_ITEM),
    (Qt.Key.Key_B, InputAction.PREV_ITEM),
    (Qt.Key.Key_Return, InputAction.MENU),
    (Qt.Key.Key_Enter, InputAction.MENU),
    (Qt.Key.Key_Escape, InputAction.BACK),
    (Qt.Key.Key_Backspace, InputAction.BACK),
    (Qt.Key.Key_Up, InputAction.UP),
    (Qt.Key.Key_Down, InputAction.DOWN),
])
def test_player_mode_mappings(key, expected):
    assert key_to_action(key, player_mode=True) == expected


def test_player_mode_unmapped_key():
    assert key_to_action(Qt.Key.Key_Z, player_mode=True) is None


# ---- Mode switching ----

def test_space_nav_unmapped_player_plays():
    """Space is unmapped in nav mode but play/pause in player mode."""
    nav = key_to_action(Qt.Key.Key_Space, player_mode=False)
    player = key_to_action(Qt.Key.Key_Space, player_mode=True)
    assert nav is None
    assert player == InputAction.PLAY_PAUSE


def test_right_different_in_modes():
    nav = key_to_action(Qt.Key.Key_Right, player_mode=False)
    player = key_to_action(Qt.Key.Key_Right, player_mode=True)
    assert nav == InputAction.RIGHT
    assert player == InputAction.SEEK_FORWARD
    assert nav != player


def test_f_r_are_long_seek_only_in_player():
    """F/R are long seek in player mode; unmapped in nav mode."""
    assert key_to_action(Qt.Key.Key_F, player_mode=True) == InputAction.SEEK_FORWARD_LONG
    assert key_to_action(Qt.Key.Key_R, player_mode=True) == InputAction.SEEK_BACK_LONG
    assert key_to_action(Qt.Key.Key_F, player_mode=False) is None
    assert key_to_action(Qt.Key.Key_R, player_mode=False) is None