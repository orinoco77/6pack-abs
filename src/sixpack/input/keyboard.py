"""Maps Qt key events to InputActions following Kodi's default keyboard layout."""
from __future__ import annotations

from PyQt6.QtCore import Qt

from .actions import InputAction

# Navigation — grids, lists, menus (matches Kodi's Global/Home context)
_NAV_MAP: dict[Qt.Key, InputAction] = {
    Qt.Key.Key_Up: InputAction.UP,
    Qt.Key.Key_Down: InputAction.DOWN,
    Qt.Key.Key_Left: InputAction.LEFT,
    Qt.Key.Key_Right: InputAction.RIGHT,
    Qt.Key.Key_Return: InputAction.SELECT,
    Qt.Key.Key_Enter: InputAction.SELECT,
    # Kodi: Backspace = Back (primary), Escape = previous menu (secondary)
    # Key_Back is sent by many remotes as a dedicated back button
    Qt.Key.Key_Backspace: InputAction.BACK,
    Qt.Key.Key_Escape: InputAction.BACK,
    Qt.Key.Key_Back: InputAction.BACK,
    # Media keys — fired by remote control play/pause/stop/skip buttons
    Qt.Key.Key_MediaPlay: InputAction.PLAY_PAUSE,
    Qt.Key.Key_MediaPause: InputAction.PLAY_PAUSE,
    Qt.Key.Key_MediaTogglePlayPause: InputAction.PLAY_PAUSE,
    Qt.Key.Key_MediaStop: InputAction.STOP,
    Qt.Key.Key_MediaNext: InputAction.NEXT_ITEM,
    Qt.Key.Key_MediaPrevious: InputAction.PREV_ITEM,
}

# Player — FullscreenVideo context (Kodi's FullscreenVideo keymap)
_PLAYER_MAP: dict[Qt.Key, InputAction] = {
    Qt.Key.Key_Up: InputAction.UP,
    Qt.Key.Key_Down: InputAction.DOWN,
    Qt.Key.Key_Backspace: InputAction.BACK,
    Qt.Key.Key_Escape: InputAction.BACK,
    Qt.Key.Key_Back: InputAction.BACK,
    # Kodi: Space/P = play-pause; Enter = show OSD (MENU)
    Qt.Key.Key_Space: InputAction.PLAY_PAUSE,
    Qt.Key.Key_P: InputAction.PLAY_PAUSE,
    Qt.Key.Key_Return: InputAction.MENU,
    Qt.Key.Key_Enter: InputAction.MENU,
    # Stop — Kodi uses X; remote controls send Key_MediaStop
    Qt.Key.Key_X: InputAction.STOP,
    Qt.Key.Key_MediaStop: InputAction.STOP,
    # Media play/pause — remote control dedicated buttons
    Qt.Key.Key_MediaPlay: InputAction.PLAY_PAUSE,
    Qt.Key.Key_MediaPause: InputAction.PLAY_PAUSE,
    Qt.Key.Key_MediaTogglePlayPause: InputAction.PLAY_PAUSE,
    # Next/prev item via remote media skip buttons
    Qt.Key.Key_MediaNext: InputAction.NEXT_ITEM,
    Qt.Key.Key_MediaPrevious: InputAction.PREV_ITEM,
    # Seek — Left/Right step; F/R = fast-forward/rewind (Kodi: hold to accelerate)
    Qt.Key.Key_Right: InputAction.SEEK_FORWARD,
    Qt.Key.Key_Left: InputAction.SEEK_BACK,
    Qt.Key.Key_F: InputAction.SEEK_FORWARD_LONG,
    Qt.Key.Key_R: InputAction.SEEK_BACK_LONG,
    # Chapter skip — Kodi uses . / ,
    Qt.Key.Key_Period: InputAction.NEXT_CHAPTER,
    Qt.Key.Key_Comma: InputAction.PREV_CHAPTER,
    # Item skip — Kodi: PageUp/PageDown = next/prev chapter in FullscreenVideo
    Qt.Key.Key_PageUp: InputAction.NEXT_ITEM,
    Qt.Key.Key_PageDown: InputAction.PREV_ITEM,
    Qt.Key.Key_N: InputAction.NEXT_ITEM,
    Qt.Key.Key_B: InputAction.PREV_ITEM,
}


def key_to_action(key: Qt.Key, player_mode: bool = False) -> InputAction | None:
    """Return the InputAction for a Qt key, or None if unmapped."""
    mapping = _PLAYER_MAP if player_mode else _NAV_MAP
    return mapping.get(key)
