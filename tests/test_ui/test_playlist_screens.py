"""Tests for playlist UI screens using pytest-qt (headless)."""
from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt

from sixpack.api.models import (
    LibraryItem,
    LibraryItemMedia,
    MediaProgress,
    Playlist,
    PlaylistItem,
)
from sixpack.ui.screens.playlist_detail import PlaylistDetailScreen


# ---- Fixtures ----

def _make_item(library_item_id, title, duration):
    """Build a PlaylistItem with the real nested ``libraryItem`` shape."""
    library_item = LibraryItem(
        id=library_item_id,
        libraryId="lib1",
        mediaType="book",
        media=LibraryItemMedia(metadata={"title": title}, duration=duration),
    )
    return PlaylistItem(libraryItemId=library_item_id, libraryItem=library_item)


# ---- PlaylistDetailScreen ----

def _make_playlist():
    item1 = _make_item("li1", "Item 1", 1800.0)
    item2 = _make_item("li2", "Item 2", 3600.0)
    return Playlist(id="p1", name="My Playlist", items=[item1, item2])


def test_playlist_detail_screen_creates(qtbot):
    screen = PlaylistDetailScreen()
    qtbot.addWidget(screen)
    assert screen._grid is not None


def test_playlist_detail_screen_load(qtbot):
    screen = PlaylistDetailScreen()
    qtbot.addWidget(screen)
    playlist = _make_playlist()
    screen.load(
        playlist=playlist,
        progress={},
        server_url="http://abs.test:13378",
        token="test-token",
    )
    assert screen._hero_title.text() == "My Playlist"
    assert screen._grid.item_count == 2


def test_playlist_detail_screen_back_signal(qtbot):
    screen = PlaylistDetailScreen()
    qtbot.addWidget(screen)
    screen.load(_make_playlist(), {})
    screen.show()

    with qtbot.waitSignal(screen.back_requested, timeout=1000):
        qtbot.keyClick(screen, Qt.Key.Key_Escape)


def test_playlist_detail_screen_item_emits_activated(qtbot):
    """Activating any item emits item_activated."""
    screen = PlaylistDetailScreen()
    qtbot.addWidget(screen)
    playlist = _make_playlist()
    screen.load(playlist, {})

    with qtbot.waitSignal(screen.item_activated, timeout=1000) as blocker:
        screen._grid.item_activated.emit(0)

    assert blocker.args[0].library_item_id == "li1"


def test_playlist_detail_show_loading_renders_items(qtbot):
    """show_loading() renders items immediately."""
    screen = PlaylistDetailScreen()
    qtbot.addWidget(screen)
    screen.show_loading(_make_playlist())
    assert screen._grid.item_count == 2


def test_playlist_detail_update_progress_refreshes_in_place(qtbot):
    screen = PlaylistDetailScreen()
    qtbot.addWidget(screen)
    playlist = _make_playlist()
    screen.load(playlist, {}, "http://abs.test:13378", "test-token")
    card_before = screen._grid._items[0]
    screen.update_progress(
        {"li1": MediaProgress(libraryItemId="li1", currentTime=1800.0, duration=1800.0, isFinished=True)}
    )
    assert screen._grid._items[0] is card_before


def test_playlist_detail_resume_index_all_finished(qtbot):
    """When all items finished, resume from start."""
    screen = PlaylistDetailScreen()
    qtbot.addWidget(screen)
    playlist = _make_playlist()
    progress = {
        "li1": MediaProgress(libraryItemId="li1", isFinished=True),
        "li2": MediaProgress(libraryItemId="li2", isFinished=True),
    }
    screen.load(playlist, progress)
    assert screen._grid._focused_index == 0  # _find_resume_index falls back to 0


def test_playlist_detail_focus_item_by_key(qtbot):
    screen = PlaylistDetailScreen()
    qtbot.addWidget(screen)
    screen.load(_make_playlist(), {}, "http://abs.test:13378", "test-token")
    screen.focus_item_by_key("li2")
    assert screen._grid._focused_index == 1


def test_playlist_detail_empty_playlist(qtbot):
    """Empty playlist shows no items."""
    screen = PlaylistDetailScreen()
    qtbot.addWidget(screen)
    empty_playlist = Playlist(id="p1", name="Empty")
    screen.load(empty_playlist, {})
    assert screen._grid.item_count == 0
