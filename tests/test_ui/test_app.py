"""Smoke tests for the top-level application window (headless)."""
from __future__ import annotations

import httpx
import pytest
import respx


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
    episode = PodcastEpisode(id="ep1", libraryItemId="show1", title="Episode One", chapters=chapters)
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
    from sixpack.api.models import Chapter, LibraryItem, LibraryItemMedia, MediaProgress, PodcastEpisode

    show = LibraryItem(
        id="show1", libraryId="lib1", mediaType="podcast",
        media=LibraryItemMedia(metadata={"title": "My Show"}),
    )
    chapters = [
        Chapter(id=0, start=0.0, end=100.0, title="Part 1"),
        Chapter(id=1, start=100.0, end=200.0, title="Part 2"),
    ]
    episode = PodcastEpisode(id="ep1", libraryItemId="show1", title="Episode One", chapters=chapters)
    window._current_podcast_show = show
    window._pending_podcast_episode = episode
    window._server_url = "http://abs.test"
    window._token = "tok"
    # Mirrors _on_podcast_episode_selected's eager assignment, which always
    # runs (and completes) before this worker result comes back.
    window._chapter_back_target = "browse"
    window._player_back_target = "browse"

    progress = MediaProgress(libraryItemId="show1", episodeId="ep1", currentTime=42.0)
    window._on_result("podcast_continue_progress", progress)

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

    # Confirm the worker was asked to run something — the exact assertion
    # depends on how _on_progress_update dispatches to the worker in the
    # real current code (read it in Step 1 below before finalizing this
    # test); the key behavior under test is that "ep1" reaches
    # _async_update_progress as the episode_id argument.
    assert calls
    assert "ep1" in calls[0][0] or calls[0][1].get("episode_id") == "ep1"


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
