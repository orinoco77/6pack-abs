"""Tests for FocusGrid, MediaCard, and PlayerScreen."""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch
import pytest
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QPushButton, QWidget

from sixpack.api.models import LibraryItemMedia, MediaProgress, Series, SeriesBook
from sixpack.ui.widgets.focus_grid import FocusGrid
from sixpack.ui.widgets.media_card import MediaCard


# ===========================================================================
# FocusGrid tests
# ===========================================================================

def _make_card(title: str) -> MediaCard:
    return MediaCard(title=title)


def test_focus_grid_creates_empty(qtbot):
    grid = FocusGrid(columns=3)
    qtbot.addWidget(grid)
    assert grid.item_count == 0


def test_focus_grid_add_items(qtbot):
    grid = FocusGrid(columns=3)
    qtbot.addWidget(grid)
    for i in range(5):
        grid.add_item(_make_card(f"Card {i}"))
    assert grid.item_count == 5


def test_focus_grid_clear(qtbot):
    grid = FocusGrid(columns=3)
    qtbot.addWidget(grid)
    for i in range(4):
        grid.add_item(_make_card(f"Card {i}"))
    grid.clear()
    assert grid.item_count == 0


def test_focus_grid_focus_first(qtbot):
    grid = FocusGrid(columns=3)
    qtbot.addWidget(grid)
    grid.show()
    for i in range(4):
        grid.add_item(_make_card(f"Card {i}"))
    grid.set_focus_first()
    assert grid._focused_index == 0


def test_focus_grid_focus_item_bounds(qtbot):
    grid = FocusGrid(columns=3)
    qtbot.addWidget(grid)
    grid.show()
    for i in range(3):
        grid.add_item(_make_card(f"Card {i}"))
    grid.focus_item(100)  # out of bounds — should clamp
    assert grid._focused_index == 2


def test_focus_grid_focus_item_negative(qtbot):
    grid = FocusGrid(columns=3)
    qtbot.addWidget(grid)
    grid.show()
    for i in range(3):
        grid.add_item(_make_card(f"Card {i}"))
    grid.focus_item(-1)
    assert grid._focused_index == 0


def test_focus_grid_nav_right(qtbot):
    grid = FocusGrid(columns=3)
    qtbot.addWidget(grid)
    grid.show()
    for i in range(6):
        grid.add_item(_make_card(f"Card {i}"))
    grid.focus_item(0)
    qtbot.keyClick(grid, Qt.Key.Key_Right)
    assert grid._focused_index == 1


def test_focus_grid_nav_left(qtbot):
    grid = FocusGrid(columns=3)
    qtbot.addWidget(grid)
    grid.show()
    for i in range(6):
        grid.add_item(_make_card(f"Card {i}"))
    grid.focus_item(2)
    qtbot.keyClick(grid, Qt.Key.Key_Left)
    assert grid._focused_index == 1


def test_focus_grid_nav_down(qtbot):
    grid = FocusGrid(columns=3)
    qtbot.addWidget(grid)
    grid.show()
    for i in range(6):
        grid.add_item(_make_card(f"Card {i}"))
    grid.focus_item(0)
    qtbot.keyClick(grid, Qt.Key.Key_Down)
    assert grid._focused_index == 3


def test_focus_grid_nav_up(qtbot):
    grid = FocusGrid(columns=3)
    qtbot.addWidget(grid)
    grid.show()
    for i in range(6):
        grid.add_item(_make_card(f"Card {i}"))
    grid.focus_item(3)
    qtbot.keyClick(grid, Qt.Key.Key_Up)
    assert grid._focused_index == 0


def test_focus_grid_nav_down_at_last_row(qtbot):
    grid = FocusGrid(columns=3)
    qtbot.addWidget(grid)
    grid.show()
    for i in range(3):
        grid.add_item(_make_card(f"Card {i}"))
    grid.focus_item(1)
    qtbot.keyClick(grid, Qt.Key.Key_Down)
    assert grid._focused_index == 1  # no change — no row below


def test_focus_grid_nav_up_at_first_row(qtbot):
    grid = FocusGrid(columns=3)
    qtbot.addWidget(grid)
    grid.show()
    for i in range(3):
        grid.add_item(_make_card(f"Card {i}"))
    grid.focus_item(1)
    qtbot.keyClick(grid, Qt.Key.Key_Up)
    assert grid._focused_index == 1  # no change


def test_focus_grid_enter_emits_activated(qtbot):
    grid = FocusGrid(columns=3)
    qtbot.addWidget(grid)
    grid.show()
    for i in range(3):
        grid.add_item(_make_card(f"Card {i}"))
    grid.focus_item(1)
    with qtbot.waitSignal(grid.item_activated, timeout=1000) as blocker:
        qtbot.keyClick(grid, Qt.Key.Key_Return)
    assert blocker.args[0] == 1


def test_focus_grid_empty_nav_no_crash(qtbot):
    grid = FocusGrid(columns=3)
    qtbot.addWidget(grid)
    # Should not raise with empty grid
    qtbot.keyClick(grid, Qt.Key.Key_Down)
    qtbot.keyClick(grid, Qt.Key.Key_Right)
    qtbot.keyClick(grid, Qt.Key.Key_Return)


def test_focus_grid_card_visual_focus(qtbot):
    """focus_item() sets the accent border on the target card and clears the old one."""
    from sixpack.ui import theme
    grid = FocusGrid(columns=3)
    qtbot.addWidget(grid)
    for i in range(3):
        grid.add_item(_make_card(f"Card {i}"))
    grid.focus_item(0)
    assert grid._items[0]._focused is True
    assert grid._items[1]._focused is False
    grid.focus_item(1)
    assert grid._items[0]._focused is False
    assert grid._items[1]._focused is True


def test_focus_grid_keyboard_focus_stays_on_grid(qtbot):
    """Arrow-key navigation must not move Qt keyboard focus to individual cards."""
    grid = FocusGrid(columns=3)
    qtbot.addWidget(grid)
    grid.show()
    for i in range(6):
        grid.add_item(_make_card(f"Card {i}"))
    grid.set_focus_first()
    qtbot.keyClick(grid, Qt.Key.Key_Right)
    # The grid itself must still hold focus, not a card widget
    from PyQt6.QtWidgets import QApplication
    focused = QApplication.focusWidget()
    assert focused is grid or focused is None  # None acceptable in headless


def test_focus_grid_card_activated_propagates(qtbot):
    grid = FocusGrid(columns=3)
    qtbot.addWidget(grid)
    grid.show()
    card = _make_card("Test Card")
    grid.add_item(card)

    activated_indices = []
    grid.item_activated.connect(activated_indices.append)
    card.activated.emit()
    assert activated_indices == [0]


def test_focus_grid_right_wraps(qtbot):
    grid = FocusGrid(columns=3)
    qtbot.addWidget(grid)
    grid.show()
    for i in range(3):
        grid.add_item(_make_card(f"Card {i}"))
    grid.focus_item(2)
    qtbot.keyClick(grid, Qt.Key.Key_Right)
    assert grid._focused_index == 0  # wraps to start


def test_focus_grid_scroll_area_is_transparent(qtbot):
    """Regression guard: FocusGrid's internal QScrollArea/container must be
    explicitly transparent, or a Backdrop placed behind it (DetailGridScreen)
    gets fully occluded — the exact bug that shipped once already in the
    Home/Browse redesign (theme.py's global QWidget/QScrollArea rules are
    opaque by default)."""
    grid = FocusGrid(columns=2)
    qtbot.addWidget(grid)
    assert "transparent" in grid._scroll.styleSheet()
    assert "transparent" in grid._scroll.viewport().styleSheet()
    assert "transparent" in grid._container.styleSheet()


# ===========================================================================
# MediaCard tests
# ===========================================================================

def test_media_card_creates(qtbot):
    card = MediaCard(title="Test Drama")
    qtbot.addWidget(card)
    assert card._title == "Test Drama"


def test_media_card_fixed_size(qtbot):
    from sixpack.ui import theme
    card = MediaCard(title="Test")
    qtbot.addWidget(card)
    assert card.width() == theme.CARD_WIDTH + 2 * theme.FOCUS_BORDER
    assert card.height() == theme.CARD_HEIGHT


def test_media_card_activated_on_enter(qtbot):
    card = MediaCard(title="Test")
    qtbot.addWidget(card)
    card.show()
    card.setFocus()

    with qtbot.waitSignal(card.activated, timeout=1000):
        qtbot.keyClick(card, Qt.Key.Key_Return)


def test_media_card_space_does_not_activate(qtbot):
    """Space is play/pause in Kodi — it must not activate a card."""
    card = MediaCard(title="Test")
    qtbot.addWidget(card)
    card.show()
    card.setFocus()

    with qtbot.assertNotEmitted(card.activated):
        qtbot.keyClick(card, Qt.Key.Key_Space)


def test_media_card_set_cover(qtbot):
    card = MediaCard(title="Test")
    qtbot.addWidget(card)
    pix = QPixmap(100, 100)
    pix.fill()
    card.set_cover(pix)
    assert card._pixmap is not None


def test_media_card_set_progress(qtbot):
    card = MediaCard(title="Test")
    qtbot.addWidget(card)
    pix = QPixmap(100, 100)
    pix.fill()
    card.set_cover(pix)
    card.set_progress(0.5)  # should not raise


def test_media_card_set_progress_no_cover(qtbot):
    card = MediaCard(title="Test")
    qtbot.addWidget(card)
    card.set_progress(0.7)  # no cover set — should still work


def test_media_card_progress_clamps_high(qtbot):
    card = MediaCard(title="Test")
    qtbot.addWidget(card)
    card.set_progress(2.0)  # > 1 should clamp


def test_media_card_progress_clamps_low(qtbot):
    card = MediaCard(title="Test")
    qtbot.addWidget(card)
    card.set_progress(-0.5)  # < 0 should clamp


def test_media_card_set_finished_shows_badge(qtbot):
    card = MediaCard(title="Test")
    qtbot.addWidget(card)
    assert card._finished is False
    card.set_finished(True)
    assert card._finished is True
    card.set_finished(False)
    assert card._finished is False


def test_media_card_finished_badge_paints_without_crash(qtbot):
    """Real paint, not just state — matches this codebase's pattern of
    verifying paint-level effects actually render (see task-glow-fix-report
    history in git log for why state-only assertions weren't enough once
    before)."""
    card = MediaCard(title="Test")
    qtbot.addWidget(card)
    card.set_finished(True)
    card.show()
    qtbot.waitExposed(card)
    pix = card.grab()
    assert not pix.isNull()


def test_media_card_set_focused_style(qtbot):
    from sixpack.ui import theme
    card = MediaCard(title="Test")
    qtbot.addWidget(card)
    card.set_focused(True)
    assert card._focused is True
    assert theme.ACCENT in card.styleSheet()
    card.set_focused(False)
    assert card._focused is False
    assert "transparent" in card.styleSheet()


def test_media_card_mouse_press_no_crash(qtbot):
    card = MediaCard(title="Test")
    qtbot.addWidget(card)
    card.show()
    qtbot.mouseClick(card, Qt.MouseButton.LeftButton)  # should not crash


def test_media_card_subtitle(qtbot):
    card = MediaCard(title="Drama", subtitle="Season 1")
    qtbot.addWidget(card)
    assert card._subtitle == "Season 1"


def test_media_card_no_crash_other_key(qtbot):
    card = MediaCard(title="Test")
    qtbot.addWidget(card)
    card.show()
    card.setFocus()
    qtbot.keyClick(card, Qt.Key.Key_A)  # unmapped — should not crash


def test_media_card_media_type_param(qtbot):
    card = MediaCard(title="Pod", media_type="podcast")
    qtbot.addWidget(card)
    assert card._media_type == "podcast"


def test_media_card_no_graphics_effect_ever_installed(qtbot):
    """Regression guard for the QGraphicsDropShadowEffect glow that used to
    live on `self` and was implicated (via lldb) in a Qt6.11/PyQt6
    compositor segfault. `self.graphicsEffect()` must be None at all times,
    across repeated focus/unfocus cycles."""
    card = MediaCard(title="Test")
    qtbot.addWidget(card)
    assert card.graphicsEffect() is None
    for state in (True, False, True, False):
        card.set_focused(state)
        assert card.graphicsEffect() is None


def _expected_scrim_alpha():
    from sixpack.ui import theme
    return int(round(255 * (1.0 - theme.UNFOCUSED_OPACITY)))


def test_media_card_no_graphics_effect_used_for_dim(qtbot):
    """The dim must never be a QGraphicsEffect of any kind — see
    docs/qt-graphics-effect-crash.md. No QGraphicsEffect of any kind remains
    anywhere on the card."""
    from PyQt6.QtWidgets import QGraphicsEffect
    card = MediaCard(title="Test")
    qtbot.addWidget(card)
    for state in (False, True, False):
        card.set_focused(state)
        assert card.graphicsEffect() is None
        assert card._body.graphicsEffect() is None
        assert card._scrim.graphicsEffect() is None
        assert not isinstance(card._scrim, QGraphicsEffect)


def test_media_card_unfocus_installs_dim(qtbot):
    card = MediaCard(title="Test")
    qtbot.addWidget(card)
    card.set_focused(True)
    card.set_focused(False)
    assert card._scrim.isVisibleTo(card._body)
    assert card._scrim.color().alpha() == _expected_scrim_alpha()


def test_media_card_never_focused_still_dims(qtbot):
    """Regression: set_focused(False) must dim unconditionally, even when
    the card was never previously focused (the common case for sibling
    cards in a grid)."""
    card = MediaCard(title="Test")
    qtbot.addWidget(card)
    card.set_focused(False)  # never previously focused
    assert card._scrim.isVisibleTo(card._body)
    assert card._scrim.color().alpha() == _expected_scrim_alpha()


def test_media_card_default_construction_dims(qtbot):
    """Regression: a freshly constructed MediaCard on which set_focused()
    is NEVER called must already be dimmed to UNFOCUSED_OPACITY. In real
    usage (FocusGrid.focus_item / BrowseScreen._set_grid_focus), only the
    previously- and newly-focused cards ever get a set_focused() call —
    every other sibling in a grid sits at its __init__-time default for
    its entire lifetime."""
    card = MediaCard(title="Test")
    qtbot.addWidget(card)
    # No set_focused() call at all.
    assert card._scrim.isVisibleTo(card._body)
    assert card._scrim.color().alpha() == _expected_scrim_alpha()


def test_media_card_default_construction_then_focus_true(qtbot):
    """A freshly constructed (now dim-by-default) card must still focus
    correctly: set_focused(True) removes the dim scrim."""
    card = MediaCard(title="Test")
    qtbot.addWidget(card)
    card.set_focused(True)
    assert not card._scrim.isVisibleTo(card._body)
    assert card._scrim.color().alpha() == 0


def test_media_card_scrim_is_non_interactive_and_covers_body(qtbot):
    from PyQt6.QtCore import Qt
    card = MediaCard(title="Test")
    qtbot.addWidget(card)
    card.show()
    qtbot.waitExposed(card)
    assert card._scrim.testAttribute(
        Qt.WidgetAttribute.WA_TransparentForMouseEvents
    )
    assert card._scrim.parent() is card._body
    assert card._scrim.size() == card._body.size()


@pytest.mark.parametrize("iteration", range(180))
def test_media_card_high_churn_no_crash(qtbot, iteration):
    """Regression test: many distinct MediaCards doing focus churn used to
    segfault deep in Qt's compositor once churn crossed ~100-150 instances
    within one process — see docs/qt-graphics-effect-crash.md. The current
    design uses zero QGraphicsEffects per card: both the focus glow and the
    dim are plain painted widgets/paintEvent overrides. This test exercises
    that at the volume that used to trigger the crash.
    """
    grid = FocusGrid(columns=4)
    qtbot.addWidget(grid)
    cards = [MediaCard(title=f"Card {i}") for i in range(4)]
    for c in cards:
        grid.add_item(c)
    grid.show()

    for idx in range(4):
        grid.focus_item(idx)
    for idx in reversed(range(4)):
        grid.focus_item(idx)
    for c in cards:
        c.set_focused(False)
    for c in cards:
        c.set_focused(True)
        c.set_focused(False)

    from PyQt6.QtWidgets import QApplication
    QApplication.processEvents()
    grid.close()
    grid.deleteLater()
    QApplication.processEvents()


# ===========================================================================
# PlayerScreen tests
# ===========================================================================

class MockAudioPlayer:
    """Test double for AudioPlayer."""

    def __init__(self):
        self._position_cbs = []
        self._state_cbs = []
        self._eof_cbs = []
        self._duration_cbs = []
        self.paused = False
        self.toggle_count = 0
        self.seek_forward_count = 0
        self.seek_back_count = 0
        self.seek_forward_long_count = 0
        self.seek_back_long_count = 0
        self.stop_count = 0
        self.next_chapter_count = 0
        self.prev_chapter_count = 0

    def on_position_changed(self, cb):
        self._position_cbs.append(cb)

    def on_state_changed(self, cb):
        self._state_cbs.append(cb)

    def on_end_of_track(self, cb):
        self._eof_cbs.append(cb)

    def on_duration_changed(self, cb):
        self._duration_cbs.append(cb)

    def toggle_pause(self):
        self.toggle_count += 1

    def stop(self):
        self.stop_count += 1

    def seek_forward(self):
        self.seek_forward_count += 1

    def seek_back(self):
        self.seek_back_count += 1

    def seek_forward_long(self):
        self.seek_forward_long_count += 1

    def seek_back_long(self):
        self.seek_back_long_count += 1

    def next_chapter(self):
        self.next_chapter_count += 1

    def prev_chapter(self):
        self.prev_chapter_count += 1

    def play(self, url, start_time=0.0, auth_token=""):
        pass

    def fire_position(self, value):
        for cb in self._position_cbs:
            cb(value)

    def fire_state(self, state):
        for cb in self._state_cbs:
            cb(state)

    def fire_eof(self):
        for cb in self._eof_cbs:
            cb()

    def fire_duration(self, value):
        for cb in self._duration_cbs:
            cb(value)


def _make_player_series():
    media = LibraryItemMedia(metadata={"title": "Episode 1"}, duration=1800.0)
    book = SeriesBook(id="b1", libraryId="lib1", media=media, sequence="1")
    series = Series(id="s1", name="The Archers", books=[book])
    return series, book


def test_player_screen_creates(qtbot):
    from sixpack.ui.screens.player import PlayerScreen
    mock_player = MockAudioPlayer()
    screen = PlayerScreen(mock_player)
    qtbot.addWidget(screen)


def test_player_screen_enter_key_activates_default_focused_play_pause(qtbot):
    """Enter/Return now activates whichever control row button is
    currently focused (see PlayerScreen._control_buttons), rather than
    Kodi's "show OSD" behavior -- this app's row has no hidden OSD to
    show, it's always visible, so Enter's role here is "confirm the
    row's current selection" like every other action. Play/pause is the
    row's default landing spot, so Enter triggers it immediately unless
    focus has been moved elsewhere first."""
    from sixpack.ui.screens.player import PlayerScreen
    mock_player = MockAudioPlayer()
    screen = PlayerScreen(mock_player)
    qtbot.addWidget(screen)
    screen.show()
    screen.setFocus()
    qtbot.keyClick(screen, Qt.Key.Key_Return)
    assert mock_player.toggle_count == 1


def test_player_screen_play_pause_key(qtbot):
    from sixpack.ui.screens.player import PlayerScreen
    mock_player = MockAudioPlayer()
    screen = PlayerScreen(mock_player)
    qtbot.addWidget(screen)
    screen.show()
    screen.setFocus()
    qtbot.keyClick(screen, Qt.Key.Key_Space)
    assert mock_player.toggle_count == 1


def test_player_screen_p_key(qtbot):
    from sixpack.ui.screens.player import PlayerScreen
    mock_player = MockAudioPlayer()
    screen = PlayerScreen(mock_player)
    qtbot.addWidget(screen)
    screen.show()
    screen.setFocus()
    qtbot.keyClick(screen, Qt.Key.Key_P)
    assert mock_player.toggle_count == 1


def test_player_screen_right_key_moves_focus_not_seek(qtbot):
    """Left/Right now move the control row's highlight rather than
    instantly seeking -- a gamepad or a basic remote (D-pad + Select +
    Back, nothing else) has no other way to reach seek/next/prev/speed
    at all. Seeking now requires navigating to the rewind/forward-30s
    button and pressing Select, like every other control in the row."""
    from sixpack.ui.screens.player import PlayerScreen
    mock_player = MockAudioPlayer()
    screen = PlayerScreen(mock_player)
    qtbot.addWidget(screen)
    screen.show()
    screen.setFocus()
    qtbot.keyClick(screen, Qt.Key.Key_Right)
    assert mock_player.seek_forward_count == 0
    assert screen._control_buttons[screen._control_focus_idx] is screen._fwd_btn


def test_player_screen_select_on_forward_button_seeks_forward(qtbot):
    from sixpack.ui.screens.player import PlayerScreen
    mock_player = MockAudioPlayer()
    screen = PlayerScreen(mock_player)
    qtbot.addWidget(screen)
    screen.show()
    screen.setFocus()
    qtbot.keyClick(screen, Qt.Key.Key_Right)  # play -> forward-30s
    qtbot.keyClick(screen, Qt.Key.Key_Return)  # select
    assert mock_player.seek_forward_count == 1


def test_player_screen_left_key_moves_focus_not_seek(qtbot):
    from sixpack.ui.screens.player import PlayerScreen
    mock_player = MockAudioPlayer()
    screen = PlayerScreen(mock_player)
    qtbot.addWidget(screen)
    screen.show()
    screen.setFocus()
    qtbot.keyClick(screen, Qt.Key.Key_Left)
    assert mock_player.seek_back_count == 0
    assert screen._control_buttons[screen._control_focus_idx] is screen._rew_btn


def test_player_screen_select_on_rewind_button_seeks_back(qtbot):
    from sixpack.ui.screens.player import PlayerScreen
    mock_player = MockAudioPlayer()
    screen = PlayerScreen(mock_player)
    qtbot.addWidget(screen)
    screen.show()
    screen.setFocus()
    qtbot.keyClick(screen, Qt.Key.Key_Left)  # play -> rewind-30s
    qtbot.keyClick(screen, Qt.Key.Key_Return)  # select
    assert mock_player.seek_back_count == 1


def test_player_screen_next_chapter_key(qtbot):
    from sixpack.ui.screens.player import PlayerScreen
    mock_player = MockAudioPlayer()
    screen = PlayerScreen(mock_player)
    qtbot.addWidget(screen)
    screen.show()
    screen.setFocus()
    qtbot.keyClick(screen, Qt.Key.Key_Period)
    assert mock_player.next_chapter_count == 1


def test_player_screen_prev_chapter_key(qtbot):
    from sixpack.ui.screens.player import PlayerScreen
    mock_player = MockAudioPlayer()
    screen = PlayerScreen(mock_player)
    qtbot.addWidget(screen)
    screen.show()
    screen.setFocus()
    qtbot.keyClick(screen, Qt.Key.Key_Comma)
    assert mock_player.prev_chapter_count == 1


def test_player_screen_back_key(qtbot):
    from sixpack.ui.screens.player import PlayerScreen
    mock_player = MockAudioPlayer()
    screen = PlayerScreen(mock_player)
    qtbot.addWidget(screen)
    screen.show()
    screen.setFocus()

    with qtbot.waitSignal(screen.back_requested, timeout=1000):
        qtbot.keyClick(screen, Qt.Key.Key_Escape)


def test_player_screen_next_item_key(qtbot):
    from sixpack.ui.screens.player import PlayerScreen
    mock_player = MockAudioPlayer()
    screen = PlayerScreen(mock_player)
    qtbot.addWidget(screen)
    screen.show()
    screen.setFocus()

    with qtbot.waitSignal(screen.next_item, timeout=1000):
        qtbot.keyClick(screen, Qt.Key.Key_N)


def test_player_screen_prev_item_key(qtbot):
    from sixpack.ui.screens.player import PlayerScreen
    mock_player = MockAudioPlayer()
    screen = PlayerScreen(mock_player)
    qtbot.addWidget(screen)
    screen.show()
    screen.setFocus()

    with qtbot.waitSignal(screen.prev_item, timeout=1000):
        qtbot.keyClick(screen, Qt.Key.Key_B)


def test_player_screen_page_up_next_item(qtbot):
    """Kodi: PageUp = next chapter in FullscreenVideo."""
    from sixpack.ui.screens.player import PlayerScreen
    mock_player = MockAudioPlayer()
    screen = PlayerScreen(mock_player)
    qtbot.addWidget(screen)
    screen.show()
    screen.setFocus()

    with qtbot.waitSignal(screen.next_item, timeout=1000):
        qtbot.keyClick(screen, Qt.Key.Key_PageUp)


def test_player_screen_page_down_prev_item(qtbot):
    """Kodi: PageDown = prev chapter in FullscreenVideo."""
    from sixpack.ui.screens.player import PlayerScreen
    mock_player = MockAudioPlayer()
    screen = PlayerScreen(mock_player)
    qtbot.addWidget(screen)
    screen.show()
    screen.setFocus()

    with qtbot.waitSignal(screen.prev_item, timeout=1000):
        qtbot.keyClick(screen, Qt.Key.Key_PageDown)


def test_player_screen_x_stops_and_backs(qtbot):
    """Kodi: X = stop playback and return to library."""
    from sixpack.ui.screens.player import PlayerScreen
    mock_player = MockAudioPlayer()
    screen = PlayerScreen(mock_player)
    qtbot.addWidget(screen)
    screen.show()
    screen.setFocus()

    with qtbot.waitSignal(screen.back_requested, timeout=1000):
        qtbot.keyClick(screen, Qt.Key.Key_X)
    assert mock_player.stop_count == 1


def test_player_screen_f_seeks_long_forward(qtbot):
    """Kodi: F = fast forward (long seek)."""
    from sixpack.ui.screens.player import PlayerScreen
    mock_player = MockAudioPlayer()
    screen = PlayerScreen(mock_player)
    qtbot.addWidget(screen)
    screen.show()
    screen.setFocus()
    qtbot.keyClick(screen, Qt.Key.Key_F)
    assert mock_player.seek_forward_long_count == 1


def test_player_screen_r_seeks_long_back(qtbot):
    """Kodi: R = rewind (long seek back)."""
    from sixpack.ui.screens.player import PlayerScreen
    mock_player = MockAudioPlayer()
    screen = PlayerScreen(mock_player)
    qtbot.addWidget(screen)
    screen.show()
    screen.setFocus()
    qtbot.keyClick(screen, Qt.Key.Key_R)
    assert mock_player.seek_back_long_count == 1


def test_player_screen_backspace_goes_back(qtbot):
    """Kodi: Backspace = go back (same as Escape)."""
    from sixpack.ui.screens.player import PlayerScreen
    mock_player = MockAudioPlayer()
    screen = PlayerScreen(mock_player)
    qtbot.addWidget(screen)
    screen.show()
    screen.setFocus()

    with qtbot.waitSignal(screen.back_requested, timeout=1000):
        qtbot.keyClick(screen, Qt.Key.Key_Backspace)


def test_player_screen_transport_buttons(qtbot):
    from sixpack.ui.screens.player import PlayerScreen
    mock_player = MockAudioPlayer()
    screen = PlayerScreen(mock_player)
    qtbot.addWidget(screen)
    screen.show()

    screen._play_btn.click()
    assert mock_player.toggle_count == 1

    screen._fwd_btn.click()
    assert mock_player.seek_forward_count == 1

    screen._rew_btn.click()
    assert mock_player.seek_back_count == 1


def test_player_screen_back_button(qtbot):
    from sixpack.ui.screens.player import PlayerScreen
    mock_player = MockAudioPlayer()
    screen = PlayerScreen(mock_player)
    qtbot.addWidget(screen)

    with qtbot.waitSignal(screen.back_requested, timeout=1000):
        screen._back_btn.click()


def test_player_screen_next_prev_buttons(qtbot):
    from sixpack.ui.screens.player import PlayerScreen
    mock_player = MockAudioPlayer()
    screen = PlayerScreen(mock_player)
    qtbot.addWidget(screen)

    with qtbot.waitSignal(screen.next_item, timeout=1000):
        screen._next_btn.click()

    with qtbot.waitSignal(screen.prev_item, timeout=1000):
        screen._prev_btn.click()


def test_player_screen_update_position(qtbot):
    from sixpack.ui.screens.player import PlayerScreen
    mock_player = MockAudioPlayer()
    screen = PlayerScreen(mock_player)
    qtbot.addWidget(screen)
    screen._duration = 3600.0
    screen._update_position(300.0)
    assert "5:00" in screen._elapsed_label.text()
    assert screen._progress_bar.value() > 0


def test_player_screen_update_duration(qtbot):
    from sixpack.ui.screens.player import PlayerScreen
    mock_player = MockAudioPlayer()
    screen = PlayerScreen(mock_player)
    qtbot.addWidget(screen)
    screen._update_duration(7200.0)
    assert screen._duration == 7200.0


def test_player_screen_state_playing(qtbot):
    from sixpack.ui import theme
    from sixpack.ui.screens.player import PlayerScreen
    mock_player = MockAudioPlayer()
    screen = PlayerScreen(mock_player)
    qtbot.addWidget(screen)
    screen._update_state("playing")
    assert screen._play_btn.text() == theme.ICON_PAUSE


def test_player_screen_state_paused(qtbot):
    from sixpack.ui import theme
    from sixpack.ui.screens.player import PlayerScreen
    mock_player = MockAudioPlayer()
    screen = PlayerScreen(mock_player)
    qtbot.addWidget(screen)
    screen._update_state("paused")
    assert screen._play_btn.text() == theme.ICON_PLAY


def test_player_screen_sync_progress(qtbot):
    from sixpack.ui.screens.player import PlayerScreen
    mock_player = MockAudioPlayer()
    screen = PlayerScreen(mock_player)
    qtbot.addWidget(screen)
    screen._item_id = "b1"
    screen._duration = 1800.0
    screen._position = 900.0

    with qtbot.waitSignal(screen.progress_update, timeout=1000) as blocker:
        screen._sync_progress()

    item_id, current_time, duration, is_finished, episode_id = blocker.args
    assert item_id == "b1"
    assert current_time == 900.0
    assert duration == 1800.0
    assert is_finished is False
    assert episode_id == ""


def test_player_screen_sync_progress_finished(qtbot):
    from sixpack.ui.screens.player import PlayerScreen
    mock_player = MockAudioPlayer()
    screen = PlayerScreen(mock_player)
    qtbot.addWidget(screen)
    screen._item_id = "b1"
    screen._duration = 1800.0
    screen._position = 1795.0  # within 10s of end

    with qtbot.waitSignal(screen.progress_update, timeout=1000) as blocker:
        screen._sync_progress()

    _, _, _, is_finished, _ = blocker.args
    assert is_finished is True


def test_player_screen_sync_progress_no_duration(qtbot):
    from sixpack.ui.screens.player import PlayerScreen
    mock_player = MockAudioPlayer()
    screen = PlayerScreen(mock_player)
    qtbot.addWidget(screen)
    screen._item_id = "b1"
    screen._duration = 0.0

    with qtbot.assertNotEmitted(screen.progress_update):
        screen._sync_progress()


def test_player_screen_set_audio_tracks(qtbot):
    from sixpack.ui import theme
    from sixpack.ui.screens.player import PlayerScreen
    mock_player = MockAudioPlayer()
    screen = PlayerScreen(mock_player)
    qtbot.addWidget(screen)
    screen.set_audio_tracks("http://abs.test/file.mp3", 0.0, "token")
    assert screen._play_btn.text() == theme.ICON_PAUSE


def test_player_fmt_time_seconds():
    from sixpack.ui.screens.player import _fmt_time
    assert _fmt_time(0) == "0:00"
    assert _fmt_time(65) == "1:05"
    assert _fmt_time(3661) == "1:01:01"


def test_player_fmt_time_negative():
    from sixpack.ui.screens.player import _fmt_time
    assert _fmt_time(-5) == "0:00"


def test_player_fmt_time_inf():
    from sixpack.ui.screens.player import _fmt_time
    import math
    assert _fmt_time(math.inf) == "0:00"


# ===========================================================================
# HeroBackdrop tests
# ===========================================================================


def test_hero_backdrop_creates(qtbot):
    from sixpack.ui.widgets.hero_backdrop import HeroBackdrop
    hb = HeroBackdrop()
    qtbot.addWidget(hb)
    assert hb.backdrop is not None


def test_hero_backdrop_set_title_and_subtitle(qtbot):
    from sixpack.ui.widgets.hero_backdrop import HeroBackdrop
    hb = HeroBackdrop()
    qtbot.addWidget(hb)
    hb.set_title("My Series")
    hb.set_subtitle("Episode 1")
    assert hb._hero_title.text() == "My Series"
    assert hb._hero_sub.text() == "Episode 1"


def test_hero_backdrop_resize_positions_children(qtbot):
    from sixpack.ui.widgets.hero_backdrop import HeroBackdrop
    hb = HeroBackdrop()
    qtbot.addWidget(hb)
    hb.show()
    hb.resize(800, 600)
    assert hb.backdrop.geometry() == hb.rect()
    assert hb._hero.geometry().height() == HeroBackdrop.HERO_H
    assert hb._hero.geometry().width() == 800
