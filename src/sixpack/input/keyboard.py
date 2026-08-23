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
    # Kodi: Space/P = play-pause (kept as a direct keyboard-only bonus —
    # play/pause is also reachable via the control row + Select)
    Qt.Key.Key_Space: InputAction.PLAY_PAUSE,
    Qt.Key.Key_P: InputAction.PLAY_PAUSE,
    # Enter/Return activates whichever control row button is currently
    # focused (see PlayerScreen._control_buttons/_control_focus_idx).
    # Real Kodi uses Enter to show/hide a normally-hidden OSD; this app's
    # control row has no hidden state to show/hide (it's always visible),
    # so Enter's role here is simply "confirm the row's current
    # selection" — the same meaning SELECT already has everywhere else
    # in the app, and already accepted as a synonym for MENU inside the
    # chapter overlay's own handling below.
    Qt.Key.Key_Return: InputAction.SELECT,
    Qt.Key.Key_Enter: InputAction.SELECT,
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
    # Left/Right move the control row's highlight (see PlayerScreen) —
    # deliberately NOT an instant seek shortcut anymore. A gamepad or a
    # basic remote (D-pad + Select + Back, nothing else) has no way to
    # reach seek/next/prev/speed otherwise, so those all live in the
    # always-focused control row instead; seeking is "navigate to the
    # rewind/forward-30s button, press Select", same as every other
    # control in the row, matching how Left/Right behave everywhere else
    # in this app (move a selection, never fire an instant action).
    Qt.Key.Key_Right: InputAction.RIGHT,
    Qt.Key.Key_Left: InputAction.LEFT,
    # Long seek — kept as a direct keyboard-only shortcut (F/R); there's
    # no row equivalent (a deliberate scope decision — the 30s seek
    # buttons already make seeking fully reachable without a keyboard).
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
