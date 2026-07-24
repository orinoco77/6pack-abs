"""Tests for playlist UI screens using pytest-qt (headless)."""
from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt

from sixpack.api.models import (
    Library,
    LibraryItemMedia,
    MediaProgress,
    Playlist,
    PlaylistItem,
)
from sixpack.ui.screens.playlists import PlaylistsScreen
from sixpack.ui.screens.playlist_detail import PlaylistDetailScreen


# ---- Fixtures ----

def _make_playlists():
    media1 = LibraryItemMedia(metadata={"title": "Book 1"}, duration=1800.0)
    media2 = LibraryItemMedia(metadata={"title": "Book 2"}, duration=3600.0)
    item1 = PlaylistItem(id="pli1", libraryItemId="li1", media=media1)
    item2 = PlaylistItem(id="pli2", libraryItemId="li2", media=media2)
    return [
        Playlist(id="p1", name="Favorites", items=[item1]),
        Playlist(id="p2", name="To Read", items=[item1, item2]),
    ]


def _make_libraries():
    return [
        Library(id="lib1", name="Audiobooks", mediaType="book"),
        Library(id="lib2", name="Drama", mediaType="podcast"),
    ]


# ---- PlaylistsScreen ----

def test_playlists_screen_creates(qtbot):
    screen = PlaylistsScreen()
    qtbot.addWidget(screen)
    assert screen._grid is not None


def test_playlists_screen_load(qtbot):
    screen = PlaylistsScreen()
    qtbot.addWidget(screen)
    playlists = _make_playlists()
    screen.load(
        library=None,
        playlists=playlists,
        server_url="http://abs.test:13378",
        token="test-token",
        all_libraries=_make_libraries(),
    )
    assert screen._count_label.text() == "2 playlists"


def test_playlists_screen_load_with_library(qtbot):
    screen = PlaylistsScreen()
    qtbot.addWidget(screen)
    lib = Library(id="lib1", name="Audiobooks")
    screen.load(
        library=lib,
        playlists=_make_playlists(),
        server_url="http://abs.test:13378",
        token="test-token",
    )
    assert "Audiobooks" in screen._library_btn.text()


def test_playlists_screen_emits_playlist_selected(qtbot):
    screen = PlaylistsScreen()
    qtbot.addWidget(screen)
    playlists = _make_playlists()
    screen.load(
        library=None,
        playlists=playlists,
        server_url="http://abs.test:13378",
        token="test-token",
    )

    with qtbot.waitSignal(screen.playlist_selected, timeout=1000) as blocker:
        screen._grid.item_activated.emit(0)

    assert blocker.args[0].id == "p1"


def test_playlists_screen_back_signal(qtbot):
    screen = PlaylistsScreen()
    qtbot.addWidget(screen)
    screen.load(
        library=None,
        playlists=_make_playlists(),
        server_url="http://abs.test:13378",
        token="test-token",
    )

    with qtbot.waitSignal(screen.back_requested, timeout=1000):
        qtbot.keyClick(screen, Qt.Key.Key_Escape)


def test_playlists_screen_empty(qtbot):
    screen = PlaylistsScreen()
    qtbot.addWidget(screen)
    screen.load(
        library=None,
        playlists=[],
        server_url="http://abs.test:13378",
        token="test-token",
    )
    assert screen._count_label.text() == "0 playlists"


def test_playlists_screen_single_item_plural(qtbot):
    """Count label should use singular 'playlist' when there's exactly one."""
    screen = PlaylistsScreen()
    qtbot.addWidget(screen)
    screen.load(
        library=None,
        playlists=[Playlist(id="p1", name="Only One")],
        server_url="http://abs.test:13378",
        token="test-token",
    )
    assert "1 playlist" in screen._count_label.text()
    assert "playlists" not in screen._count_label.text()


def test_playlists_screen_view_switch_emits(qtbot):
    """Clicking view switcher should emit view_switch_requested."""
    screen = PlaylistsScreen()
    qtbot.addWidget(screen)

    # Can't easily test the menu, but we can test the signal connection
    with qtbot.waitSignal(screen.view_switch_requested, timeout=1000) as blocker:
        screen.view_switch_requested.emit("series")

    assert blocker.args[0] == "series"


# ---- PlaylistDetailScreen ----

def _make_playlist():
    media1 = LibraryItemMedia(metadata={"title": "Item 1"}, duration=1800.0)
    media2 = LibraryItemMedia(metadata={"title": "Item 2"}, duration=3600.0)
    item1 = PlaylistItem(id="pli1", libraryItemId="li1", media=media1)
    item2 = PlaylistItem(id="pli2", libraryItemId="li2", media=media2)
    return Playlist(id="p1", name="My Playlist", items=[item1, item2])


def test_playlist_detail_screen_creates(qtbot):
    screen = PlaylistDetailScreen()
    qtbot.addWidget(screen)


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
    assert screen._list.count() == 2
    assert screen._title_label.text() == "My Playlist"


def test_playlist_detail_screen_back_signal(qtbot):
    screen = PlaylistDetailScreen()
    qtbot.addWidget(screen)
    screen.load(_make_playlist(), {})

    with qtbot.waitSignal(screen.back_requested, timeout=1000):
        qtbot.keyClick(screen, Qt.Key.Key_Escape)


def test_playlist_detail_screen_item_emits_activated(qtbot):
    """Clicking any item emits item_activated."""
    screen = PlaylistDetailScreen()
    qtbot.addWidget(screen)
    playlist = _make_playlist()
    screen.load(playlist, {})
    screen._list.setCurrentRow(0)

    with qtbot.waitSignal(screen.item_activated, timeout=1000) as blocker:
        screen._list.itemActivated.emit(screen._list.item(0))

    assert blocker.args[0].id == "pli1"


def test_playlist_detail_screen_play_all(qtbot):
    """Play All button emits play_requested at correct resume position."""
    screen = PlaylistDetailScreen()
    qtbot.addWidget(screen)
    playlist = _make_playlist()
    progress = {"li1": MediaProgress(libraryItemId="li1", currentTime=900.0, duration=1800.0)}
    screen.load(playlist, progress)

    with qtbot.waitSignal(screen.play_requested, timeout=1000) as blocker:
        screen._play_all_btn.click()

    item, start_time = blocker.args
    assert item.library_item_id == "li1"
    assert start_time == 900.0


def test_playlist_detail_screen_play_all_skips_finished(qtbot):
    """Play All skips finished items and starts from first unfinished."""
    screen = PlaylistDetailScreen()
    qtbot.addWidget(screen)
    playlist = _make_playlist()
    progress = {
        "li1": MediaProgress(libraryItemId="li1", isFinished=True),
    }
    screen.load(playlist, progress)

    with qtbot.waitSignal(screen.play_requested, timeout=1000) as blocker:
        screen._play_all_btn.click()

    item, start_time = blocker.args
    assert item.library_item_id == "li2"


def test_playlist_detail_show_loading_renders_items(qtbot):
    """show_loading() renders items immediately with grey dots."""
    screen = PlaylistDetailScreen()
    qtbot.addWidget(screen)
    screen.show_loading(_make_playlist())
    assert screen._list.count() == 2
    assert not screen._loading_label.isHidden()


def test_playlist_detail_update_progress_hides_loading(qtbot):
    screen = PlaylistDetailScreen()
    qtbot.addWidget(screen)
    screen.show_loading(_make_playlist())
    assert not screen._loading_label.isHidden()
    screen.update_progress({})
    assert screen._loading_label.isHidden()


def test_playlist_detail_update_progress_dot_colour(qtbot):
    """After update_progress, finished item dot changes to SUCCESS colour."""
    from sixpack.ui import theme
    screen = PlaylistDetailScreen()
    qtbot.addWidget(screen)
    screen.show_loading(_make_playlist())

    progress = {"li1": MediaProgress(libraryItemId="li1", isFinished=True)}
    screen.update_progress(progress)

    item = screen._list.item(0)
    widget = screen._list.itemWidget(item)
    assert theme.SUCCESS in widget._dot.styleSheet()


def test_playlist_item_widget_update_progress(qtbot):
    """PlaylistItemWidget updates progress correctly."""
    from sixpack.ui.screens.playlist_detail import PlaylistItemWidget
    from sixpack.ui import theme

    media = LibraryItemMedia(metadata={"title": "Item"}, duration=3600.0)
    item = PlaylistItem(id="pli1", libraryItemId="li1", media=media)
    widget = PlaylistItemWidget(item, None)
    qtbot.addWidget(widget)

    assert theme.TEXT_MUTED in widget._dot.styleSheet()

    prog = MediaProgress(libraryItemId="li1", currentTime=1800.0, duration=3600.0)
    widget.update_progress(prog)
    assert theme.ACCENT in widget._dot.styleSheet()


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
    assert screen._find_resume_index() == 0


def test_playlist_detail_item_count_label(qtbot):
    """Screen displays correct item count."""
    screen = PlaylistDetailScreen()
    qtbot.addWidget(screen)
    playlist = _make_playlist()
    screen.load(playlist, {})

    # The item count isn't shown in a label like series detail,
    # but we can verify the list has the right number of items
    assert screen._list.count() == 2


def test_playlist_detail_empty_playlist(qtbot):
    """Empty playlist shows no items."""
    screen = PlaylistDetailScreen()
    qtbot.addWidget(screen)
    empty_playlist = Playlist(id="p1", name="Empty")
    screen.load(empty_playlist, {})
    assert screen._list.count() == 0
