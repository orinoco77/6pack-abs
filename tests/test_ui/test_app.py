"""Smoke tests for the top-level application window (headless)."""
from __future__ import annotations

import httpx
import pytest
import respx

from sixpack.api.client import ABSClient


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
    _FakeAudioPlayer docstring for why the real one can't be used in tests)
    and a stubbed update check (so tests never hit the real GitHub API --
    mirrors the AudioPlayer stub for the same "no real external resources
    in tests" reason).
    """
    from sixpack.config import AppConfig
    from sixpack.ui import app as app_module

    # Avoid constructing a real python-mpv/libmpv backend in the test
    # process (see _FakeAudioPlayer docstring).
    monkeypatch.setattr(app_module, "AudioPlayer", _FakeAudioPlayer)

    async def _fake_fetch_latest_release():
        return None

    monkeypatch.setattr(app_module, "fetch_latest_release", _fake_fetch_latest_release)

    win = app_module.MainWindow(AppConfig())
    qtbot.addWidget(win)
    # _try_autologin() no longer runs synchronously inside __init__ -- it
    # now only runs once the (stubbed, but still genuinely asynchronous,
    # real-background-thread) check_update round-trip completes. Wait for
    # that to settle before handing the window to a test, so every
    # existing assumption about post-construction state (previously true
    # synchronously) still holds.
    qtbot.waitUntil(lambda: win._stack.currentWidget() is not win._splash_screen, timeout=2000)

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


# ---- gamepad dispatch ----
#
# GamepadListener's callback fires from a background per-device thread in
# real use; _on_gamepad_action must marshal to the GUI thread rather than
# touching any QWidget/QApplication state directly. These tests call it
# from the test's own (GUI) thread, which still goes through the real
# QueuedConnection dispatch -- qtbot.waitUntil pumps the event loop so the
# queued slot actually runs before asserting.

def test_gamepad_listener_started_on_construction(window):
    assert window._gamepad is not None


def test_gamepad_action_dispatches_synthetic_key_to_focused_widget(window, qtbot):
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QLineEdit

    from sixpack.input.actions import InputAction

    target = QLineEdit()
    qtbot.addWidget(target)
    target.show()
    target.setFocus()
    qtbot.waitUntil(lambda: target.hasFocus(), timeout=2000)

    received = []
    target.keyPressEvent = lambda event: received.append(event.key())

    window._on_gamepad_action(InputAction.SELECT, True)

    qtbot.waitUntil(lambda: len(received) == 1, timeout=2000)
    assert received[0] == Qt.Key.Key_Return


def test_gamepad_action_release_dispatches_key_release(window, qtbot):
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QLineEdit

    from sixpack.input.actions import InputAction

    target = QLineEdit()
    qtbot.addWidget(target)
    target.show()
    target.setFocus()
    qtbot.waitUntil(lambda: target.hasFocus(), timeout=2000)

    received = []
    target.keyReleaseEvent = lambda event: received.append(event.key())

    window._on_gamepad_action(InputAction.SELECT, False)

    qtbot.waitUntil(lambda: len(received) == 1, timeout=2000)
    assert received[0] == Qt.Key.Key_Return


def test_gamepad_action_unmapped_is_noop(window, qtbot):
    """MENU has no synthesizable key (see gamepad.py's _build_button_map
    comment) -- dispatching it must not raise or affect focus."""
    from sixpack.input.actions import InputAction

    window._on_gamepad_action(InputAction.MENU, True)
    qtbot.wait(50)  # let any (unexpected) queued dispatch settle
    # No assertion beyond "did not raise" -- there is nothing to observe
    # for a correctly-dropped unmapped action.


def test_gamepad_stopped_on_close(window, monkeypatch):
    stopped = []
    monkeypatch.setattr(window._gamepad, "stop", lambda: stopped.append(True))
    window.close()
    assert stopped == [True]


# ---- _async_get_libraries: exclude libraries with no playable audio ----

def _library_payload(lib_id="lib1", name="Audiobooks"):
    return {"id": lib_id, "name": name, "mediaType": "book", "displayOrder": 1}


@pytest.mark.asyncio
async def test_async_get_libraries_excludes_library_with_no_audio(window):
    """A library whose stats report zero duration and zero audio tracks
    (e.g. an all-epub library — Audiobookshelf's library-level `mediaType`
    is "book" for both audiobook and ebook-only libraries, so it can't be
    used to tell them apart; per-library /stats is the cheap signal that
    can) must not appear in the list handed to the browse screen."""
    window._server_url = "http://abs.test"
    window._token = "tok"
    window._client = ABSClient(window._server_url, token=window._token)
    async with respx.mock(base_url="http://abs.test") as mock:
        mock.get("/api/libraries").mock(
            return_value=httpx.Response(
                200,
                json={
                    "libraries": [
                        _library_payload("lib-audio", "Audiobooks"),
                        _library_payload("lib-ebooks", "eBooks"),
                    ]
                },
            )
        )
        mock.get("/api/libraries/lib-audio/stats").mock(
            return_value=httpx.Response(
                200, json={"totalDuration": 123456.0, "numAudioTracks": 42}
            )
        )
        mock.get("/api/libraries/lib-ebooks/stats").mock(
            return_value=httpx.Response(200, json={"totalDuration": 0, "numAudioTracks": 0})
        )
        result = await window._async_get_libraries()

    assert [lib.id for lib in result] == ["lib-audio"]


@pytest.mark.asyncio
async def test_async_get_libraries_keeps_library_on_stats_fetch_failure(window):
    """A transient stats-fetch failure for one library must not hide it —
    fail open rather than risk hiding a real, playable library."""
    window._server_url = "http://abs.test"
    window._token = "tok"
    window._client = ABSClient(window._server_url, token=window._token)
    async with respx.mock(base_url="http://abs.test") as mock:
        mock.get("/api/libraries").mock(
            return_value=httpx.Response(
                200, json={"libraries": [_library_payload("lib-flaky", "Flaky")]}
            )
        )
        mock.get("/api/libraries/lib-flaky/stats").mock(
            return_value=httpx.Response(500, text="Internal Error")
        )
        result = await window._async_get_libraries()

    assert [lib.id for lib in result] == ["lib-flaky"]


# ---- browse cache: instant first paint + save-after-fetch ----

def test_prime_browse_from_cache_shows_browse_before_network_result(window, tmp_path):
    """A cached library list must show up immediately — before any worker
    result arrives — so a returning user isn't stuck waiting on the
    network just to see their library sidebar again."""
    from sixpack.api.models import Library
    from sixpack.ui.browse_cache import BrowseCache

    window._browse_cache = BrowseCache(cache_dir=tmp_path)
    window._server_url = "http://abs.test"
    window._token = "tok"
    window._browse_cache.save_libraries(
        "http://abs.test", [Library(id="lib1", name="Cached Lib", mediaType="book")]
    )

    window._prime_browse_from_cache()

    assert window._stack.currentWidget() is window._browse_screen
    assert window._current_library.id == "lib1"
    assert [lib.id for lib in window._browse_screen._libraries] == ["lib1"]


def test_prime_browse_from_cache_does_not_dispatch_a_network_fetch(window, tmp_path, monkeypatch):
    """Regression test: priming from cache must be a pure disk read. If it
    also called _fetch_browse_content() (which always dispatches a real
    network fetch, by design, so normal library switches stay fresh),
    the initial library's browse content would be fetched over the
    network TWICE on every cache-primed load — once from priming, once
    from the real "libraries"/"autologin" result that follows right
    after. Observed live: duplicate items/personalized/series/playlists
    requests in the network log on startup."""
    from sixpack.api.models import Library, LibraryItem, LibraryItemMedia
    from sixpack.ui.browse_cache import BrowseCache
    from sixpack.ui.screens.browse import RowType

    window._browse_cache = BrowseCache(cache_dir=tmp_path)
    window._server_url = "http://abs.test"
    window._token = "tok"
    window._browse_cache.save_libraries(
        "http://abs.test", [Library(id="lib1", name="Cached Lib", mediaType="book")]
    )
    item = LibraryItem(
        id="i1", libraryId="lib1", mediaType="book",
        media=LibraryItemMedia(metadata={"title": "Cached Book"}),
    )
    window._browse_cache.save_browse_content(
        "http://abs.test", "lib1", {RowType.RECENTLY_ADDED: [item]}
    )
    dispatched = []
    monkeypatch.setattr(window._worker, "run", lambda tag, coro: dispatched.append(tag))

    window._prime_browse_from_cache()

    assert dispatched == []
    idx = window._browse_screen._row_types.index(RowType.RECENTLY_ADDED)
    assert [i.title for i in window._browse_screen._row_items[idx]] == ["Cached Book"]


def test_prime_browse_from_cache_is_noop_when_no_cache(window, tmp_path):
    from sixpack.ui.browse_cache import BrowseCache

    window._browse_cache = BrowseCache(cache_dir=tmp_path)
    window._server_url = "http://abs.test"

    window._prime_browse_from_cache()

    assert window._stack.currentWidget() is not window._browse_screen


def test_libraries_result_saves_to_cache(window, tmp_path):
    from sixpack.api.models import Library
    from sixpack.ui.browse_cache import BrowseCache

    window._browse_cache = BrowseCache(cache_dir=tmp_path)
    window._server_url = "http://abs.test"
    window._token = "tok"

    window._on_result("libraries", [Library(id="lib1", name="Fresh Lib", mediaType="book")])

    cached = window._browse_cache.load_libraries("http://abs.test")
    assert [lib.id for lib in cached] == ["lib1"]


def test_fetch_browse_content_primes_rows_from_cache(window, tmp_path):
    from sixpack.api.models import LibraryItem, LibraryItemMedia
    from sixpack.ui.browse_cache import BrowseCache
    from sixpack.ui.screens.browse import RowType

    window._browse_cache = BrowseCache(cache_dir=tmp_path)
    window._server_url = "http://abs.test"
    window._token = "tok"
    item = LibraryItem(
        id="i1", libraryId="lib1", mediaType="book",
        media=LibraryItemMedia(metadata={"title": "Cached Book"}),
    )
    window._browse_cache.save_browse_content(
        "http://abs.test", "lib1", {RowType.RECENTLY_ADDED: [item]}
    )

    window._fetch_browse_content("lib1")

    idx = window._browse_screen._row_types.index(RowType.RECENTLY_ADDED)
    assert [i.title for i in window._browse_screen._row_items[idx]] == ["Cached Book"]


def test_browse_content_result_saves_to_cache(window, tmp_path):
    from sixpack.api.models import Library, LibraryItem, LibraryItemMedia
    from sixpack.ui.browse_cache import BrowseCache
    from sixpack.ui.screens.browse import RowType

    window._browse_cache = BrowseCache(cache_dir=tmp_path)
    window._server_url = "http://abs.test"
    window._token = "tok"
    window._current_library = Library(id="lib1", name="Lib", mediaType="book")
    item = LibraryItem(
        id="i1", libraryId="lib1", mediaType="book",
        media=LibraryItemMedia(metadata={"title": "Fresh Book"}),
    )

    window._on_result("browse_content", ("lib1", {RowType.RECENTLY_ADDED: [item]}))

    cached = window._browse_cache.load_browse_content("http://abs.test", "lib1")
    assert [i.title for i in cached[RowType.RECENTLY_ADDED]] == ["Fresh Book"]


def test_on_track_ended_navigates_to_series_detail_with_next_focused(window, qtbot):
    """Automatic end-of-track must NOT auto-play the next book — it shows
    an up-next message, then lands on the series detail screen with the
    next book pre-focused, per this plan's end-of-book behavior change."""
    from sixpack.api.models import LibraryItemMedia, Series, SeriesBook

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

    # Shrink the up-next delay so this test doesn't have to sleep out the
    # real 3000ms production value — this is what was making test_app.py's
    # suite slow and its ~200ms margin race real timer delivery under
    # system load. The behavior under test (navigation happens after SOME
    # delay) is unaffected by the delay's actual duration.
    window._UP_NEXT_DELAY_MS = 50

    window._on_track_ended()
    # up-next message shown synchronously; navigation happens after a timer
    assert window._player_screen._up_next_label.isVisible()

    qtbot.wait(window._UP_NEXT_DELAY_MS + 200)

    assert window._stack.currentWidget() is window._detail_screen
    assert window._detail_screen._grid._focused_index == 1  # b2 pre-focused


def test_pairing_login_succeeded_saves_token_and_proceeds(window, qtbot, monkeypatch):
    """The pairing flow's success path must save the token via the same
    AppConfig/ServerConfig mechanism manual login uses, and proceed to
    fetch libraries / show browse — matching _on_login_requested's
    existing successful-login behavior, not a parallel path."""
    saved = []
    monkeypatch.setattr(window._config, "add_or_update_server", lambda cfg: saved.append(cfg))
    monkeypatch.setattr(window._config, "save", lambda: None)

    window._login_screen.pairing_login_succeeded.emit("http://abs.test", "alice", "tok123")

    assert len(saved) == 1
    assert saved[0].url == "http://abs.test"
    assert saved[0].token == "tok123"
    assert saved[0].username == "alice"


def test_show_login_starts_pairing_server(window):
    calls = []
    window._login_screen.start_pairing = lambda: calls.append(True)
    window._show_login()
    assert calls == [True]


def test_leaving_login_screen_stops_pairing_server(window):
    """The real transition-away-from-login point is inside _on_result's
    "libraries"/"autologin" success branch, not _show_browse() itself
    (which is also called from other, unrelated navigation paths)."""
    calls = []
    window._login_screen.stop_pairing = lambda: calls.append(True)
    window._on_result("autologin", [])
    assert calls == [True]


def test_close_event_stops_pairing_server(window):
    calls = []
    window._login_screen.stop_pairing = lambda: calls.append(True)
    window.close()
    assert calls == [True]


def test_on_error_libraries_shows_recoverable_error_on_login_screen(window, qtbot):
    """A "libraries" fetch failure after a successful login (pairing or
    manual) must not strand the user silently: the login screen is shown,
    its error is genuinely visible, and any pairing server left running
    from before is stopped."""
    old_server = window._login_screen._pairing_server
    assert old_server is not None  # start_pairing() already ran during __init__ (_show_login)

    window._on_error("libraries", "connection reset")
    qtbot.wait(20)

    assert window._stack.currentWidget() is window._login_screen
    assert window._login_screen._error_label.isVisible()
    assert "connection reset" in window._login_screen._error_label.text()
    assert window._login_screen._keyboard_form.isVisible()


def test_on_result_book_chapters_single_chapter_sets_chapters_after_play(window):
    """Round-2 regression test (Task 6 fix): the single-chapter direct-play
    path in _on_result("book_chapters", ...) must call set_chapters() AFTER
    the play-handler (_on_play_requested -> PlayerScreen.play_book), not
    before. play_book() resets PlayerScreen._chapters = [] at entry (round-1
    fix for a different bug: stale chapters surviving next/prev navigation),
    so calling set_chapters() before play_book() would have it immediately
    wiped, silently disabling the in-player chapter overlay for every
    single-chapter item (the common case for standalone audiobooks).
    """
    from sixpack.api.models import Chapter, LibraryItem, LibraryItemMedia, Series, SeriesBook

    media = LibraryItemMedia(metadata={"title": "Book 1"}, duration=100.0)
    book = SeriesBook(id="b1", libraryId="lib1", media=media, sequence="1")
    series = Series(id="s1", name="A Series", books=[book])

    window._current_series = series
    window._pending_book = book

    chapters = [Chapter(id=0, start=0.0, end=100.0, title="Ch1")]
    result_media = LibraryItemMedia(metadata={"title": "Book 1"}, duration=100.0, chapters=chapters)
    result_item = LibraryItem(id="b1", libraryId="lib1", media=result_media)

    window._on_result("book_chapters", result_item)

    assert window._player_screen._chapters == chapters


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

    # See the matching comment in
    # test_on_track_ended_navigates_to_series_detail_with_next_focused —
    # shrink the delay to avoid a real ~3s sleep per test.
    window._UP_NEXT_DELAY_MS = 50

    window._on_track_ended()
    qtbot.wait(window._UP_NEXT_DELAY_MS + 200)

    assert window._stack.currentWidget() is window._browse_screen


# ----------------------------------------------------------------------
# Up-next timer race (final whole-plan review, Fix 2)
#
# _on_track_ended arms a QTimer.singleShot with no handle and no way to
# invalidate it. If the user takes a manual action (next/prev/back) during
# the delay window, the stale timer must not still fire later and act.
# ----------------------------------------------------------------------


def test_on_next_item_invalidates_up_next_generation(window):
    window._up_next_generation = 5
    window._current_series = None  # early-return after the invalidation
    window._on_next_item()
    assert window._up_next_generation == 6


def test_on_prev_item_invalidates_up_next_generation(window):
    window._up_next_generation = 5
    window._current_series = None  # early-return after the invalidation
    window._on_prev_item()
    assert window._up_next_generation == 6


def test_on_player_back_invalidates_up_next_generation(window):
    window._up_next_generation = 5
    window._player_back_target = "browse"
    window._on_player_back()
    assert window._up_next_generation == 6


def test_manual_next_hides_up_next_label(window):
    """_on_next_item must hide the (now-stale) "Up next: ..." label
    immediately, so it doesn't stay visibly painted over the newly-started
    playback during the remainder of the old delay window."""
    # The player screen must actually be on-screen for its child
    # _up_next_label's isVisible() to reflect setVisible(True) — see the
    # matching comment in test_on_track_ended_navigates_to_series_detail_
    # with_next_focused.
    window._stack.setCurrentWidget(window._player_screen)
    window._current_series = None  # early-return after the hide
    window._player_screen.show_up_next("Up next: Something")
    assert window._player_screen._up_next_label.isVisible()
    window._on_next_item()
    assert not window._player_screen._up_next_label.isVisible()


def test_stale_up_next_timer_does_not_refire_after_manual_back(window, qtbot):
    """End-to-end regression for Fix 2: track ends -> up-next timer armed
    -> user immediately presses Back (a manual action reachable during the
    delay window) -> the stale timer must NOT fire later and navigate
    again, yanking the user off whatever screen the manual Back landed
    them on."""
    from sixpack.api.models import LibraryItemMedia, Series, SeriesBook

    media1 = LibraryItemMedia(metadata={"title": "Book 1"}, duration=100.0)
    media2 = LibraryItemMedia(metadata={"title": "Book 2"}, duration=100.0)
    b1 = SeriesBook(id="b1", libraryId="lib1", media=media1, sequence="1")
    b2 = SeriesBook(id="b2", libraryId="lib1", media=media2, sequence="2")
    series = Series(id="s1", name="A Series", books=[b1, b2])

    window._current_series = series
    window._player_screen._current_book = b1
    window._player_screen._series_books = [b1, b2]
    window._player_screen._current_index = 0
    window._detail_screen.show_loading(series)
    window._stack.setCurrentWidget(window._player_screen)
    window._UP_NEXT_DELAY_MS = 50

    window._on_track_ended()  # arms the up-next timer for the current generation
    assert window._player_screen._up_next_label.isVisible()

    # Manual Back immediately after — reachable in real usage while
    # "Up next" is showing.
    window._player_back_target = "browse"
    window._on_player_back()
    assert window._stack.currentWidget() is window._browse_screen

    # Wait past the stale timer's original delay. Without Fix 2, the stale
    # timer fires here and calls _advance_after_up_next, navigating AGAIN
    # (to series detail) and away from Browse.
    qtbot.wait(window._UP_NEXT_DELAY_MS + 200)

    assert window._stack.currentWidget() is window._browse_screen


# ----------------------------------------------------------------------
# Chapter-forwarding connection ordering (final whole-plan review, Fix 5)
#
# The chapters-forwarding connection must run AFTER the matching
# _on_*_play_requested connection on the same signal, since the play_*
# handler resets PlayerScreen._chapters before the forwarder sets the real
# value. This exercises that dependency through the REAL signal (not by
# calling the handlers directly), which round-2's fix-round tests never
# covered for the multi-chapter path.
# ----------------------------------------------------------------------


def test_play_requested_forwards_chapters_to_player_in_order(window):
    from sixpack.api.models import Chapter, LibraryItemMedia, Series, SeriesBook

    media = LibraryItemMedia(metadata={"title": "Book 1"}, duration=100.0)
    book = SeriesBook(id="b1", libraryId="lib1", media=media, sequence="1")
    series = Series(id="s1", name="A Series", books=[book])
    window._current_series = series

    chapters = [
        Chapter(id=0, start=0.0, end=50.0, title="Ch1"),
        Chapter(id=1, start=50.0, end=100.0, title="Ch2"),
    ]
    window._chapter_screen._chapters = chapters

    window._chapter_screen.play_requested.emit(book, 0.0)

    assert window._player_screen._chapters == chapters


def test_library_item_play_requested_forwards_chapters_to_player_in_order(window):
    from sixpack.api.models import Chapter, LibraryItem, LibraryItemMedia

    media = LibraryItemMedia(metadata={"title": "Item 1", "authorName": "Author"})
    item = LibraryItem(id="i1", libraryId="lib1", media=media)

    chapters = [
        Chapter(id=0, start=0.0, end=50.0, title="Ch1"),
        Chapter(id=1, start=50.0, end=100.0, title="Ch2"),
    ]
    window._chapter_screen._chapters = chapters

    window._chapter_screen.library_item_play_requested.emit(item, 0.0)

    assert window._player_screen._chapters == chapters


def test_playlist_item_play_requested_forwards_chapters_to_player_in_order(window):
    from sixpack.api.models import Chapter, LibraryItem, LibraryItemMedia, Playlist, PlaylistItem

    media = LibraryItemMedia(metadata={"title": "Item 1", "authorName": "Author"})
    library_item = LibraryItem(id="i1", libraryId="lib1", media=media)
    item = PlaylistItem(library_item_id="i1", library_item=library_item)
    playlist = Playlist(id="p1", name="My Playlist", items=[item])
    window._current_playlist = playlist

    chapters = [
        Chapter(id=0, start=0.0, end=50.0, title="Ch1"),
        Chapter(id=1, start=50.0, end=100.0, title="Ch2"),
    ]
    window._chapter_screen._chapters = chapters

    window._chapter_screen.playlist_item_play_requested.emit(item, 0.0)

    assert window._player_screen._chapters == chapters


def test_on_result_playlist_single_chapter_sets_playlist_detail_back_target(window):
    """Single-chapter playlist items bypass the chapter screen entirely --
    the "playlist_item_chapters" result handler calls
    _on_playlist_item_play_requested directly. Back from the player must
    therefore land on playlist_detail, not on the never-shown chapter
    screen. Previously _on_playlist_item_activated eagerly set
    _player_back_target="chapter" regardless of chapter count, and
    _on_playlist_item_play_requested's ternary re-derivation always
    evaluated to "chapter" for any playlist item since
    _chapter_back_target is unconditionally "playlist_detail" after
    activation -- sending single-chapter playback to a blank chapter
    screen on Back."""
    from sixpack.api.models import LibraryItem, LibraryItemMedia, Playlist, PlaylistItem

    media = LibraryItemMedia(metadata={"title": "Item 1", "authorName": "Author"})
    library_item = LibraryItem(id="i1", libraryId="lib1", media=media)
    item = PlaylistItem(library_item_id="i1", library_item=library_item)
    playlist = Playlist(id="p1", name="My Playlist", items=[item])
    window._current_playlist = playlist
    window._server_url = "http://abs.test"
    window._token = "tok"

    # Mirrors _on_playlist_item_activated's eager assignment.
    window._pending_playlist_item = item
    window._chapter_back_target = "playlist_detail"
    window._player_back_target = "playlist_detail"

    full_item = LibraryItem(id="i1", libraryId="lib1", media=media)  # no chapters
    window._on_result("playlist_item_chapters", full_item)

    assert window._stack.currentWidget() is window._player_screen
    assert window._player_back_target == "playlist_detail"


# ---- Podcast playback wiring ----

def test_podcast_selected_shows_detail_screen(window):
    from sixpack.api.models import LibraryItem, LibraryItemMedia

    show = LibraryItem(
        id="show1", libraryId="lib1", mediaType="podcast",
        media=LibraryItemMedia(metadata={"title": "My Show"}),
    )
    window._server_url = "http://abs.test"
    window._token = "tok"

    window._browse_screen.podcast_selected.emit(show)

    assert window._stack.currentWidget() is window._podcast_detail_screen
    assert window._current_podcast_show is show


def test_on_result_podcast_detail_populates_episodes_from_full_item(window):
    """Live-verification regression test: BrowseScreen's rows only ever carry
    lightweight LibraryItem stubs (from get_library_items_recent()/
    personalized-shelf non-continue entities), which never include
    media.episodes — confirmed against a real Audiobookshelf server's
    /api/libraries/{id}/items response during Task 6 live verification.
    _on_podcast_selected's "podcast_detail" worker result must therefore
    carry a FULL re-fetched LibraryItem (with real episodes), not just a
    progress dict layered on the original lightweight stub the show_loading()
    preview used — otherwise the episode grid stays permanently empty for
    every podcast reached by drilling in from Browse (as opposed to a
    Continue Listening entry, whose recentEpisode already arrives fully
    formed from the shelf itself)."""
    from sixpack.api.models import LibraryItem, LibraryItemMedia, PodcastEpisode

    stub_show = LibraryItem(
        id="show1", libraryId="lib1", mediaType="podcast",
        media=LibraryItemMedia(metadata={"title": "My Show"}),  # no episodes
    )
    window._current_podcast_show = stub_show

    episodes = [
        PodcastEpisode(id="ep1", libraryItemId="show1", title="Episode One"),
        PodcastEpisode(id="ep2", libraryItemId="show1", title="Episode Two"),
    ]
    full_show = LibraryItem(
        id="show1", libraryId="lib1", mediaType="podcast",
        media=LibraryItemMedia(metadata={"title": "My Show"}, episodes=episodes),
    )

    window._on_result("podcast_detail", (full_show, {}))

    assert window._current_podcast_show is full_show
    assert window._podcast_detail_screen._items == episodes


def test_podcast_episode_activated_single_chapter_plays_directly(window, monkeypatch):
    from sixpack.api.models import LibraryItem, LibraryItemMedia, PodcastEpisode

    show = LibraryItem(
        id="show1", libraryId="lib1", mediaType="podcast",
        media=LibraryItemMedia(metadata={"title": "My Show"}),
    )
    episode = PodcastEpisode(id="ep1", libraryItemId="show1", title="Episode One")  # no chapters
    window._current_podcast_show = show
    window._server_url = "http://abs.test"
    window._token = "tok"

    played = []
    monkeypatch.setattr(
        window, "_on_podcast_episode_play_requested",
        lambda ep, start_time: played.append((ep, start_time)),
    )

    window._podcast_detail_screen.item_activated.emit(episode)

    assert played == [(episode, 0.0)]
    assert window._player_back_target == "podcast_detail"


def test_podcast_episode_activated_multi_chapter_shows_chapter_screen(window):
    from sixpack.api.models import Chapter, LibraryItem, LibraryItemMedia, PodcastEpisode

    show = LibraryItem(
        id="show1", libraryId="lib1", mediaType="podcast",
        media=LibraryItemMedia(metadata={"title": "My Show"}),
    )
    chapters = [
        Chapter(id=0, start=0.0, end=100.0, title="Part 1"),
        Chapter(id=1, start=100.0, end=200.0, title="Part 2"),
    ]
    episode = PodcastEpisode(
        id="ep1", libraryItemId="show1", title="Episode One", chapters=chapters
    )
    window._current_podcast_show = show
    window._server_url = "http://abs.test"
    window._token = "tok"

    window._podcast_detail_screen.item_activated.emit(episode)

    assert window._stack.currentWidget() is window._chapter_screen
    assert window._player_back_target == "chapter"
    assert window._chapter_back_target == "podcast_detail"


def test_podcast_episode_selected_from_continue_listening_sets_browse_back_target(window):
    """Continue-listening entries have no intermediate detail screen —
    mirrors _on_browse_book_selected's direct-from-browse book path."""
    from sixpack.api.models import LibraryItem, LibraryItemMedia, PodcastEpisode

    show = LibraryItem(
        id="show1", libraryId="lib1", mediaType="podcast",
        media=LibraryItemMedia(metadata={"title": "My Show"}),
    )
    episode = PodcastEpisode(id="ep1", libraryItemId="show1", title="Episode One")
    window._server_url = "http://abs.test"
    window._token = "tok"

    window._browse_screen.podcast_episode_selected.emit(show, episode)

    assert window._current_podcast_show is show
    assert window._pending_podcast_episode is episode
    assert window._chapter_back_target == "browse"
    assert window._player_back_target == "browse"


def test_on_result_podcast_continue_progress_multi_chapter_sets_chapter_back_target(window):
    """Row 4 of Task 6's back-target trace table: a Continue-Listening entry
    (no intermediate podcast_detail screen was ever shown) whose episode has
    multiple chapters. The "podcast_continue_progress" branch in _on_result
    must set _player_back_target = "chapter" (so Back from the player lands
    on the chapter screen) while leaving _chapter_back_target = "browse" (so
    Back from the chapter screen skips the never-shown detail screen and
    lands directly on Browse) -- these two back-targets deliberately diverge
    inside this one branch, which is exactly the kind of state-machine
    subtlety this task exists to guard against. Previously uncovered: no
    test drove _on_result("podcast_continue_progress", ...) at all."""
    from sixpack.api.models import (
        Chapter,
        LibraryItem,
        LibraryItemMedia,
        MediaProgress,
        PodcastEpisode,
    )

    show = LibraryItem(
        id="show1", libraryId="lib1", mediaType="podcast",
        media=LibraryItemMedia(metadata={"title": "My Show"}),
    )
    chapters = [
        Chapter(id=0, start=0.0, end=100.0, title="Part 1"),
        Chapter(id=1, start=100.0, end=200.0, title="Part 2"),
    ]
    episode = PodcastEpisode(
        id="ep1", libraryItemId="show1", title="Episode One", chapters=chapters
    )
    window._current_podcast_show = show
    window._pending_podcast_episode = episode
    window._server_url = "http://abs.test"
    window._token = "tok"
    # Mirrors _on_podcast_episode_selected's eager assignment, which always
    # runs (and completes) before this worker result comes back.
    window._chapter_back_target = "browse"
    window._player_back_target = "browse"

    progress = MediaProgress(libraryItemId="show1", episodeId="ep1", currentTime=42.0)
    window._on_result("podcast_continue_progress", (show, episode, progress))

    assert window._stack.currentWidget() is window._chapter_screen
    assert window._chapter_back_target == "browse"
    assert window._player_back_target == "chapter"


def test_on_player_back_podcast_detail_target_shows_podcast_detail(window):
    window._player_back_target = "podcast_detail"
    window._on_player_back()
    assert window._stack.currentWidget() is window._podcast_detail_screen


def test_on_chapter_back_podcast_detail_target_shows_podcast_detail(window):
    window._chapter_back_target = "podcast_detail"
    window._on_chapter_back()
    assert window._stack.currentWidget() is window._podcast_detail_screen


def test_on_progress_update_forwards_episode_id(window, monkeypatch):
    calls = []
    monkeypatch.setattr(
        window, "_async_update_progress",
        lambda *args, **kwargs: calls.append((args, kwargs)) or _noop_coro(),
    )
    window._server_url = "http://abs.test"
    window._token = "tok"

    window._on_progress_update("show1", 100.0, 1000.0, False, "ep1")

    # Confirm the worker was asked to run something — the key behavior
    # under test is that "ep1" reaches _async_update_progress as the
    # episode_id argument.
    assert calls
    assert "ep1" in calls[0][0] or calls[0][1].get("episode_id") == "ep1"


def test_on_track_ended_podcast_episode_returns_to_episode_list_with_focus(window, qtbot):
    """End-of-episode (not manual Back) must return to the podcast episode
    list, per the spec's "return to the episode list on finish/back" —
    not fall through to the generic default branch, which lands on Browse
    and loses the show context (final whole-plan review, Fix 1)."""
    from sixpack.api.models import LibraryItem, LibraryItemMedia, PodcastEpisode

    ep1 = PodcastEpisode(id="ep1", libraryItemId="show1", title="Episode One")
    ep2 = PodcastEpisode(id="ep2", libraryItemId="show1", title="Episode Two")
    show = LibraryItem(
        id="show1", libraryId="lib1", mediaType="podcast",
        media=LibraryItemMedia(metadata={"title": "My Show"}, episodes=[ep1, ep2]),
    )
    window._podcast_detail_screen.load(show, {}, "http://abs.test", "tok")
    window._current_podcast_show = show

    # play_podcast_episode() is what sets _episode_id — _current_book/
    # _current_playlist_item stay None the whole time (_reset_per_item_state
    # never touches them for a podcast play), which is the exact discriminator
    # gap Fix 1 closes.
    window._player_screen._current_book = None
    window._player_screen._current_playlist_item = None
    window._player_screen._series_books = []
    window._player_screen._playlist_items = []
    window._player_screen._episode_id = "ep1"

    window._UP_NEXT_DELAY_MS = 50
    window._on_track_ended()
    qtbot.wait(window._UP_NEXT_DELAY_MS + 200)

    assert window._stack.currentWidget() is window._podcast_detail_screen
    assert window._podcast_detail_screen._grid._focused_index == 0  # ep1 refocused


def test_on_error_podcast_detail_returns_to_browse(window):
    """A transient network failure on drill-in must not leave the user
    stuck on a permanently blank episode grid with no way out except Back
    (final whole-plan review, Fix 3)."""
    from sixpack.api.models import LibraryItem, LibraryItemMedia

    show = LibraryItem(
        id="show1", libraryId="lib1", mediaType="podcast",
        media=LibraryItemMedia(metadata={"title": "My Show"}),
    )
    window._current_podcast_show = show
    window._show_podcast_detail()

    window._on_error("podcast_detail", "connection reset")

    assert window._stack.currentWidget() is window._browse_screen


def test_podcast_continue_progress_result_is_self_contained_not_stale_current_show(
    window, monkeypatch
):
    """Regression test for the show/episode desync race (final whole-plan
    review, Fix 2): _pending_podcast_episode/_current_podcast_show are two
    independently-mutable instance fields. If the user navigates to a
    DIFFERENT podcast show while a Continue Listening progress fetch for an
    earlier show/episode is still in flight, the OLD code would pair the
    stale episode with the now-current (wrong) show when the result finally
    arrived. _async_get_podcast_progress now returns (show, episode,
    progress) as a self-contained tuple, so the result handler never needs
    to re-read (possibly-changed) instance state to pair them — verify the
    play-request fires with the ORIGINAL, correctly-paired show/episode."""
    from sixpack.api.models import LibraryItem, LibraryItemMedia, MediaProgress, PodcastEpisode

    show_a = LibraryItem(
        id="showA", libraryId="lib1", mediaType="podcast",
        media=LibraryItemMedia(metadata={"title": "Show A"}),
    )
    episode_a = PodcastEpisode(id="epA", libraryItemId="showA", title="Episode A")
    show_b = LibraryItem(
        id="showB", libraryId="lib1", mediaType="podcast",
        media=LibraryItemMedia(metadata={"title": "Show B"}),
    )
    window._server_url = "http://abs.test"
    window._token = "tok"

    # Simulate the race: show_A/episode_A's fetch is in flight...
    window._current_podcast_show = show_a
    window._pending_podcast_episode = episode_a
    # ...then, before it resolves, the user navigates to a DIFFERENT show.
    window._current_podcast_show = show_b

    played = []
    monkeypatch.setattr(
        window, "_on_podcast_episode_play_requested",
        lambda ep, start_time: played.append(ep),
    )

    progress = MediaProgress(libraryItemId="showA", episodeId="epA", currentTime=10.0)
    # The self-contained result still carries show_A/episode_A, paired
    # together, regardless of what _current_podcast_show has since become.
    window._on_result("podcast_continue_progress", (show_a, episode_a, progress))

    assert played == [episode_a]
    # The handler re-syncs instance state to the result it actually acted
    # on, rather than trusting whatever _current_podcast_show had drifted to.
    assert window._current_podcast_show is show_a


def test_on_podcast_episode_selected_calls_progress_fetch_with_show_and_episode(
    window, monkeypatch
):
    """_async_get_podcast_progress must be handed the show/episode pair
    directly (not just ids read back off mutable instance state later),
    so its result is self-contained end to end."""
    from sixpack.api.models import LibraryItem, LibraryItemMedia, PodcastEpisode

    show = LibraryItem(
        id="show1", libraryId="lib1", mediaType="podcast",
        media=LibraryItemMedia(metadata={"title": "My Show"}),
    )
    episode = PodcastEpisode(id="ep1", libraryItemId="show1", title="Episode One")
    window._server_url = "http://abs.test"
    window._token = "tok"

    async def _fake_result():
        # (None, None, None) is a harmless, well-formed result — the "podcast_continue_progress"
        # branch's None-show guard (Fix 12) treats it as a no-op once the
        # worker thread actually runs this coroutine.
        return None, None, None

    calls = []
    monkeypatch.setattr(
        window, "_async_get_podcast_progress",
        lambda *args: calls.append(args) or _fake_result(),
    )

    window._browse_screen.podcast_episode_selected.emit(show, episode)

    assert calls == [(show, episode)]


def test_on_result_podcast_continue_progress_none_show_is_noop(window):
    """Defensive guard (final whole-plan review, Fix 12): a None show in
    the result tuple must not crash — mirrors the existing None-check in
    _on_podcast_episode_play_requested."""
    from sixpack.api.models import PodcastEpisode

    episode = PodcastEpisode(id="ep1", libraryItemId="show1", title="Episode One")
    window._current_podcast_show = None
    window._on_result("podcast_continue_progress", (None, episode, None))
    assert window._stack.currentWidget() is not window._chapter_screen
    assert window._stack.currentWidget() is not window._player_screen


def test_podcast_episode_activated_single_chapter_sets_player_chapters(window, monkeypatch):
    """Every other single-chapter direct-play path (book, library item,
    playlist item) calls set_chapters() so the in-player MENU overlay is
    populated even for a single "chapter" — the podcast equivalent path was
    missing this call (final whole-plan review, Fix 6)."""
    from sixpack.api.models import Chapter, LibraryItem, LibraryItemMedia, PodcastEpisode

    show = LibraryItem(
        id="show1", libraryId="lib1", mediaType="podcast",
        media=LibraryItemMedia(metadata={"title": "My Show"}),
    )
    chapters = [Chapter(id=0, start=0.0, end=100.0, title="Whole episode")]
    episode = PodcastEpisode(
        id="ep1", libraryItemId="show1", title="Episode One", chapters=chapters
    )
    window._current_podcast_show = show
    window._server_url = "http://abs.test"
    window._token = "tok"

    window._podcast_detail_screen.item_activated.emit(episode)

    assert window._player_screen._chapters == chapters


def test_podcast_continue_progress_single_chapter_sets_player_chapters(window):
    """Same as test_podcast_episode_activated_single_chapter_sets_player_chapters,
    but for the Continue Listening direct-play path (final whole-plan
    review, Fix 6)."""
    from sixpack.api.models import (
        Chapter,
        LibraryItem,
        LibraryItemMedia,
        MediaProgress,
        PodcastEpisode,
    )

    show = LibraryItem(
        id="show1", libraryId="lib1", mediaType="podcast",
        media=LibraryItemMedia(metadata={"title": "My Show"}),
    )
    chapters = [Chapter(id=0, start=0.0, end=100.0, title="Whole episode")]
    episode = PodcastEpisode(
        id="ep1", libraryItemId="show1", title="Episode One", chapters=chapters
    )
    window._server_url = "http://abs.test"
    window._token = "tok"

    progress = MediaProgress(libraryItemId="show1", episodeId="ep1", currentTime=0.0)
    window._on_result("podcast_continue_progress", (show, episode, progress))

    assert window._player_screen._chapters == chapters


def test_async_fetch_podcast_detail_reuses_one_client(window):
    """The item-detail fetch and the per-episode progress fan-out must
    share a single ABSClient (matching _async_get_browse_book's equivalent
    pattern for books) -- and, per the session-wide connection-reuse fix,
    that's window._client itself: no per-call ABSClient is constructed at
    all anymore."""
    import asyncio

    from sixpack.api.models import LibraryItem, LibraryItemMedia, PodcastEpisode

    ep = PodcastEpisode(id="ep1", libraryItemId="show1", title="Episode One")
    show = LibraryItem(
        id="show1", libraryId="lib1", mediaType="podcast",
        media=LibraryItemMedia(metadata={"title": "My Show"}),
    )
    full_show = LibraryItem(
        id="show1", libraryId="lib1", mediaType="podcast",
        media=LibraryItemMedia(metadata={"title": "My Show"}, episodes=[ep]),
    )

    calls = []

    class FakeClient:
        async def get_library_item(self, item_id):
            calls.append(("get_library_item", item_id))
            return full_show

        async def get_progress(self, item_id, episode_id=None):
            calls.append(("get_progress", item_id, episode_id))
            return None

    fake = FakeClient()
    window._server_url = "http://abs.test"
    window._token = "tok"
    window._client = fake

    full, _progress = asyncio.run(window._async_fetch_podcast_detail(show))

    assert full is full_show
    assert ("get_library_item", "show1") in calls
    assert ("get_progress", "show1", "ep1") in calls


def test_on_progress_update_via_real_signal_forwards_episode_id(window, monkeypatch):
    """Task 5 closed a bug where PlayerScreen.progress_update (5 args) was
    connected to a 4-arg @pyqtSlot -- PyQt's signal/slot marshalling layer
    silently truncated the trailing arg, which is a different failure mode
    than plain Python argument passing and not something a direct method
    call can catch. test_on_progress_update_forwards_episode_id above calls
    window._on_progress_update(...) directly, which would keep passing even
    if the signal were widened again without updating the @pyqtSlot(...)
    decorator's type list. This test instead emits the REAL signal through
    the REAL connection app.py wires (_player_screen.progress_update ->
    _on_progress_update), so a reintroduction of that specific regression
    would be caught here."""
    calls = []
    monkeypatch.setattr(
        window, "_async_update_progress",
        lambda *args, **kwargs: calls.append((args, kwargs)) or _noop_coro(),
    )
    window._server_url = "http://abs.test"
    window._token = "tok"

    window._player_screen.progress_update.emit("show1", 100.0, 1000.0, False, "ep1")

    assert calls
    assert "ep1" in calls[0][0] or calls[0][1].get("episode_id") == "ep1"


async def _noop_coro():
    return None


# ---- Auto-update wiring ----

def test_main_window_fires_check_update_on_startup(qtbot, monkeypatch):
    """Verifies the real dispatch wiring exists -- constructs its own
    MainWindow (not the shared `window` fixture, which stubs the check
    entirely) with AsyncWorker.run patched at the class level so no real
    coroutine executes."""
    from sixpack.config import AppConfig
    from sixpack.ui import app as app_module

    monkeypatch.setattr(app_module, "AudioPlayer", _FakeAudioPlayer)
    dispatched = []
    monkeypatch.setattr(
        app_module.AsyncWorker, "run", lambda self, tag, coro: dispatched.append(tag)
    )

    win = app_module.MainWindow(AppConfig())
    qtbot.addWidget(win)
    try:
        assert dispatched == ["check_update"]
    finally:
        win.close()


def test_on_result_check_update_shows_prompt_when_newer_release_available(window, monkeypatch):
    from sixpack.ui import app as app_module
    from sixpack.updater import ReleaseInfo

    monkeypatch.setattr(app_module, "CURRENT_VERSION", "0.1.0")
    release = ReleaseInfo(version="0.2.0", zipball_url="http://example.com/z.zip")

    window._on_result("check_update", release)

    assert window._stack.currentWidget() is window._update_prompt_screen
    assert window._pending_release is release


def test_on_result_check_update_proceeds_to_login_when_release_not_newer(window, monkeypatch):
    from sixpack.ui import app as app_module
    from sixpack.updater import ReleaseInfo

    monkeypatch.setattr(app_module, "CURRENT_VERSION", "9.9.9")
    release = ReleaseInfo(version="0.2.0", zipball_url="http://example.com/z.zip")

    window._on_result("check_update", release)

    assert window._stack.currentWidget() is window._login_screen


def test_on_result_check_update_proceeds_to_login_when_no_release(window):
    window._on_result("check_update", None)
    assert window._stack.currentWidget() is window._login_screen


def test_on_error_check_update_proceeds_to_login(window):
    """Defensive backstop -- fetch_latest_release() fails soft internally
    and should never actually raise, but _on_error must still degrade
    gracefully if it somehow did."""
    window._on_error("check_update", "boom")
    assert window._stack.currentWidget() is window._login_screen


def test_update_prompt_later_proceeds_to_login(window):
    from sixpack.updater import ReleaseInfo

    window._pending_release = ReleaseInfo(version="0.2.0", zipball_url="http://example.com/z.zip")
    window._update_prompt_screen.show_prompt("0.1.0", "0.2.0")
    window._stack.setCurrentWidget(window._update_prompt_screen)

    window._update_prompt_screen.later_requested.emit()

    assert window._stack.currentWidget() is window._login_screen


def test_on_update_install_requested_fires_apply_update_job(window, monkeypatch):
    from sixpack.updater import ReleaseInfo

    window._pending_release = ReleaseInfo(version="0.2.0", zipball_url="http://example.com/z.zip")
    dispatched = []
    monkeypatch.setattr(window._worker, "run", lambda tag, coro: dispatched.append(tag))

    window._on_update_install_requested()

    assert dispatched == ["apply_update"]
    assert not window._update_prompt_screen._button_row.isVisible()


def test_on_update_install_requested_is_noop_without_pending_release(window, monkeypatch):
    window._pending_release = None
    dispatched = []
    monkeypatch.setattr(window._worker, "run", lambda tag, coro: dispatched.append(tag))

    window._on_update_install_requested()

    assert dispatched == []


def test_on_result_apply_update_relaunches_and_quits(window, monkeypatch):
    """CRITICAL: must monkeypatch both relaunch and QApplication.quit --
    see this plan's Global Constraints. Calling the real .quit() would
    tear down the shared test-session QApplication."""
    from PyQt6.QtWidgets import QApplication

    from sixpack.ui import app as app_module

    relaunch_calls = []
    monkeypatch.setattr(app_module, "relaunch", lambda: relaunch_calls.append(True))
    quit_calls = []
    monkeypatch.setattr(QApplication, "quit", lambda self: quit_calls.append(True))

    window._on_result("apply_update", None)

    assert relaunch_calls == [True]
    assert quit_calls == [True]


def test_on_error_apply_update_shows_error_state(window):
    window._on_error("apply_update", "Download failed: connection refused")
    assert window._stack.currentWidget() is window._update_prompt_screen
    assert "connection refused" in window._update_prompt_screen._status_label.text()
    assert window._update_prompt_screen._continue_btn.isVisible()


def test_update_prompt_continue_after_error_proceeds_to_login(window):
    window._on_error("apply_update", "boom")
    window._update_prompt_screen.continue_requested.emit()
    assert window._stack.currentWidget() is window._login_screen


def test_splash_shows_update_check_status_on_startup(qtbot, monkeypatch):
    """Regression test: verify the splash screen displays accurate status
    while the update check is in progress. Constructs its own MainWindow
    (not the shared `window` fixture) with AsyncWorker.run patched to a
    no-op so the check never completes and the window stays on the splash
    screen where we can observe the status label text."""
    from sixpack.config import AppConfig
    from sixpack.ui import app as app_module

    monkeypatch.setattr(app_module, "AudioPlayer", _FakeAudioPlayer)
    monkeypatch.setattr(
        app_module.AsyncWorker, "run", lambda self, tag, coro: None
    )

    win = app_module.MainWindow(AppConfig())
    qtbot.addWidget(win)
    try:
        assert win._splash_screen._status_label.text() == "Checking for updates…"
    finally:
        win.close()


# ---- Sidebar Exit wiring ----

def test_series_detail_finished_changed_wired_to_progress_update(window, monkeypatch):
    calls = []
    monkeypatch.setattr(
        window, "_async_update_progress",
        lambda *args, **kwargs: calls.append((args, kwargs)) or _noop_coro(),
    )
    window._server_url = "http://abs.test"
    window._token = "tok"
    window._detail_screen.finished_changed.emit("item1", 100.0, 100.0, True, "")
    assert calls


def test_playlist_detail_finished_changed_wired_to_progress_update(window, monkeypatch):
    calls = []
    monkeypatch.setattr(
        window, "_async_update_progress",
        lambda *args, **kwargs: calls.append((args, kwargs)) or _noop_coro(),
    )
    window._server_url = "http://abs.test"
    window._token = "tok"
    window._playlist_detail_screen.finished_changed.emit("item1", 100.0, 100.0, True, "")
    assert calls


def test_podcast_detail_finished_changed_wired_to_progress_update(window, monkeypatch):
    calls = []
    monkeypatch.setattr(
        window, "_async_update_progress",
        lambda *args, **kwargs: calls.append((args, kwargs)) or _noop_coro(),
    )
    window._server_url = "http://abs.test"
    window._token = "tok"
    window._podcast_detail_screen.finished_changed.emit("item1", 100.0, 100.0, True, "ep1")
    assert calls


def test_browse_exit_requested_calls_close(qtbot, monkeypatch):
    """BrowseScreen.exit_requested must be wired straight to MainWindow's
    own close() -- the same method the old Q/Ctrl+Q shortcut used to call
    -- so all existing shutdown cleanup (pairing server, audio player,
    worker thread) still runs unchanged. Constructs its own MainWindow (not
    the shared `window` fixture) because close must be patched at the
    class level BEFORE _build_ui() connects the signal -- connecting to
    self.close captures that bound method at connect time, so patching
    the instance afterward wouldn't affect an already-established
    connection."""
    from sixpack.config import AppConfig
    from sixpack.ui import app as app_module

    monkeypatch.setattr(app_module, "AudioPlayer", _FakeAudioPlayer)
    monkeypatch.setattr(app_module.AsyncWorker, "run", lambda self, tag, coro: None)
    close_calls = []
    monkeypatch.setattr(app_module.MainWindow, "close", lambda self: close_calls.append(True))

    win = app_module.MainWindow(AppConfig())
    qtbot.addWidget(win)
    try:
        win._browse_screen.exit_requested.emit()
        assert close_calls == [True]
    finally:
        # close() is patched to a no-op above, so the real closeEvent
        # (which would normally stop this thread) never ran -- stop it
        # directly so it doesn't leak into the rest of the test session.
        win._worker.stop_loop()
        win._thread.quit()
        win._thread.wait(2000)
