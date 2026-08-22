"""Smoke tests for the top-level application window (headless)."""
from __future__ import annotations

import pytest


class _FakeAudioPlayer:
    """Minimal stand-in for sixpack.player.player.AudioPlayer.

    MainWindow's real AudioPlayer wraps python-mpv, which spawns a genuine
    libmpv event thread. Constructing that for real in a test process leaves
    background threads running past test teardown and reliably aborts the
    interpreter on shutdown (observed: "Fatal Python error: Aborted" inside
    mpv's `_event_generator`). This double satisfies the same interface
    MainWindow/PlayerScreen touch during construction, so the full screen
    stack (including PlayerScreen and its signal wiring) still gets built
    and connected, without touching real mpv/libmpv.
    """

    def on_position_changed(self, cb):
        pass

    def on_state_changed(self, cb):
        pass

    def on_end_of_track(self, cb):
        pass

    def on_duration_changed(self, cb):
        pass

    def seek_back(self):
        pass

    def seek_forward(self):
        pass

    def seek_back_long(self):
        pass

    def seek_forward_long(self):
        pass

    def toggle_pause(self):
        pass

    def stop(self):
        pass

    def next_chapter(self):
        pass

    def prev_chapter(self):
        pass

    def play(self, url, start_time=0.0, auth_token=""):
        pass

    def shutdown(self):
        pass


@pytest.fixture
def window(qtbot, monkeypatch):
    """Fully-constructed MainWindow with a fake AudioPlayer (see
    _FakeAudioPlayer docstring for why the real one can't be used in tests).
    """
    from sixpack.config import AppConfig
    from sixpack.ui import app as app_module

    # Avoid constructing a real python-mpv/libmpv backend in the test
    # process (see _FakeAudioPlayer docstring).
    monkeypatch.setattr(app_module, "AudioPlayer", _FakeAudioPlayer)

    win = app_module.MainWindow(AppConfig())
    qtbot.addWidget(win)

    yield win

    # MainWindow.closeEvent() stops the AsyncWorker's background QThread;
    # without this the thread survives past the test, which reliably
    # aborts the interpreter at process exit.
    win.close()


def test_main_window_constructs_without_error(window):
    """MainWindow must build its full screen stack and signal wiring without
    raising. This guards against dangling signal connections (e.g. to a
    signal removed from a screen but left wired in app.py) that no
    screen-level unit test can catch, since MainWindow is only ever
    constructed by the real app entry point.
    """
    assert window is not None
    assert window._player_screen is not None


def test_on_track_ended_navigates_to_series_detail_with_next_focused(window, qtbot):
    """Automatic end-of-track must NOT auto-play the next book — it shows
    an up-next message, then lands on the series detail screen with the
    next book pre-focused, per this plan's end-of-book behavior change."""
    from sixpack.api.models import Series, SeriesBook, LibraryItemMedia

    media1 = LibraryItemMedia(metadata={"title": "Book 1"}, duration=100.0)
    media2 = LibraryItemMedia(metadata={"title": "Book 2"}, duration=100.0)
    b1 = SeriesBook(id="b1", libraryId="lib1", media=media1, sequence="1")
    b2 = SeriesBook(id="b2", libraryId="lib1", media=media2, sequence="2")
    series = Series(id="s1", name="A Series", books=[b1, b2])

    window._current_series = series
    window._player_screen._current_book = b1
    window._player_screen._series_books = [b1, b2]
    window._player_screen._current_index = 0

    # In real usage the user already browsed into the series detail screen
    # (which populates its item grid) before starting playback — _show_detail()
    # itself has no reload logic, so replicate that pre-existing population here.
    window._detail_screen.show_loading(series)

    # The player screen must actually be on-screen (current widget in the
    # QStackedWidget) for its child _up_next_label's isVisible() to reflect
    # setVisible(True) — a hidden ancestor keeps isVisible() False even
    # after the child's own explicit visibility flag is set.
    window._stack.setCurrentWidget(window._player_screen)

    window._on_track_ended()
    # up-next message shown synchronously; navigation happens after a timer
    assert window._player_screen._up_next_label.isVisible()

    qtbot.wait(window._UP_NEXT_DELAY_MS + 200)

    assert window._stack.currentWidget() is window._detail_screen
    assert window._detail_screen._grid._focused_index == 1  # b2 pre-focused


def test_on_track_ended_standalone_item_returns_to_browse(window, qtbot):
    """A library item played with no series/playlist context has no 'next'
    grid to return to — lands on Browse, per the spec's explicitly-flagged
    open implementation detail."""
    window._current_series = None
    window._current_playlist = None
    window._player_screen._current_book = None
    window._player_screen._current_playlist_item = None
    window._player_screen._series_books = []
    window._player_screen._playlist_items = []

    window._on_track_ended()
    qtbot.wait(window._UP_NEXT_DELAY_MS + 200)

    assert window._stack.currentWidget() is window._browse_screen
