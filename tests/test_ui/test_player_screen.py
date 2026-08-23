"""Tests for PlayerScreen's up-next display, track_ended signal, and the
cinematic-redesign visual wiring (Backdrop feed, larger cover, restyled
progress/transport controls)."""
from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap

from sixpack.api.models import (
    LibraryItem,
    LibraryItemMedia,
    Playlist,
    PlaylistItem,
    Series,
    SeriesBook,
)
from sixpack.ui.screens.player import PlayerScreen


class _FakePlayer:
    """Stands in for AudioPlayer — PlayerScreen only needs on_*/toggle_pause/
    seek_*/stop/set_speed/seek_to_chapter/chapter_count/current_chapter on it,
    matching AudioPlayer's real interface without constructing real mpv."""

    def __init__(self):
        self.speed_calls = []
        self.seek_to_chapter_calls = []
        self.seek_absolute_calls = []
        self.chapter_count = 0
        self.current_chapter = 0

    def on_position_changed(self, cb): pass
    def on_state_changed(self, cb): pass
    def on_end_of_track(self, cb): pass
    def on_duration_changed(self, cb): pass
    def toggle_pause(self): pass
    def stop(self): pass
    def seek_forward(self): pass
    def seek_back(self): pass
    def seek_forward_long(self): pass
    def seek_back_long(self): pass
    def next_chapter(self): pass
    def prev_chapter(self): pass
    def set_speed(self, speed): self.speed_calls.append(speed)
    def seek_to_chapter(self, index): self.seek_to_chapter_calls.append(index)
    def seek_absolute(self, seconds): self.seek_absolute_calls.append(seconds)


class _FakeCoverCache:
    """Captures fetch/fetch_backdrop calls instead of invoking them, so the
    test can assert exactly how many times each was invoked without a real
    network-backed CoverCache. Same pattern as
    tests/test_ui/test_detail_grid.py's _FakeCoverCache."""

    def __init__(self):
        self.fetch_calls = []
        self.fetch_backdrop_calls = []

    def fetch(self, url, token, callback):
        self.fetch_calls.append((url, token, callback))

    def fetch_backdrop(self, url, token, callback):
        self.fetch_backdrop_calls.append((url, token, callback))


@pytest.fixture
def screen(qtbot):
    s = PlayerScreen(player=_FakePlayer())
    qtbot.addWidget(s)
    s.show()
    return s


def _book(book_id="b1", title="Book One", sequence="1"):
    return SeriesBook(
        id=book_id,
        media=LibraryItemMedia(metadata={"title": title}),
        sequence=sequence,
    )


def _series(books):
    return Series(id="s1", name="Series One", books=books)


def _library_item(item_id="i1", title="Item One"):
    return LibraryItem(
        id=item_id,
        library_id="lib1",
        media=LibraryItemMedia(metadata={"title": title, "authorName": "Author"}),
    )


def _playlist_item(item_id="i1", title="Item One"):
    return PlaylistItem(
        library_item_id=item_id,
        library_item=_library_item(item_id, title),
    )


def _playlist(items):
    return Playlist(id="p1", name="My Playlist", items=items)


def test_show_up_next_sets_visible_text(screen):
    screen.show_up_next("Up next: Episode 2")
    assert screen._up_next_label.isVisible()
    assert screen._up_next_label.text() == "Up next: Episode 2"


def test_hide_up_next_clears_visibility(screen):
    screen.show_up_next("Up next: Episode 2")
    screen.hide_up_next()
    assert not screen._up_next_label.isVisible()


def test_up_next_label_hidden_initially(screen):
    assert not screen._up_next_label.isVisible()


def test_track_ended_emitted_not_next_item(qtbot, screen):
    """Regression: the automatic end-of-track path must use the new
    track_ended signal, NOT the existing next_item signal — next_item is
    reserved for the manual skip-forward remote button/key, which must keep
    auto-playing immediately (see this plan's Global Constraints)."""
    next_item_calls = []
    track_ended_calls = []
    screen.next_item.connect(lambda: next_item_calls.append(True))
    screen.track_ended.connect(lambda: track_ended_calls.append(True))

    screen._handle_end_of_track()

    assert track_ended_calls == [True]
    assert next_item_calls == []


# ----------------------------------------------------------------------
# Cinematic-redesign visual wiring (Task 4)
# ----------------------------------------------------------------------


def test_play_book_fetches_cover_and_backdrop(qtbot):
    fake_cache = _FakeCoverCache()
    s = PlayerScreen(player=_FakePlayer(), cover_cache=fake_cache)
    qtbot.addWidget(s)

    book = _book()
    series = _series([book])
    s.play_book(book, 0.0, series, [book], "http://server", "tok")

    assert len(fake_cache.fetch_calls) == 1
    assert len(fake_cache.fetch_backdrop_calls) == 1
    assert fake_cache.fetch_calls[0][2] == s._set_cover_pixmap
    # The backdrop callback is a closure (not the bare _set_backdrop_pixmap
    # method) so it can carry the item's key through to Backdrop's staleness
    # guard — see test_stale_backdrop_callback_does_not_clobber_newer_item
    # below. Invoking it end-to-end should still land the pixmap on the
    # Backdrop, exactly as the bare method used to.
    pix = QPixmap(10, 10)
    pix.fill(Qt.GlobalColor.red)
    fake_cache.fetch_backdrop_calls[0][2](pix)
    assert s._backdrop._incoming_pixmap is not None


def test_play_library_item_fetches_cover_and_backdrop(qtbot):
    fake_cache = _FakeCoverCache()
    s = PlayerScreen(player=_FakePlayer(), cover_cache=fake_cache)
    qtbot.addWidget(s)

    s.play_library_item(_library_item(), 0.0, "http://server", "tok")

    assert len(fake_cache.fetch_calls) == 1
    assert len(fake_cache.fetch_backdrop_calls) == 1


def test_play_playlist_item_fetches_cover_and_backdrop(qtbot):
    fake_cache = _FakeCoverCache()
    s = PlayerScreen(player=_FakePlayer(), cover_cache=fake_cache)
    qtbot.addWidget(s)

    item = _playlist_item()
    playlist = _playlist([item])
    s.play_playlist_item(item, 0.0, playlist, [item], "http://server", "tok")

    assert len(fake_cache.fetch_calls) == 1
    assert len(fake_cache.fetch_backdrop_calls) == 1


def test_stale_backdrop_callback_does_not_clobber_newer_item(qtbot):
    """Regression for the reused-instance race: PlayerScreen is constructed
    once by app.py and reused for every subsequent play_* call (e.g.
    app.py's _on_next_item/_on_prev_item skip handlers call play_book again
    on the SAME instance). CoverCache.fetch_backdrop resolves synchronously
    on a disk-cache hit but asynchronously (QNetworkReply) on a miss, so
    playing book A (cold cover, fetch in flight) then skipping to book B
    (warm cover, resolves immediately) then having A's fetch resolve late
    must NOT overwrite B's already-displayed backdrop with A's pixmap.
    """
    fake_cache = _FakeCoverCache()
    s = PlayerScreen(player=_FakePlayer(), cover_cache=fake_cache)
    qtbot.addWidget(s)

    book_a = _book(book_id="a", title="Book A")
    book_b = _book(book_id="b", title="Book B")
    series = _series([book_a, book_b])

    # Play book A — its backdrop fetch is "in flight" (callback captured,
    # not yet invoked), simulating a cold-cache async miss.
    s.play_book(book_a, 0.0, series, [book_a, book_b], "http://server", "tok")
    assert len(fake_cache.fetch_backdrop_calls) == 1
    stale_callback_for_a = fake_cache.fetch_backdrop_calls[0][2]

    # Skip to book B — its fetch resolves immediately (warm cache hit),
    # which is how CoverCache behaves synchronously on a cache hit.
    s.play_book(book_b, 0.0, series, [book_a, book_b], "http://server", "tok")
    assert len(fake_cache.fetch_backdrop_calls) == 2
    callback_for_b = fake_cache.fetch_backdrop_calls[1][2]
    pix_b = QPixmap(10, 10)
    pix_b.fill(Qt.GlobalColor.blue)
    callback_for_b(pix_b)
    assert s._backdrop._incoming_pixmap is pix_b

    # A's fetch now resolves late, after B is already showing. Without the
    # key guard this unconditionally overwrites the backdrop with A's cover
    # for the entire remaining duration of B's playback.
    pix_a = QPixmap(10, 10)
    pix_a.fill(Qt.GlobalColor.red)
    stale_callback_for_a(pix_a)

    assert s._backdrop._incoming_pixmap is pix_b
    assert s._backdrop._incoming_pixmap is not pix_a


def test_set_backdrop_pixmap_shows_image_on_backdrop(screen):
    pix = QPixmap(10, 10)
    pix.fill(Qt.GlobalColor.red)
    screen._set_backdrop_pixmap(pix)
    assert screen._backdrop._incoming_pixmap is not None


def test_cover_label_fixed_size_is_400(screen):
    assert screen._cover_label.size().width() == 400
    assert screen._cover_label.size().height() == 400


def test_set_cover_pixmap_scales_to_400(screen):
    pix = QPixmap(100, 100)
    pix.fill(Qt.GlobalColor.blue)
    screen._set_cover_pixmap(pix)
    scaled = screen._cover_label.pixmap()
    assert scaled is not None
    assert scaled.width() >= 400
    assert scaled.height() >= 400


def test_progress_bar_uses_accent_color(screen):
    from sixpack.ui import theme

    style = screen._progress_bar.styleSheet()
    assert theme.ACCENT in style
    assert theme.SURFACE_HIGH in style


def test_transport_buttons_remain_unfocusable(screen):
    for btn in (screen._prev_btn, screen._rew_btn, screen._fwd_btn, screen._next_btn):
        assert btn.focusPolicy() == Qt.FocusPolicy.NoFocus


def test_secondary_transport_buttons_are_flat_not_accent(screen):
    """The play/pause button keeps the accent fill; the secondary transport
    buttons must NOT — otherwise they'd visually compete with it."""
    from sixpack.ui import theme

    assert theme.ACCENT in screen._play_btn.styleSheet()
    for btn in (screen._prev_btn, screen._rew_btn, screen._fwd_btn, screen._next_btn):
        assert theme.ACCENT not in btn.styleSheet()
        assert "transparent" in btn.styleSheet()


# ----------------------------------------------------------------------
# Playback speed control (Task 5)
# ----------------------------------------------------------------------


def test_speed_starts_at_1x(screen):
    assert screen._speed_value_label.text() == "1.0x"


def test_up_key_cycles_speed_forward(qtbot, screen):
    screen.show()
    qtbot.waitExposed(screen)
    qtbot.keyClick(screen, Qt.Key.Key_Up)
    assert screen._speed_value_label.text() == "1.25x"
    assert screen._player.speed_calls == [1.25]


def test_speed_cycle_wraps_around(qtbot, screen):
    screen.show()
    qtbot.waitExposed(screen)
    for _ in range(5):  # 1.0 -> 1.25 -> 1.5 -> 1.75 -> 2.0 -> 1.0
        qtbot.keyClick(screen, Qt.Key.Key_Up)
    assert screen._speed_value_label.text() == "1.0x"
    assert screen._player.speed_calls[-1] == 1.0


# ----------------------------------------------------------------------
# In-player chapter access overlay (Task 6)
# ----------------------------------------------------------------------


def test_menu_key_opens_chapter_overlay(qtbot, screen):
    from sixpack.api.models import Chapter
    chapters = [Chapter(id=0, start=0.0, end=100.0, title="Ch1"),
                Chapter(id=1, start=100.0, end=200.0, title="Ch2")]
    screen.set_chapters(chapters)
    screen.show()
    qtbot.waitExposed(screen)

    assert not screen._chapter_overlay.isVisible()
    qtbot.keyClick(screen, Qt.Key.Key_Return)  # MENU in player mode
    assert screen._chapter_overlay.isVisible()


def test_menu_key_closes_open_overlay(qtbot, screen):
    from sixpack.api.models import Chapter
    screen.set_chapters([Chapter(id=0, start=0.0, end=100.0, title="Ch1")])
    screen.show()
    qtbot.waitExposed(screen)
    qtbot.keyClick(screen, Qt.Key.Key_Return)
    assert screen._chapter_overlay.isVisible()
    qtbot.keyClick(screen, Qt.Key.Key_Return)
    assert not screen._chapter_overlay.isVisible()


def test_select_in_overlay_seeks_and_closes(qtbot, screen):
    """Regression: the overlay must seek by TIME (seek_absolute), not by
    index (seek_to_chapter) — `row` indexes into self._chapters (ABS's own
    chapter metadata), a different domain than mpv's internally-derived
    chapter list that seek_to_chapter indexes into. See _on_overlay_chapter_
    activated's docstring in player.py for the full rationale."""
    from sixpack.api.models import Chapter
    screen.set_chapters([Chapter(id=0, start=0.0, end=100.0, title="Ch1"),
                          Chapter(id=1, start=100.0, end=200.0, title="Ch2")])
    screen.show()
    qtbot.waitExposed(screen)
    qtbot.keyClick(screen, Qt.Key.Key_Return)  # open
    screen._chapter_overlay.setCurrentRow(1)
    qtbot.keyClick(screen, Qt.Key.Key_Return)  # select — closes AND seeks

    assert screen._player.seek_absolute_calls == [100.0]
    assert screen._player.seek_to_chapter_calls == []
    assert not screen._chapter_overlay.isVisible()


def test_back_closes_overlay_without_seeking(qtbot, screen):
    from sixpack.api.models import Chapter
    screen.set_chapters([Chapter(id=0, start=0.0, end=100.0, title="Ch1")])
    screen.show()
    qtbot.waitExposed(screen)
    qtbot.keyClick(screen, Qt.Key.Key_Return)  # open
    qtbot.keyClick(screen, Qt.Key.Key_Escape)  # BACK

    assert screen._player.seek_absolute_calls == []
    assert screen._player.seek_to_chapter_calls == []
    assert not screen._chapter_overlay.isVisible()


def test_menu_key_does_nothing_without_chapters(qtbot, screen):
    """No chapters set (e.g. staleness/fallback path) — MENU must not crash
    and the overlay must simply not open."""
    screen.show()
    qtbot.waitExposed(screen)
    qtbot.keyClick(screen, Qt.Key.Key_Return)
    assert not screen._chapter_overlay.isVisible()


def test_up_down_navigate_overlay_without_cycling_speed(qtbot, screen):
    """Regression: while the overlay is open, UP must navigate the overlay,
    NOT cycle playback speed (Task 5's binding) — the speed label must stay
    unchanged and the overlay's current row must move."""
    from sixpack.api.models import Chapter
    screen.set_chapters([Chapter(id=0, start=0.0, end=100.0, title="Ch1"),
                          Chapter(id=1, start=100.0, end=200.0, title="Ch2")])
    screen.show()
    qtbot.waitExposed(screen)
    qtbot.keyClick(screen, Qt.Key.Key_Return)  # open — resumes at row 0
    assert screen._chapter_overlay.currentRow() == 0

    qtbot.keyClick(screen, Qt.Key.Key_Down)
    assert screen._chapter_overlay.currentRow() == 1
    assert screen._speed_value_label.text() == "1.0x"
    assert screen._player.speed_calls == []

    qtbot.keyClick(screen, Qt.Key.Key_Up)
    assert screen._chapter_overlay.currentRow() == 0
    assert screen._speed_value_label.text() == "1.0x"
    assert screen._player.speed_calls == []


# ----------------------------------------------------------------------
# Chapter reset on play_* (Task 6 review fix)
#
# app.py's _on_next_item/_on_prev_item handlers (bound to the next_item/
# prev_item manual-skip signals — reachable via the transport buttons and
# PageUp/PageDown) call play_book/play_library_item/play_playlist_item
# directly, bypassing BOTH of set_chapters()'s delivery paths. Without a
# reset, the chapter overlay would show a previous item's stale chapters
# over a different item's audio. Each play_* method must clear
# self._chapters so the overlay instead falls back to its existing
# no-chapters no-op (test_menu_key_does_nothing_without_chapters above)
# rather than showing wrong data.
# ----------------------------------------------------------------------


def test_play_book_resets_stale_chapters(qtbot):
    from sixpack.api.models import Chapter
    s = PlayerScreen(player=_FakePlayer())
    qtbot.addWidget(s)

    book_a = _book(book_id="a", title="Book A")
    book_b = _book(book_id="b", title="Book B")
    series = _series([book_a, book_b])

    s.play_book(book_a, 0.0, series, [book_a, book_b], "http://server", "tok")
    s.set_chapters([Chapter(id=0, start=0.0, end=100.0, title="A Ch1")])
    assert s._chapters != []

    # Simulate app.py's next-item handler calling play_book again WITHOUT
    # calling set_chapters() for the new book.
    s.play_book(book_b, 0.0, series, [book_a, book_b], "http://server", "tok")

    assert s._chapters == []


def test_play_library_item_resets_stale_chapters(qtbot):
    from sixpack.api.models import Chapter
    s = PlayerScreen(player=_FakePlayer())
    qtbot.addWidget(s)

    s.play_library_item(_library_item(item_id="i1"), 0.0, "http://server", "tok")
    s.set_chapters([Chapter(id=0, start=0.0, end=100.0, title="Ch1")])
    assert s._chapters != []

    s.play_library_item(_library_item(item_id="i2"), 0.0, "http://server", "tok")

    assert s._chapters == []


def test_play_playlist_item_resets_stale_chapters(qtbot):
    from sixpack.api.models import Chapter
    s = PlayerScreen(player=_FakePlayer())
    qtbot.addWidget(s)

    item_a = _playlist_item(item_id="a")
    item_b = _playlist_item(item_id="b")
    playlist = _playlist([item_a, item_b])

    s.play_playlist_item(item_a, 0.0, playlist, [item_a, item_b], "http://server", "tok")
    s.set_chapters([Chapter(id=0, start=0.0, end=100.0, title="Ch1")])
    assert s._chapters != []

    s.play_playlist_item(item_b, 0.0, playlist, [item_a, item_b], "http://server", "tok")

    assert s._chapters == []


# ----------------------------------------------------------------------
# Cross-mode per-item state reset (final whole-plan review, Fix 1 + Fix 3)
#
# PlayerScreen is a process-lifetime singleton reused across every item
# played. play_book() previously left playlist-mode fields
# (_current_playlist_item/_playlist/_playlist_items) untouched, and
# play_playlist_item() previously left series-mode fields (_current_book/
# _series/_series_books) untouched — so app.py's _on_track_ended, which
# branches on the series fields FIRST, could read stale cross-mode state
# after a session like: play a series book -> back out -> play a playlist
# item -> track ends. Both play_* methods now go through
# _reset_per_item_state(), which clears both sides unconditionally.
# ----------------------------------------------------------------------


def test_play_book_clears_stale_playlist_fields(qtbot):
    """Regression for Fix 1: playing a series book after a playlist item
    must clear the playlist-mode fields, or app.py's _on_track_ended could
    still see a stale _current_playlist_item/_playlist_items pair (not the
    bug path itself — that's the series-fields-checked-first order — but
    this is the other half of the same singleton-reuse bug: leftover
    cross-mode state that should never survive a play_book() call)."""
    s = PlayerScreen(player=_FakePlayer())
    qtbot.addWidget(s)

    item = _playlist_item(item_id="p1")
    playlist = _playlist([item])
    s.play_playlist_item(item, 0.0, playlist, [item], "http://server", "tok")
    assert s._current_playlist_item is not None
    assert s._playlist is not None
    assert s._playlist_items != []

    book = _book(book_id="b1")
    series = _series([book])
    s.play_book(book, 0.0, series, [book], "http://server", "tok")

    assert s._current_playlist_item is None
    assert s._playlist is None
    assert s._playlist_items == []


def test_play_playlist_item_clears_stale_series_fields(qtbot):
    """Regression for Fix 1: playing a playlist item after a series book
    must clear the series-mode fields (_current_book/_series/
    _series_books) — this is the field state app.py's _on_track_ended
    actually branches on FIRST, so leaving these stale after
    play_playlist_item() is exactly the reachable bug the final review
    traced: series book -> back out -> playlist item -> track ends would
    take the (wrong) series branch using the old book's stale title."""
    s = PlayerScreen(player=_FakePlayer())
    qtbot.addWidget(s)

    book = _book(book_id="b1")
    series = _series([book])
    s.play_book(book, 0.0, series, [book], "http://server", "tok")
    assert s._current_book is not None
    assert s._series is not None
    assert s._series_books != []

    item = _playlist_item(item_id="p1")
    playlist = _playlist([item])
    s.play_playlist_item(item, 0.0, playlist, [item], "http://server", "tok")

    assert s._current_book is None
    assert s._series is None
    assert s._series_books == []


def test_play_library_item_clears_both_sides(qtbot):
    """play_library_item() already cleared both sides before this fix wave
    — confirm it still does after routing through _reset_per_item_state()."""
    s = PlayerScreen(player=_FakePlayer())
    qtbot.addWidget(s)

    book = _book(book_id="b1")
    series = _series([book])
    s.play_book(book, 0.0, series, [book], "http://server", "tok")

    s.play_library_item(_library_item(item_id="i1"), 0.0, "http://server", "tok")

    assert s._current_book is None
    assert s._series is None
    assert s._series_books == []
    assert s._current_playlist_item is None
    assert s._playlist is None
    assert s._playlist_items == []


def test_play_podcast_episode_sets_item_and_episode_ids(qtbot):
    from sixpack.api.models import PodcastEpisode

    s = PlayerScreen(player=_FakePlayer())
    qtbot.addWidget(s)

    show = LibraryItem(
        id="show1", library_id="lib1", media_type="podcast",
        media=LibraryItemMedia(metadata={"title": "My Show"}),
    )
    episode = PodcastEpisode(id="ep1", library_item_id="show1", title="Episode One")

    s.play_podcast_episode(episode, show, 0.0, "http://abs.test", "tok")

    assert s._item_id == "show1"
    assert s._episode_id == "ep1"
    assert s._title_label.text() == "Episode One"
    assert s._series_label.text() == "My Show"


def test_progress_update_carries_podcast_episode_id(qtbot):
    from sixpack.api.models import PodcastEpisode

    s = PlayerScreen(player=_FakePlayer())
    qtbot.addWidget(s)

    show = LibraryItem(
        id="show1", library_id="lib1", media_type="podcast",
        media=LibraryItemMedia(metadata={"title": "My Show"}),
    )
    episode = PodcastEpisode(id="ep1", library_item_id="show1", title="Episode One")
    s.play_podcast_episode(episode, show, 0.0, "http://abs.test", "tok")
    s._duration = 1000.0
    s._position = 100.0

    received = []
    s.progress_update.connect(lambda *args: received.append(args))
    s._sync_progress()

    assert len(received) == 1
    assert received[0][0] == "show1"
    assert received[0][4] == "ep1"


def test_progress_update_episode_id_empty_for_library_item_playback(qtbot):
    """Regression guard: play_library_item (a book, not a podcast) must
    emit an empty episode id — _reset_per_item_state clearing _episode_id
    is what keeps book/playlist progress updates unaffected by this task."""
    s = PlayerScreen(player=_FakePlayer())
    qtbot.addWidget(s)

    s.play_library_item(_library_item(item_id="book1"), 0.0, "http://abs.test", "tok")
    s._duration = 1000.0
    s._position = 100.0

    received = []
    s.progress_update.connect(lambda *args: received.append(args))
    s._sync_progress()

    assert len(received) == 1
    assert received[0][4] == ""


def test_play_book_hides_and_clears_open_chapter_overlay(qtbot):
    """Regression for Fix 3: if the chapter overlay is left open (still
    visible+populated with the PREVIOUS item's rows) when a new item starts
    playing — e.g. via the transport's next/prev buttons, which stay
    mouse-clickable while the overlay is open — the overlay must not
    silently carry over into the new item. Without this reset the overlay
    would still be visible, still populated with the old item's chapter
    rows, and (per keyPressEvent's overlay-open branch) would hijack all
    player input for the new item until BACK/MENU is pressed."""
    from sixpack.api.models import Chapter

    s = PlayerScreen(player=_FakePlayer())
    qtbot.addWidget(s)
    s.show()

    book_a = _book(book_id="a", title="Book A")
    book_b = _book(book_id="b", title="Book B")
    series = _series([book_a, book_b])

    s.play_book(book_a, 0.0, series, [book_a, book_b], "http://server", "tok")
    s.set_chapters([Chapter(id=0, start=0.0, end=100.0, title="A Ch1")])
    s._toggle_chapter_overlay()  # open it, populated with book A's chapter
    assert s._chapter_overlay.isVisible()
    assert s._chapter_overlay.count() == 1

    # Simulate the transport next-button path: play_book() called again
    # directly, overlay never explicitly closed by the user.
    s.play_book(book_b, 0.0, series, [book_a, book_b], "http://server", "tok")

    assert not s._chapter_overlay.isVisible()
    assert s._chapter_overlay.count() == 0


# ----------------------------------------------------------------------
# Description panel
# ----------------------------------------------------------------------


def test_play_book_shows_description(qtbot):
    s = PlayerScreen(player=_FakePlayer())
    qtbot.addWidget(s)
    s.show()
    book = SeriesBook(
        id="b1", media=LibraryItemMedia(metadata={"title": "T", "description": "A tale."}),
        sequence="1",
    )
    s.play_book(book, 0.0, _series([book]), [book], "http://server", "tok")
    assert s._description_label.isVisible()
    assert s._description_label.text() == "A tale."


def test_play_book_hides_description_when_absent(qtbot):
    s = PlayerScreen(player=_FakePlayer())
    qtbot.addWidget(s)
    book = _book()  # no description in metadata
    s.play_book(book, 0.0, _series([book]), [book], "http://server", "tok")
    assert not s._description_label.isVisible()
    assert s._description_label.text() == ""


def test_play_library_item_shows_description(qtbot):
    s = PlayerScreen(player=_FakePlayer())
    qtbot.addWidget(s)
    s.show()
    item = LibraryItem(
        id="i1", library_id="lib1",
        media=LibraryItemMedia(metadata={"title": "T", "description": "Summary."}),
    )
    s.play_library_item(item, 0.0, "http://server", "tok")
    assert s._description_label.isVisible()
    assert s._description_label.text() == "Summary."


def test_play_playlist_item_shows_description(qtbot):
    s = PlayerScreen(player=_FakePlayer())
    qtbot.addWidget(s)
    s.show()
    library_item = LibraryItem(
        id="i1", library_id="lib1",
        media=LibraryItemMedia(metadata={"title": "T", "description": "Playlist item desc."}),
    )
    item = PlaylistItem(library_item_id="i1", library_item=library_item)
    s.play_playlist_item(item, 0.0, _playlist([item]), [item], "http://server", "tok")
    assert s._description_label.isVisible()
    assert s._description_label.text() == "Playlist item desc."


def test_play_podcast_episode_shows_description(qtbot):
    from sixpack.api.models import PodcastEpisode

    s = PlayerScreen(player=_FakePlayer())
    qtbot.addWidget(s)
    s.show()
    show = LibraryItem(
        id="show1", library_id="lib1", media_type="podcast",
        media=LibraryItemMedia(metadata={"title": "My Show"}),
    )
    episode = PodcastEpisode.model_validate({
        "id": "ep1", "libraryItemId": "show1", "title": "Ep One",
        "description": "Show notes.",
    })
    s.play_podcast_episode(episode, show, 0.0, "http://abs.test", "tok")
    assert s._description_label.isVisible()
    assert s._description_label.text() == "Show notes."


def test_description_switches_between_items(qtbot):
    """Regression: a later item with no description must hide the label
    again, not leave the previous item's text showing stale."""
    s = PlayerScreen(player=_FakePlayer())
    qtbot.addWidget(s)
    s.show()
    book_with_desc = SeriesBook(
        id="a", media=LibraryItemMedia(metadata={"title": "A", "description": "Has one."}),
    )
    book_without_desc = _book(book_id="b", title="B")
    series = _series([book_with_desc, book_without_desc])

    s.play_book(book_with_desc, 0.0, series, [book_with_desc, book_without_desc],
                "http://server", "tok")
    assert s._description_label.isVisible()

    s.play_book(book_without_desc, 0.0, series, [book_with_desc, book_without_desc],
                "http://server", "tok")
    assert not s._description_label.isVisible()


def test_description_truncated_at_word_boundary_with_ellipsis(qtbot):
    s = PlayerScreen(player=_FakePlayer())
    qtbot.addWidget(s)
    long_text = "word " * 200  # far beyond the 600-char cap
    book = SeriesBook(
        id="b1", media=LibraryItemMedia(metadata={"title": "T", "description": long_text}),
    )
    s.play_book(book, 0.0, _series([book]), [book], "http://server", "tok")
    shown = s._description_label.text()
    assert shown.endswith("…")
    assert len(shown) <= 601  # 600 chars + the ellipsis character
    assert not shown[:-1].endswith(" ")  # truncated at a word boundary, not mid-word


def test_description_short_text_not_truncated(qtbot):
    s = PlayerScreen(player=_FakePlayer())
    qtbot.addWidget(s)
    book = SeriesBook(
        id="b1", media=LibraryItemMedia(metadata={"title": "T", "description": "Short."}),
    )
    s.play_book(book, 0.0, _series([book]), [book], "http://server", "tok")
    assert s._description_label.text() == "Short."


# ----------------------------------------------------------------------
# Icon-font transport controls (chapters/speed buttons, glyph codepoints)
# ----------------------------------------------------------------------


def test_transport_buttons_use_icon_font_codepoints(screen):
    from sixpack.ui import theme

    assert screen._prev_btn.text() == theme.ICON_SKIP_PREVIOUS
    assert screen._next_btn.text() == theme.ICON_SKIP_NEXT
    assert screen._rew_btn.text() == theme.ICON_REPLAY_30
    assert screen._fwd_btn.text() == theme.ICON_FORWARD_30
    assert screen._play_btn.text() == theme.ICON_PAUSE
    assert screen._chapters_btn.text() == theme.ICON_MENU_BOOK
    assert screen._speed_btn.text() == theme.ICON_SPEED


def test_chapters_button_click_toggles_overlay(qtbot, screen):
    from sixpack.api.models import Chapter

    screen.set_chapters([Chapter(id=0, start=0.0, end=100.0, title="Ch1")])
    assert not screen._chapter_overlay.isVisible()

    qtbot.mouseClick(screen._chapters_btn, Qt.MouseButton.LeftButton)
    assert screen._chapter_overlay.isVisible()

    qtbot.mouseClick(screen._chapters_btn, Qt.MouseButton.LeftButton)
    assert not screen._chapter_overlay.isVisible()


def test_speed_button_click_cycles_speed(qtbot, screen):
    assert screen._speed_value_label.text() == "1.0x"
    qtbot.mouseClick(screen._speed_btn, Qt.MouseButton.LeftButton)
    assert screen._speed_value_label.text() == "1.25x"
    assert screen._player.speed_calls == [1.25]


def test_chapters_and_speed_buttons_are_unfocusable_and_muted(screen):
    from sixpack.ui import theme

    for btn in (screen._chapters_btn, screen._speed_btn):
        assert btn.focusPolicy() == Qt.FocusPolicy.NoFocus
        assert theme.TEXT_MUTED in btn.styleSheet()


def test_icon_buttons_zero_out_the_app_wide_button_padding(screen):
    """Regression: the app-wide QPushButton stylesheet sets `padding: 10px
    24px`. Without an explicit `padding: 0` override, that 24px-per-side
    horizontal padding exceeds the 44px fixed width of the chapters/speed
    buttons entirely, leaving negative room for the glyph -- confirmed via
    a real screenshot to render as a fully invisible icon, not just a
    slightly-off one. Every icon-only button must override it."""
    for btn in (
        screen._chapters_btn, screen._prev_btn, screen._rew_btn,
        screen._play_btn, screen._fwd_btn, screen._next_btn, screen._speed_btn,
    ):
        assert "padding: 0" in btn.styleSheet()
