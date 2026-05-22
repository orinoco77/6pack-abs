"""Maps Qt key events to InputActions."""
from __future__ import annotations

from PyQt6.QtCore import Qt

from .actions import InputAction

# Navigation keys — used by all screens
_NAV_MAP: dict[Qt.Key, InputAction] = {
    Qt.Key.Key_Up: InputAction.UP,
    Qt.Key.Key_Down: InputAction.DOWN,
    Qt.Key.Key_Left: InputAction.LEFT,
    Qt.Key.Key_Right: InputAction.RIGHT,
    Qt.Key.Key_Return: InputAction.SELECT,
    Qt.Key.Key_Enter: InputAction.SELECT,
    Qt.Key.Key_Space: InputAction.SELECT,
    Qt.Key.Key_Escape: InputAction.BACK,
    Qt.Key.Key_Backspace: InputAction.BACK,
}

# Player-specific keys — override select/back in player context
_PLAYER_MAP: dict[Qt.Key, InputAction] = {
    Qt.Key.Key_Up: InputAction.UP,
    Qt.Key.Key_Down: InputAction.DOWN,
    Qt.Key.Key_Return: InputAction.MENU,
    Qt.Key.Key_Enter: InputAction.MENU,
    Qt.Key.Key_Escape: InputAction.BACK,
    Qt.Key.Key_Backspace: InputAction.BACK,
    Qt.Key.Key_Space: InputAction.PLAY_PAUSE,
    Qt.Key.Key_P: InputAction.PLAY_PAUSE,
    Qt.Key.Key_S: InputAction.STOP,
    Qt.Key.Key_Right: InputAction.SEEK_FORWARD,
    Qt.Key.Key_Left: InputAction.SEEK_BACK,
    Qt.Key.Key_Period: InputAction.NEXT_CHAPTER,
    Qt.Key.Key_Comma: InputAction.PREV_CHAPTER,
    Qt.Key.Key_N: InputAction.NEXT_ITEM,
    Qt.Key.Key_B: InputAction.PREV_ITEM,
}


def key_to_action(key: Qt.Key, player_mode: bool = False) -> InputAction | None:
    """Return the InputAction for a Qt key, or None if unmapped."""
    mapping = _PLAYER_MAP if player_mode else _NAV_MAP
    return mapping.get(key)
