"""Tests for PlayerScreen's up-next display, track_ended signal, and the
cinematic-redesign visual wiring (Backdrop feed, larger cover, restyled
progress/transport controls)."""
from __future__ import annotations

from unittest.mock import MagicMock

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
from sixpack.player.player import AudioPlayer
from sixpack.ui.screens.player import PlayerScreen


class _FakePlayer:
    """Stands in for AudioPlayer — PlayerScreen only needs on_*/toggle_pause/
    seek_*/stop/set_speed/seek_to_chapter/chapter_count/current_chapter on it,
    matching AudioPlayer's real interface without constructing real mpv."""

    def __init__(self):
        self.speed_calls = []
        self.seek_to_chapter_calls = []
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
    assert fake_cache.fetch_backdrop_calls[0][2] == s._set_backdrop_pixmap


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
