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

    assert blocker.args[0].library_item_id == "li1"


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

    item = _make_item("li1", "Item", 3600.0)
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
