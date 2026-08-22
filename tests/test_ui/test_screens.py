"""UI screen tests using pytest-qt (headless)."""
from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from sixpack.api.models import (
    Chapter,
    LibraryItemMedia,
    MediaProgress,
    Series,
    SeriesBook,
)
from sixpack.ui.screens.login import LoginScreen
from sixpack.ui.screens.series_detail import SeriesDetailScreen


# ---- SplashScreen ----

def test_splash_screen_creates(qtbot):
    from sixpack.ui.screens.splash import SplashScreen
    from PyQt6.QtWidgets import QLabel
    screen = SplashScreen()
    qtbot.addWidget(screen)
    labels = screen.findChildren(QLabel)
    assert any("SixPack" in lbl.text() for lbl in labels)


def test_splash_screen_set_status(qtbot):
    from sixpack.ui.screens.splash import SplashScreen
    screen = SplashScreen()
    qtbot.addWidget(screen)
    screen.set_status("Checking saved session…")
    assert screen._status_label.text() == "Checking saved session…"


def test_splash_screen_default_status(qtbot):
    from sixpack.ui.screens.splash import SplashScreen
    screen = SplashScreen()
    qtbot.addWidget(screen)
    assert screen._status_label.text() == "Connecting…"


# ---- LoginScreen ----

def test_login_screen_creates(qtbot):
    screen = LoginScreen()
    qtbot.addWidget(screen)
    assert screen._url_input is not None
    assert screen._user_input is not None
    assert screen._pass_input is not None


def test_login_screen_error_hidden_initially(qtbot):
    screen = LoginScreen()
    qtbot.addWidget(screen)
    # isHidden() checks the widget's own state regardless of parent visibility
    assert screen._error_label.isHidden()


def test_login_screen_show_error(qtbot):
    screen = LoginScreen()
    qtbot.addWidget(screen)
    screen.show_error("Bad credentials")
    assert not screen._error_label.isHidden()
    assert "Bad credentials" in screen._error_label.text()


def test_login_screen_set_prefill(qtbot):
    screen = LoginScreen()
    qtbot.addWidget(screen)
    screen.set_prefill("http://abs.local:13378", "adam")
    assert screen._url_input.text() == "http://abs.local:13378"
    assert screen._user_input.text() == "adam"


def test_login_emits_signal_on_connect(qtbot):
    screen = LoginScreen()
    qtbot.addWidget(screen)
    screen._url_input.setText("http://abs.local:13378")
    screen._user_input.setText("adam")
    screen._pass_input.setText("secret")

    with qtbot.waitSignal(screen.login_requested, timeout=1000) as blocker:
        screen._login_btn.click()

    url, username, password = blocker.args
    assert url == "http://abs.local:13378"
    assert username == "adam"
    assert password == "secret"


def test_login_no_emit_without_url(qtbot):
    screen = LoginScreen()
    qtbot.addWidget(screen)
    screen._url_input.setText("")
    screen._user_input.setText("adam")

    with qtbot.assertNotEmitted(screen.login_requested):
        screen._login_btn.click()
    assert not screen._error_label.isHidden()


def test_login_no_emit_without_username(qtbot):
    screen = LoginScreen()
    qtbot.addWidget(screen)
    screen._url_input.setText("http://abs.local")
    screen._user_input.setText("")

    with qtbot.assertNotEmitted(screen.login_requested):
        screen._login_btn.click()


def test_login_button_disabled_during_connect(qtbot):
    screen = LoginScreen()
    qtbot.addWidget(screen)
    screen._url_input.setText("http://abs.local")
    screen._user_input.setText("adam")
    screen._pass_input.setText("pass")

    emitted = []
    screen.login_requested.connect(lambda *a: emitted.append(a))
    screen._login_btn.click()
    # After emitting, button should be disabled
    assert not screen._login_btn.isEnabled()
    # Reset state
    screen.show_error("failed")
    assert screen._login_btn.isEnabled()


# ---- LoginScreen: pairing flow + on-screen-keyboard fallback ----
#
# These tests never call screen.show(), so isVisible() would report False
# for every widget regardless of state (a widget's effective visibility
# requires its whole ancestor chain, including the top-level window, to
# have been shown — see QWidget.isVisible() docs). isHidden() only reflects
# the widget's OWN explicit hide()/setVisible(False) call, independent of
# ancestor state, which is exactly this file's existing convention for
# _error_label above — so these tests check isHidden() on the two view
# CONTAINERS (_pairing_view / _keyboard_form), which are what
# _use_keyboard_fallback()/start_pairing() actually toggle.

def test_login_starts_on_pairing_view_by_default(qtbot):
    screen = LoginScreen()
    qtbot.addWidget(screen)
    screen.start_pairing()
    try:
        assert not screen._pairing_view.isHidden()
        assert screen._keyboard_form.isHidden()
        assert screen._pairing_server is not None
    finally:
        screen.stop_pairing()


def test_login_stop_pairing_tears_down_server(qtbot):
    screen = LoginScreen()
    qtbot.addWidget(screen)
    screen.start_pairing()
    server = screen._pairing_server
    screen.stop_pairing()
    assert screen._pairing_server is None
    # The underlying HTTPServer must actually be torn down, not just
    # dereferenced — confirm the port is no longer accepting connections.
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        result = s.connect_ex(("127.0.0.1", server.port))
        assert result != 0  # connection refused/failed — server is down


def test_login_stop_pairing_idempotent_when_never_started(qtbot):
    screen = LoginScreen()
    qtbot.addWidget(screen)
    screen.stop_pairing()  # must not raise
    assert screen._pairing_server is None


def test_login_pairing_success_emits_pairing_login_succeeded(qtbot):
    screen = LoginScreen()
    qtbot.addWidget(screen)
    screen.start_pairing()
    try:
        with qtbot.waitSignal(screen.pairing_login_succeeded, timeout=2000) as blocker:
            # Simulate the pairing server's background-thread callback
            # exactly the way PairingServer itself would call it.
            screen._pairing_server.on_success("http://abs.test", "alice", "tok123")
        assert blocker.args == ["http://abs.test", "alice", "tok123"]
    finally:
        screen.stop_pairing()


def test_login_use_remote_instead_switches_to_keyboard_form(qtbot):
    screen = LoginScreen()
    qtbot.addWidget(screen)
    screen.start_pairing()
    try:
        screen._use_keyboard_fallback()
        assert not screen._keyboard_form.isHidden()
        assert screen._pairing_view.isHidden()
    finally:
        screen.stop_pairing()


def test_login_keyboard_fallback_typing_and_submit_emits_login_requested(qtbot):
    screen = LoginScreen()
    qtbot.addWidget(screen)
    screen.start_pairing()
    try:
        screen._use_keyboard_fallback()
        screen._url_input.setText("http://abs.test:13378")
        screen._user_input.setText("alice")
        screen._pass_input.setText("hunter2")

        signals = []
        screen.login_requested.connect(lambda *a: signals.append(a))
        screen._keyboard.done_pressed.emit()
        assert signals == [("http://abs.test:13378", "alice", "hunter2")]
    finally:
        screen.stop_pairing()


def test_login_keyboard_key_presses_type_into_active_field(qtbot):
    """key_pressed/backspace_pressed append to / delete from whichever
    field last received real Qt focus (the active-field mechanism)."""
    screen = LoginScreen()
    qtbot.addWidget(screen)
    screen.show()
    qtbot.waitExposed(screen)
    screen.start_pairing()
    try:
        screen._use_keyboard_fallback()
        # _use_keyboard_fallback() defaults the active field to the URL
        # field (also gives it initial focus/active-field status).
        for ch in "abs":
            screen._keyboard.key_pressed.emit(ch)
        assert screen._url_input.text() == "abs"
        screen._keyboard.backspace_pressed.emit()
        assert screen._url_input.text() == "ab"

        # Switching real Qt focus to another field (simulating a
        # click/Select on it) retargets subsequent keyboard input there.
        screen._user_input.setFocus()
        qtbot.waitUntil(lambda: screen._active_field is screen._user_input, timeout=1000)
        screen._keyboard.key_pressed.emit("x")
        assert screen._user_input.text() == "x"
    finally:
        screen.stop_pairing()


def test_login_pairing_bind_failure_falls_back_to_keyboard(qtbot, monkeypatch):
    """If PairingServer.start() can't bind a port, start_pairing() must not
    show the (now broken) pairing view — it should fall back to the
    keyboard view automatically with an inline note."""
    from sixpack.pairing.server import PairingServer

    def _raise_oserror(self):
        raise OSError("bind failed")

    monkeypatch.setattr(PairingServer, "start", _raise_oserror)

    screen = LoginScreen()
    qtbot.addWidget(screen)
    screen.start_pairing()
    try:
        assert screen._pairing_server is None
        assert not screen._keyboard_form.isHidden()
        assert screen._pairing_view.isHidden()
        assert not screen._pairing_unavailable_label.isHidden()
        assert screen._pairing_unavailable_label.text()
    finally:
        screen.stop_pairing()


def test_login_show_error_still_works_unchanged(qtbot):
    screen = LoginScreen()
    qtbot.addWidget(screen)
    screen.show_error("Login failed: bad credentials")
    assert not screen._error_label.isHidden()
    assert "Login failed" in screen._error_label.text()


def test_login_set_prefill_still_works_unchanged(qtbot):
    screen = LoginScreen()
    qtbot.addWidget(screen)
    screen.set_prefill("http://abs.test", "alice")
    assert screen._url_input.text() == "http://abs.test"
    assert screen._user_input.text() == "alice"


# ---- SeriesDetailScreen ----

def _make_series() -> Series:
    media1 = LibraryItemMedia(metadata={"title": "Episode 1"}, duration=1800.0)
    media2 = LibraryItemMedia(metadata={"title": "Episode 2"}, duration=3600.0)
    b1 = SeriesBook(id="b1", libraryId="lib1", media=media1, sequence="1")
    b2 = SeriesBook(id="b2", libraryId="lib1", media=media2, sequence="2")
    return Series(id="s1", name="My Drama Series", books=[b1, b2])


def test_detail_screen_creates(qtbot):
    screen = SeriesDetailScreen()
    qtbot.addWidget(screen)
    assert screen._grid is not None


def test_detail_screen_load(qtbot):
    screen = SeriesDetailScreen()
    qtbot.addWidget(screen)
    series = _make_series()
    screen.load(series, {}, "http://localhost", "tok")
    assert screen._hero_backdrop._hero_title.text() == "My Drama Series"
    assert screen._grid.item_count == 2


def test_detail_screen_back_signal(qtbot):
    from sixpack.input.keyboard import key_to_action  # noqa: F401 — confirm import path used by screen
    screen = SeriesDetailScreen()
    qtbot.addWidget(screen)
    screen.load(_make_series(), {}, "http://localhost", "tok")
    screen.show()
    with qtbot.waitSignal(screen.back_requested, timeout=1000):
        qtbot.keyClick(screen, Qt.Key.Key_Backspace)


def test_detail_screen_item_emits_episode_activated(qtbot):
    screen = SeriesDetailScreen()
    qtbot.addWidget(screen)
    series = _make_series()
    screen.load(series, {}, "http://localhost", "tok")
    with qtbot.waitSignal(screen.episode_activated, timeout=1000) as blocker:
        screen._grid.item_activated.emit(0)
    assert blocker.args[0].id == "b1"


def test_detail_show_loading_renders_episodes(qtbot):
    screen = SeriesDetailScreen()
    qtbot.addWidget(screen)
    screen.show_loading(_make_series(), "http://localhost", "tok")
    assert screen._grid.item_count == 2


def test_detail_update_progress_refreshes_in_place(qtbot):
    screen = SeriesDetailScreen()
    qtbot.addWidget(screen)
    series = _make_series()
    screen.load(series, {}, "http://localhost", "tok")
    card_before = screen._grid._items[0]
    screen.update_progress({"b1": MediaProgress(currentTime=1800.0, duration=1800.0, isFinished=True)})
    assert screen._grid._items[0] is card_before


def test_detail_resume_index_all_finished(qtbot):
    screen = SeriesDetailScreen()
    qtbot.addWidget(screen)
    series = _make_series()
    progress = {
        "b1": MediaProgress(currentTime=1800.0, duration=1800.0, isFinished=True),
        "b2": MediaProgress(currentTime=3600.0, duration=3600.0, isFinished=True),
    }
    screen.load(series, progress, "http://localhost", "tok")
    assert screen._grid._focused_index == 0  # _find_resume_index falls back to 0


def test_detail_screen_focus_item_by_key(qtbot):
    screen = SeriesDetailScreen()
    qtbot.addWidget(screen)
    screen.load(_make_series(), {}, "http://localhost", "tok")
    screen.focus_item_by_key("b2")
    assert screen._grid._focused_index == 1


def test_detail_screen_hero_subtitle_shows_episode_number_and_title(qtbot):
    screen = SeriesDetailScreen()
    qtbot.addWidget(screen)
    media = LibraryItemMedia(metadata={"title": "The Vanishing Point"}, duration=1800.0)
    book = SeriesBook(id="bx", libraryId="lib1", media=media, sequence="3")
    series = Series(id="sx", name="Some Series", books=[book])
    screen.load(series, {}, "http://localhost", "tok")
    assert screen._hero_backdrop._hero_sub.text() == "Episode 3 · The Vanishing Point"


def test_detail_screen_card_subtitle_is_short_form_not_duplicated(qtbot):
    """Regression test: Task 4 once made the hero-subtitle fix leak into the
    card's own subtitle, duplicating the (unelided) title under every card.
    """
    screen = SeriesDetailScreen()
    qtbot.addWidget(screen)
    media = LibraryItemMedia(metadata={"title": "The Vanishing Point"}, duration=1800.0)
    book = SeriesBook(id="bx", libraryId="lib1", media=media, sequence="3")
    series = Series(id="sx", name="Some Series", books=[book])
    screen.load(series, {}, "http://localhost", "tok")
    assert screen._grid._items[0]._subtitle == "Episode 3"


def test_detail_screen_hero_subtitle_no_sequence_falls_back_to_title(qtbot):
    screen = SeriesDetailScreen()
    qtbot.addWidget(screen)
    media = LibraryItemMedia(metadata={"title": "Standalone Book"}, duration=1800.0)
    book = SeriesBook(id="bx", libraryId="lib1", media=media)  # no sequence -> None (model default)
    series = Series(id="sx", name="Some Series", books=[book])
    screen.load(series, {}, "http://localhost", "tok")
    assert screen._hero_backdrop._hero_sub.text() == "Standalone Book"


def test_series_detail_screen_backdrop_not_occluded(qtbot):
    """Regression test for the occlusion bug class Task 2 verified only via
    a one-off, uncommitted script: an opaque scroll/container widget hiding
    Backdrop's content. Task 2 moved Backdrop from a direct screen child to
    a grandchild inside HeroBackdrop — exactly the kind of structural
    change that could silently reintroduce this. Samples a point below the
    hero band but above the first card — squarely inside FocusGrid's scroll
    viewport/container, which must stay transparent for Backdrop to show
    through.
    """
    from PyQt6.QtGui import QColor, QPixmap

    from sixpack.ui import theme

    screen = SeriesDetailScreen()
    qtbot.addWidget(screen)
    screen.resize(800, 600)
    screen.load(_make_series(), {}, "http://localhost", "tok")
    screen._hero_backdrop.backdrop.show_color(QColor(255, 0, 0))
    screen.show()
    qtbot.waitExposed(screen)

    pix = QPixmap(screen.size())
    screen.render(pix)
    img = pix.toImage()

    x, y, height = 400, 160, screen.height()
    color = img.pixelColor(x, y)

    # Backdrop.show_color paints a vertical gradient from red.darker(150)
    # at y=0 to theme.BG at the bottom (see backdrop.py). Verify the
    # sampled pixel actually matches that ramp — not black (fully
    # occluded), not raw #FF0000 (would mean darker()/gradient isn't being
    # applied), and not a flat opaque widget color like theme.SURFACE.
    dark_red = QColor(255, 0, 0).darker(150)
    bg = QColor(theme.BG)
    fraction = y / height
    expected_r = dark_red.red() + (bg.red() - dark_red.red()) * fraction
    expected_g = dark_red.green() + (bg.green() - dark_red.green()) * fraction
    expected_b = dark_red.blue() + (bg.blue() - dark_red.blue()) * fraction

    assert abs(color.red() - expected_r) <= 10
    assert abs(color.green() - expected_g) <= 10
    assert abs(color.blue() - expected_b) <= 10


def test_detail_screen_item_progress_fraction(qtbot):
    """_item_progress computes current_time / duration, keyed by item.id."""
    screen = SeriesDetailScreen()
    qtbot.addWidget(screen)
    book = _make_series().sorted_books[0]  # id "b1", duration 1800.0
    prog = MediaProgress(currentTime=900.0, duration=1800.0, isFinished=False)
    fraction, finished = screen._item_progress(book, {book.id: prog})
    assert abs(fraction - 0.5) < 1e-6
    assert finished is False


def test_detail_screen_item_progress_finished_is_zero_fraction(qtbot):
    """A finished item reports fraction 0.0 regardless of current_time."""
    screen = SeriesDetailScreen()
    qtbot.addWidget(screen)
    book = _make_series().sorted_books[0]
    prog = MediaProgress(currentTime=1800.0, duration=1800.0, isFinished=True)
    fraction, finished = screen._item_progress(book, {book.id: prog})
    assert fraction == 0.0
    assert finished is True


# ---- ChapterSelectScreen ----

def _make_chapters():
    return [
        Chapter(id=0, start=0.0, end=1500.0, title="Part One: The Arrival"),
        Chapter(id=1, start=1500.0, end=3000.0, title="Part Two: The Attack"),
        Chapter(id=2, start=3000.0, end=4200.0, title="Part Three: Aftermath"),
    ]


def _make_box_set_book():
    from sixpack.api.models import Chapter
    media = LibraryItemMedia(
        metadata={"title": "Invasion of Earth"},
        duration=4200.0,
        chapters=_make_chapters(),
    )
    return SeriesBook(id="bx1", libraryId="lib1", media=media, sequence="1")


def test_chapter_screen_creates(qtbot):
    from sixpack.ui.screens.chapter_select import ChapterSelectScreen
    screen = ChapterSelectScreen()
    qtbot.addWidget(screen)
    assert screen._list is not None


def test_chapter_screen_load(qtbot):
    from sixpack.ui.screens.chapter_select import ChapterSelectScreen
    screen = ChapterSelectScreen()
    qtbot.addWidget(screen)
    book = _make_box_set_book()
    screen.load(book, _make_chapters(), None)
    assert screen._list.count() == 3
    assert screen._hero_backdrop._hero_title.text() == "Invasion of Earth"
    assert "3 chapters" in screen._hero_backdrop._hero_sub.text()


def test_chapter_screen_hero_shows_book_title(qtbot):
    from sixpack.ui.screens.chapter_select import ChapterSelectScreen
    screen = ChapterSelectScreen()
    qtbot.addWidget(screen)
    book = _make_box_set_book()
    screen.load(book, _make_chapters(), None, "http://localhost", "tok")
    assert screen._hero_backdrop._hero_title.text() == book.title


def test_chapter_select_screen_backdrop_not_occluded(qtbot):
    """Regression test for the occlusion bug class Task 2 verified only via
    a one-off, uncommitted script: an opaque scroll/container widget hiding
    Backdrop's content. Task 2 moved Backdrop from a direct screen child to
    a grandchild inside HeroBackdrop — exactly the kind of structural
    change that could silently reintroduce this.

    Unlike FocusGrid, ChapterSelectScreen's QListWidget rows start
    immediately below the hero band with no extra margin, so this samples
    below the last chapter row instead, where the list viewport's
    transparent background should let Backdrop show through.
    """
    from PyQt6.QtGui import QColor, QPixmap

    from sixpack.ui import theme
    from sixpack.ui.screens.chapter_select import ChapterSelectScreen

    screen = ChapterSelectScreen()
    qtbot.addWidget(screen)
    screen.resize(800, 600)
    screen.load(_make_box_set_book(), _make_chapters(), None)
    screen._hero_backdrop.backdrop.show_color(QColor(255, 0, 0))
    screen.show()
    qtbot.waitExposed(screen)

    pix = QPixmap(screen.size())
    screen.render(pix)
    img = pix.toImage()

    # 3 chapter rows (68px + spacing each) end well before y=400, leaving
    # empty (transparent) list viewport below them.
    x, y, height = 400, 400, screen.height()
    color = img.pixelColor(x, y)

    # Backdrop.show_color paints a vertical gradient from red.darker(150)
    # at y=0 to theme.BG at the bottom (see backdrop.py). Verify the
    # sampled pixel actually matches that ramp — not black (fully
    # occluded), not raw #FF0000, and not a flat opaque widget color like
    # theme.SURFACE (ChapterItem's own row background).
    dark_red = QColor(255, 0, 0).darker(150)
    bg = QColor(theme.BG)
    fraction = y / height
    expected_r = dark_red.red() + (bg.red() - dark_red.red()) * fraction
    expected_g = dark_red.green() + (bg.green() - dark_red.green()) * fraction
    expected_b = dark_red.blue() + (bg.blue() - dark_red.blue()) * fraction

    assert abs(color.red() - expected_r) <= 10
    assert abs(color.green() - expected_g) <= 10
    assert abs(color.blue() - expected_b) <= 10


def test_chapter_screen_play_signal(qtbot):
    from sixpack.ui.screens.chapter_select import ChapterSelectScreen
    screen = ChapterSelectScreen()
    qtbot.addWidget(screen)
    book = _make_box_set_book()
    screen.load(book, _make_chapters(), None)

    signals = []
    screen.play_requested.connect(lambda b, t: signals.append((b, t)))
    screen._list.itemActivated.emit(screen._list.item(1))  # Part Two starts at 1500.0

    assert len(signals) == 1
    assert signals[0][0] is book
    assert signals[0][1] == 1500.0


def test_chapter_screen_enter_on_real_focus_target_activates_chapter(qtbot):
    """Regression: QListWidget's own default Key_Return handling doesn't
    reliably fire itemActivated in this app's configuration, so if the list
    (rather than the screen) held real keyboard focus, pressing Enter on a
    real TV remote was silently swallowed — nothing happened, and the user
    never reached the player. This sends Enter to whatever Qt says actually
    has focus after the screen is shown (not directly to the screen or the
    list, which would bypass the real routing this bug lived in), exactly
    matching how a real key event is delivered."""
    from sixpack.ui.screens.chapter_select import ChapterSelectScreen
    screen = ChapterSelectScreen()
    qtbot.addWidget(screen)
    book = _make_box_set_book()
    screen.load(book, _make_chapters(), None)
    screen.show()
    qtbot.waitExposed(screen)

    # screen.focusWidget() (the locally-focused descendant within this
    # widget's own window) rather than QApplication.focusWidget() (the
    # OS-level active window's focus target) — the latter is flaky in a
    # test session sharing one QApplication across hundreds of tests, but
    # in the real single-window app the two are equivalent, so this is
    # still a faithful reproduction of real key delivery.
    focus_target = screen.focusWidget()
    assert focus_target is screen  # the screen itself owns focus, not _list

    with qtbot.waitSignal(screen.play_requested, timeout=1000) as blocker:
        qtbot.keyClick(focus_target, Qt.Key.Key_Return)

    assert blocker.args[0] is book
    assert blocker.args[1] == 0.0  # first chapter, starts at 0.0


def test_chapter_screen_down_arrow_moves_current_row(qtbot):
    from sixpack.ui.screens.chapter_select import ChapterSelectScreen
    screen = ChapterSelectScreen()
    qtbot.addWidget(screen)
    screen.load(_make_box_set_book(), _make_chapters(), None)
    screen.show()
    qtbot.waitExposed(screen)

    assert screen._list.currentRow() == 0
    qtbot.keyClick(screen, Qt.Key.Key_Down)
    assert screen._list.currentRow() == 1
    qtbot.keyClick(screen, Qt.Key.Key_Up)
    assert screen._list.currentRow() == 0


def test_chapter_screen_back_signal(qtbot):
    from sixpack.ui.screens.chapter_select import ChapterSelectScreen
    screen = ChapterSelectScreen()
    qtbot.addWidget(screen)
    screen.load(_make_box_set_book(), _make_chapters(), None)

    with qtbot.waitSignal(screen.back_requested, timeout=1000):
        qtbot.keyClick(screen, Qt.Key.Key_Escape)


def test_chapter_screen_resume_index_in_progress(qtbot):
    """Resume index points to the chapter containing current_time."""
    from sixpack.ui.screens.chapter_select import ChapterSelectScreen
    screen = ChapterSelectScreen()
    qtbot.addWidget(screen)
    book = _make_box_set_book()
    # current_time = 2000s → inside Part Two (1500–3000)
    prog = MediaProgress(libraryItemId="bx1", currentTime=2000.0, duration=4200.0)
    screen.load(book, _make_chapters(), prog)
    assert screen._list.currentRow() == 1


def test_chapter_screen_resume_index_finished(qtbot):
    """Finished book restarts from chapter 0."""
    from sixpack.ui.screens.chapter_select import ChapterSelectScreen
    screen = ChapterSelectScreen()
    qtbot.addWidget(screen)
    book = _make_box_set_book()
    prog = MediaProgress(libraryItemId="bx1", currentTime=4200.0, duration=4200.0, isFinished=True)
    screen.load(book, _make_chapters(), prog)
    assert screen._list.currentRow() == 0


def test_chapter_status_finished_book(qtbot):
    """All chapters show as finished when the book is finished."""
    from sixpack.ui.screens.chapter_select import ChapterSelectScreen, _chapter_status
    from sixpack.api.models import Chapter
    ch = Chapter(id=0, start=0.0, end=1500.0, title="Part One")
    assert _chapter_status(ch, 4200.0, is_finished=True) == "finished"
    assert _chapter_status(ch, 0.0, is_finished=True) == "finished"


def test_chapter_status_in_progress():
    from sixpack.ui.screens.chapter_select import _chapter_status
    from sixpack.api.models import Chapter
    ch = Chapter(id=1, start=1500.0, end=3000.0, title="Part Two")
    assert _chapter_status(ch, 2000.0, is_finished=False) == "in_progress"
    assert _chapter_status(ch, 3001.0, is_finished=False) == "finished"
    assert _chapter_status(ch, 1000.0, is_finished=False) == "unstarted"


def test_chapter_fraction_not_in_progress_is_zero():
    """Any status other than in_progress (unstarted, finished) reports 0.0."""
    from sixpack.ui.screens.chapter_select import _chapter_fraction
    from sixpack.api.models import Chapter
    ch = Chapter(id=0, start=0.0, end=1500.0, title="Part One")
    assert _chapter_fraction(ch, current_time=0.0, status="unstarted") == 0.0
    assert _chapter_fraction(ch, current_time=1500.0, status="finished") == 0.0


def test_chapter_fraction_in_progress_computes_correctly():
    from sixpack.ui.screens.chapter_select import _chapter_fraction
    from sixpack.api.models import Chapter
    ch = Chapter(id=1, start=1500.0, end=3000.0, title="Part Two")
    # 375s into a 1500s chapter that starts at t=1500 -> 25%
    assert abs(_chapter_fraction(ch, current_time=1875.0, status="in_progress") - 0.25) < 1e-6


def test_chapter_fraction_zero_span_is_zero():
    """A zero-length chapter (start == end) must not raise ZeroDivisionError."""
    from sixpack.ui.screens.chapter_select import _chapter_fraction
    from sixpack.api.models import Chapter
    ch = Chapter(id=0, start=60.0, end=60.0, title="Ch (zero-length)")
    assert _chapter_fraction(ch, current_time=60.0, status="in_progress") == 0.0


def test_chapter_screen_load_from_library_item(qtbot):
    from sixpack.ui.screens.chapter_select import ChapterSelectScreen
    from sixpack.api.models import LibraryItem, LibraryItemMedia

    screen = ChapterSelectScreen()
    qtbot.addWidget(screen)
    li = LibraryItem(
        id="li1", libraryId="lib1", mediaType="book",
        media=LibraryItemMedia(
            metadata={"title": "Doctor Who: Invasion", "authorName": "BBC"},
            duration=4200.0, chapters=_make_chapters(),
        ),
    )
    screen.load_from_library_item(li, _make_chapters(), None)
    assert screen._list.count() == 3
    assert screen._hero_backdrop._hero_title.text() == "Doctor Who: Invasion"
    assert "3 chapters" in screen._hero_backdrop._hero_sub.text()
    assert screen._library_item is li
    assert screen._book is None
    assert screen._playlist_item is None


def test_chapter_screen_library_item_play_signal(qtbot):
    from sixpack.ui.screens.chapter_select import ChapterSelectScreen
    from sixpack.api.models import LibraryItem, LibraryItemMedia

    screen = ChapterSelectScreen()
    qtbot.addWidget(screen)
    li = LibraryItem(
        id="li1", libraryId="lib1", mediaType="book",
        media=LibraryItemMedia(metadata={"title": "Book A"}, duration=3000.0),
    )
    screen.load_from_library_item(li, _make_chapters(), None)

    play_signals, lib_signals = [], []
    screen.play_requested.connect(lambda b, t: play_signals.append((b, t)))
    screen.library_item_play_requested.connect(lambda item, t: lib_signals.append((item, t)))
    screen._list.itemActivated.emit(screen._list.item(0))

    assert len(play_signals) == 0
    assert len(lib_signals) == 1
    assert lib_signals[0][0] is li
    assert lib_signals[0][1] == 0.0


def test_chapter_screen_load_clears_library_item(qtbot):
    from sixpack.ui.screens.chapter_select import ChapterSelectScreen
    from sixpack.api.models import LibraryItem, LibraryItemMedia

    screen = ChapterSelectScreen()
    qtbot.addWidget(screen)
    li = LibraryItem(
        id="li1", libraryId="lib1", mediaType="book",
        media=LibraryItemMedia(metadata={"title": "Book"}, duration=1000.0),
    )
    screen.load_from_library_item(li, _make_chapters(), None)
    assert screen._library_item is li

    screen.load(_make_box_set_book(), _make_chapters(), None)
    assert screen._library_item is None


def test_chapter_screen_load_from_library_item_resume(qtbot):
    from sixpack.ui.screens.chapter_select import ChapterSelectScreen
    from sixpack.api.models import LibraryItem, LibraryItemMedia, MediaProgress

    screen = ChapterSelectScreen()
    qtbot.addWidget(screen)
    li = LibraryItem(
        id="li1", libraryId="lib1", mediaType="book",
        media=LibraryItemMedia(metadata={"title": "Book"}, duration=4200.0),
    )
    prog = MediaProgress(libraryItemId="li1", currentTime=2000.0, duration=4200.0)
    screen.load_from_library_item(li, _make_chapters(), prog)
    assert screen._list.currentRow() == 1  # chapter at 1500–3000


class _FakeCoverCache:
    """Captures fetch/fetch_backdrop calls instead of invoking them, so the
    test can assert exactly how many times each was invoked without a real
    network-backed CoverCache. Same pattern as
    tests/test_ui/test_browse_screen.py's _FakeCoverCache (~line 893).
    """

    def __init__(self):
        self.fetch_calls = []
        self.fetch_backdrop_calls = []

    def fetch(self, url, token, callback):
        self.fetch_calls.append((url, token, callback))

    def fetch_backdrop(self, url, token, callback):
        self.fetch_backdrop_calls.append((url, token, callback))


def test_chapter_screen_backdrop_fetched_once_not_per_focus_change(qtbot):
    """ChapterSelectScreen fetches the book's backdrop cover exactly ONCE
    per load() call and does NOT re-fetch it as focus moves between chapter
    rows — all chapters share the same book cover, so per-row re-fetching
    would be pure waste (see chapter_select.py's module docstring and
    _load_backdrop). This exercises the real production codepath: app.py
    always constructs ChapterSelectScreen with a real CoverCache, and this
    behavior was previously only checked via throwaway scripts outside the
    test suite.
    """
    from sixpack.ui.screens.chapter_select import ChapterSelectScreen

    fake_cache = _FakeCoverCache()
    screen = ChapterSelectScreen(cover_cache=fake_cache)
    qtbot.addWidget(screen)
    book = _make_box_set_book()
    screen.load(book, _make_chapters(), None, "http://localhost", "tok")

    assert len(fake_cache.fetch_backdrop_calls) == 1

    # Simulate focus moving across every chapter row.
    for row in range(screen._list.count()):
        screen._list.setCurrentRow(row)

    assert len(fake_cache.fetch_backdrop_calls) == 1


def test_chapter_screen_stale_color_callback_is_dropped(qtbot):
    """_color_cb's dominant-color fetch is async and has no key check of its
    own (unlike _backdrop_cb, which passes key=k into Backdrop.show_image,
    letting Backdrop's own set_expected_key guard drop it). If this screen
    instance is reused for a second, different book before the first book's
    color fetch resolves — a real race, since this screen is constructed
    once and reused across load() calls — the stale callback must not paint
    a color for a book that's no longer showing. Uses a fake CoverCache that
    captures callbacks without invoking them, so both the stale and current
    callback can be fired in a controlled order.
    """
    from PyQt6.QtGui import QPixmap

    from sixpack.ui.screens.chapter_select import ChapterSelectScreen

    fake_cache = _FakeCoverCache()
    screen = ChapterSelectScreen(cover_cache=fake_cache)
    qtbot.addWidget(screen)

    book_a = _make_box_set_book()  # id="bx1"
    screen.load(book_a, _make_chapters(), None, "http://localhost", "tok")
    assert len(fake_cache.fetch_calls) == 1
    stale_color_cb = fake_cache.fetch_calls[0][2]

    media_b = LibraryItemMedia(
        metadata={"title": "A Different Book"}, duration=1000.0, chapters=_make_chapters(),
    )
    book_b = SeriesBook(id="bx2", libraryId="lib1", media=media_b)
    screen.load(book_b, _make_chapters(), None, "http://localhost", "tok")
    assert len(fake_cache.fetch_calls) == 2
    current_color_cb = fake_cache.fetch_calls[1][2]

    calls = []
    screen._hero_backdrop.backdrop.show_color = lambda color: calls.append(color)

    # Stale callback (book_a) resolving after focus already moved to book_b
    # must be dropped — not paint a color at all.
    stale_color_cb(QPixmap())
    assert calls == []

    # The current book's callback must still apply normally.
    current_color_cb(QPixmap())
    assert len(calls) == 1


def test_chapter_screen_backdrop_image_shown_blocks_late_color_reset(qtbot):
    """Regression test for the same-key race Task 6 didn't cover: fetch()
    and fetch_backdrop() can resolve at different speeds for the SAME book
    (e.g. the raw cover was evicted from CoverCache but the backdrop JPEG
    wasn't — the backdrop file is always written after its raw cover, so
    it's always newer under eviction pressure). If `_backdrop_cb` fires
    FIRST and starts showing the real image, a later same-key `_color_cb`
    must not call show_color and hard-reset the Backdrop back to a flat
    gradient over the already-shown image.
    """
    from PyQt6.QtGui import QPixmap

    from sixpack.ui.screens.chapter_select import ChapterSelectScreen

    fake_cache = _FakeCoverCache()
    screen = ChapterSelectScreen(cover_cache=fake_cache)
    qtbot.addWidget(screen)

    book = _make_box_set_book()
    screen.load(book, _make_chapters(), None, "http://localhost", "tok")
    assert len(fake_cache.fetch_calls) == 1
    assert len(fake_cache.fetch_backdrop_calls) == 1
    color_cb = fake_cache.fetch_calls[0][2]
    backdrop_cb = fake_cache.fetch_backdrop_calls[0][2]

    color_calls = []
    screen._hero_backdrop.backdrop.show_color = lambda color: color_calls.append(color)
    image_calls = []
    screen._hero_backdrop.backdrop.show_image = lambda pm, key=None: image_calls.append((pm, key))

    # Backdrop image resolves FIRST (e.g. a cache hit on the backdrop JPEG),
    # then the dominant-color fetch resolves LATER for the SAME key.
    backdrop_cb(QPixmap())
    assert len(image_calls) == 1

    color_cb(QPixmap())
    assert color_calls == []


# ---- Config ----

def test_config_save_load(tmp_path, monkeypatch):
    from sixpack.config import AppConfig, ServerConfig, CONFIG_FILE, CONFIG_DIR
    monkeypatch.setattr("sixpack.config.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("sixpack.config.CONFIG_FILE", tmp_path / "config.json")

    cfg = AppConfig()
    cfg.add_or_update_server(ServerConfig(name="Home", url="http://abs.local", token="tok1"))
    cfg.save()

    loaded = AppConfig.load()
    assert len(loaded.servers) == 1
    assert loaded.servers[0].url == "http://abs.local"
    assert loaded.servers[0].token == "tok1"
    assert loaded.active_server_index == 0


def test_config_active_server_none():
    from sixpack.config import AppConfig
    cfg = AppConfig()
    assert cfg.active_server is None


def test_config_update_existing_server(tmp_path, monkeypatch):
    monkeypatch.setattr("sixpack.config.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("sixpack.config.CONFIG_FILE", tmp_path / "config.json")

    from sixpack.config import AppConfig, ServerConfig
    cfg = AppConfig()
    cfg.add_or_update_server(ServerConfig(name="Home", url="http://abs.local", token="old"))
    cfg.add_or_update_server(ServerConfig(name="Home", url="http://abs.local", token="new"))
    assert len(cfg.servers) == 1
    assert cfg.servers[0].token == "new"


def test_config_load_corrupt_file(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text("not json{{{{")
    monkeypatch.setattr("sixpack.config.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("sixpack.config.CONFIG_FILE", cfg_file)

    from sixpack.config import AppConfig
    cfg = AppConfig.load()
    assert cfg.servers == []


def test_config_active_server_index_clamp():
    from sixpack.config import AppConfig, ServerConfig
    cfg = AppConfig(
        servers=[ServerConfig(name="A", url="http://a")],
        active_server_index=999,
    )
    assert cfg.active_server is not None
    assert cfg.active_server.url == "http://a"


def test_config_last_library_id_persists(tmp_path, monkeypatch):
    monkeypatch.setattr("sixpack.config.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("sixpack.config.CONFIG_FILE", tmp_path / "config.json")

    from sixpack.config import AppConfig, ServerConfig
    cfg = AppConfig()
    cfg.add_or_update_server(
        ServerConfig(name="Home", url="http://abs.local", token="tok", last_library_id="lib42")
    )
    cfg.save()

    loaded = AppConfig.load()
    assert loaded.servers[0].last_library_id == "lib42"


def test_config_last_library_id_defaults_empty(tmp_path, monkeypatch):
    """Old config files without last_library_id load without error."""
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text('{"servers": [{"name": "H", "url": "http://x", "token": "t"}], "active_server_index": 0}')
    monkeypatch.setattr("sixpack.config.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("sixpack.config.CONFIG_FILE", cfg_file)

    from sixpack.config import AppConfig
    cfg = AppConfig.load()
    assert cfg.servers[0].last_library_id == ""
