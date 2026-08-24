"""Tests for playlist UI screens using pytest-qt (headless)."""
from __future__ import annotations

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
    assert screen._hero_backdrop._hero_title.text() == "My Playlist"
    assert screen._grid.item_count == 2


def test_playlist_detail_screen_backdrop_not_occluded(qtbot):
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

    screen = PlaylistDetailScreen()
    qtbot.addWidget(screen)
    screen.resize(800, 600)
    screen.load(_make_playlist(), {}, "http://localhost", "tok")
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
    screen.update_progress({
        "li1": MediaProgress(
            libraryItemId="li1", currentTime=1800.0, duration=1800.0, isFinished=True
        )
    })
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


def test_playlist_detail_screen_item_progress_fraction(qtbot):
    """_item_progress computes current_time / duration, keyed by library_item_id."""
    screen = PlaylistDetailScreen()
    qtbot.addWidget(screen)
    item = _make_item("li1", "Item 1", 1800.0)
    prog = MediaProgress(libraryItemId="li1", currentTime=900.0, duration=1800.0, isFinished=False)
    fraction, finished = screen._item_progress(item, {"li1": prog})
    assert abs(fraction - 0.5) < 1e-6
    assert finished is False


def test_playlist_detail_screen_item_progress_finished_is_zero_fraction(qtbot):
    """A finished item reports fraction 0.0 regardless of current_time."""
    screen = PlaylistDetailScreen()
    qtbot.addWidget(screen)
    item = _make_item("li1", "Item 1", 1800.0)
    prog = MediaProgress(libraryItemId="li1", currentTime=1800.0, duration=1800.0, isFinished=True)
    fraction, finished = screen._item_progress(item, {"li1": prog})
    assert fraction == 0.0
    assert finished is True
