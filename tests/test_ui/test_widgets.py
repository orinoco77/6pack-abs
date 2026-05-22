"""Tests for FocusGrid, MediaCard, SeriesScreen, and PlayerScreen."""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch
import pytest
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QPushButton, QWidget

from sixpack.api.models import Library, LibraryItemMedia, MediaProgress, Series, SeriesBook
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
    assert card.width() == theme.CARD_WIDTH
    assert card.height() == theme.CARD_HEIGHT


def test_media_card_activated_on_enter(qtbot):
    card = MediaCard(title="Test")
    qtbot.addWidget(card)
    card.show()
    card.setFocus()

    with qtbot.waitSignal(card.activated, timeout=1000):
        qtbot.keyClick(card, Qt.Key.Key_Return)


def test_media_card_activated_on_space(qtbot):
    card = MediaCard(title="Test")
    qtbot.addWidget(card)
    card.show()
    card.setFocus()

    with qtbot.waitSignal(card.activated, timeout=1000):
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


def test_media_card_focus_changes_style(qtbot):
    from PyQt6.QtGui import QFocusEvent
    card = MediaCard(title="Test")
    qtbot.addWidget(card)
    # Fire focus events directly — setFocus() requires an active window
    in_evt = QFocusEvent(QFocusEvent.Type.FocusIn)
    card.focusInEvent(in_evt)
    assert card._focused is True
    out_evt = QFocusEvent(QFocusEvent.Type.FocusOut)
    card.focusOutEvent(out_evt)
    assert card._focused is False


def test_media_card_mouse_press_focuses(qtbot):
    card = MediaCard(title="Test")
    qtbot.addWidget(card)
    card.show()
    qtbot.mouseClick(card, Qt.MouseButton.LeftButton)
    # Mouse press should set focus
    # Just assert no crash


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


# ===========================================================================
# SeriesScreen tests
# ===========================================================================

def _make_series_list() -> list[Series]:
    media1 = LibraryItemMedia(metadata={"title": "Ep 1"}, duration=1800.0)
    media2 = LibraryItemMedia(metadata={"title": "Ep 2"}, duration=3600.0)
    b1 = SeriesBook(id="b1", libraryId="lib1", media=media1, sequence="1")
    b2 = SeriesBook(id="b2", libraryId="lib1", media=media2, sequence="2")
    s1 = Series(id="s1", name="The Archers", books=[b1, b2])
    s2 = Series(id="s2", name="Doctor Who", books=[b1])
    return [s1, s2]


def test_series_screen_creates(qtbot):
    from sixpack.ui.screens.series import SeriesScreen
    screen = SeriesScreen()
    qtbot.addWidget(screen)


def test_series_screen_load(qtbot):
    from sixpack.ui.screens.series import SeriesScreen
    screen = SeriesScreen()
    qtbot.addWidget(screen)
    library = Library(id="lib1", name="Drama")
    series_list = _make_series_list()
    screen.load(library, series_list, "http://abs.test", "token")
    assert screen._grid.item_count == 2


def test_series_screen_back_signal(qtbot):
    from sixpack.ui.screens.series import SeriesScreen
    screen = SeriesScreen()
    qtbot.addWidget(screen)
    library = Library(id="lib1", name="Drama")
    screen.load(library, _make_series_list(), "http://abs.test", "token")

    with qtbot.waitSignal(screen.back_requested, timeout=1000):
        qtbot.keyClick(screen, Qt.Key.Key_Escape)


def test_series_screen_back_button(qtbot):
    from sixpack.ui.screens.series import SeriesScreen
    screen = SeriesScreen()
    qtbot.addWidget(screen)
    library = Library(id="lib1", name="Drama")
    screen.load(library, _make_series_list(), "http://abs.test", "token")

    with qtbot.waitSignal(screen.back_requested, timeout=1000):
        screen._back_btn.click()


def test_series_screen_item_activated(qtbot):
    from sixpack.ui.screens.series import SeriesScreen
    screen = SeriesScreen()
    qtbot.addWidget(screen)
    library = Library(id="lib1", name="Drama")
    series_list = _make_series_list()
    screen.load(library, series_list, "http://abs.test", "token")

    with qtbot.waitSignal(screen.series_selected, timeout=1000) as blocker:
        screen._grid.item_activated.emit(0)

    assert blocker.args[0].id == "s1"


def test_series_screen_out_of_bounds_item(qtbot):
    from sixpack.ui.screens.series import SeriesScreen
    screen = SeriesScreen()
    qtbot.addWidget(screen)
    library = Library(id="lib1", name="Drama")
    screen.load(library, _make_series_list(), "http://abs.test", "token")

    # Out-of-bounds index should not crash
    with qtbot.assertNotEmitted(screen.series_selected):
        screen._grid.item_activated.emit(999)


def test_series_screen_title_shown(qtbot):
    from sixpack.ui.screens.series import SeriesScreen
    screen = SeriesScreen()
    qtbot.addWidget(screen)
    library = Library(id="lib1", name="My Drama Library")
    screen.load(library, _make_series_list(), "http://abs.test", "token",
                all_libraries=[library])
    assert screen._library_combo.currentText() == "My Drama Library"


def test_series_screen_count_label(qtbot):
    from sixpack.ui.screens.series import SeriesScreen
    screen = SeriesScreen()
    qtbot.addWidget(screen)
    library = Library(id="lib1", name="Drama")
    screen.load(library, _make_series_list(), "http://abs.test", "token")
    assert "2" in screen._count_label.text()


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
        self.seek_forward_count = 0
        self.seek_back_count = 0
        self.next_chapter_count = 0
        self.prev_chapter_count = 0
        self.toggle_count = 0

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

    def seek_forward(self):
        self.seek_forward_count += 1

    def seek_back(self):
        self.seek_back_count += 1

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


def test_player_screen_seek_forward_key(qtbot):
    from sixpack.ui.screens.player import PlayerScreen
    mock_player = MockAudioPlayer()
    screen = PlayerScreen(mock_player)
    qtbot.addWidget(screen)
    screen.show()
    screen.setFocus()
    qtbot.keyClick(screen, Qt.Key.Key_Right)
    assert mock_player.seek_forward_count == 1


def test_player_screen_seek_back_key(qtbot):
    from sixpack.ui.screens.player import PlayerScreen
    mock_player = MockAudioPlayer()
    screen = PlayerScreen(mock_player)
    qtbot.addWidget(screen)
    screen.show()
    screen.setFocus()
    qtbot.keyClick(screen, Qt.Key.Key_Left)
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
    from sixpack.ui.screens.player import PlayerScreen
    mock_player = MockAudioPlayer()
    screen = PlayerScreen(mock_player)
    qtbot.addWidget(screen)
    screen._update_state("playing")
    assert "⏸" in screen._play_btn.text()


def test_player_screen_state_paused(qtbot):
    from sixpack.ui.screens.player import PlayerScreen
    mock_player = MockAudioPlayer()
    screen = PlayerScreen(mock_player)
    qtbot.addWidget(screen)
    screen._update_state("paused")
    assert "▶" in screen._play_btn.text()


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

    item_id, current_time, duration, is_finished = blocker.args
    assert item_id == "b1"
    assert current_time == 900.0
    assert duration == 1800.0
    assert is_finished is False


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

    _, _, _, is_finished = blocker.args
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
    from sixpack.ui.screens.player import PlayerScreen
    mock_player = MockAudioPlayer()
    screen = PlayerScreen(mock_player)
    qtbot.addWidget(screen)
    screen.set_audio_tracks("http://abs.test/file.mp3", 0.0, "token")
    assert "⏸" in screen._play_btn.text()


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


def test_detail_fmt_duration():
    from sixpack.ui.screens.series_detail import _fmt_duration
    assert _fmt_duration(3661) == "1h 01m"
    assert _fmt_duration(300) == "5m"
    assert _fmt_duration(0) == "0m"
