"""Tests for the Kodi-style BrowseScreen."""
from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt

from sixpack.api.models import (
    Library,
    LibraryItem,
    LibraryItemMedia,
    PodcastEpisode,
    Playlist,
    PlaylistItem,
    Series,
    SeriesBook,
)
from sixpack.input.actions import InputAction
from sixpack.ui.screens.browse import (
    DEFAULT_ROW_TYPES,
    BrowseScreen,
    RowType,
    _RowWidget,
    _SidebarItem,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _lib(lid, name):
    return Library(id=lid, name=name, mediaType="book")


def _li(item_id, title, author="Author"):
    return LibraryItem(
        id=item_id,
        libraryId="lib1",
        mediaType="book",
        media=LibraryItemMedia(metadata={"title": title, "authorName": author}),
    )


def _series(sid, name, n_books=2):
    books = [
        SeriesBook(
            id=f"b{i}",
            libraryId="lib1",
            media=LibraryItemMedia(metadata={"title": f"Book {i}"}),
            sequence=str(i),
        )
        for i in range(n_books)
    ]
    return Series(id=sid, name=name, books=books)


def _playlist(pid, name, n_items=1):
    items = []
    for i in range(n_items):
        li = _li(f"pli{i}", f"Track {i}")
        items.append(PlaylistItem(libraryItemId=li.id, libraryItem=li))
    return Playlist(id=pid, name=name, items=items)


def _podcast_show(item_id="show1", name="My Show"):
    return LibraryItem(
        id=item_id, libraryId="lib1", mediaType="podcast",
        media=LibraryItemMedia(metadata={"title": name}),
    )


def _podcast_show_with_recent_episode(item_id="show1", name="My Show"):
    episode = PodcastEpisode(id="ep1", libraryItemId=item_id, title="Recent Episode")
    return LibraryItem(
        id=item_id, libraryId="lib1", mediaType="podcast",
        media=LibraryItemMedia(metadata={"title": name}),
        recentEpisode=episode,
    )


def _press(qtbot, widget, key):
    qtbot.keyPress(widget, key)


# ---------------------------------------------------------------------------
# RowType enum
# ---------------------------------------------------------------------------

def test_row_type_values():
    assert RowType.CONTINUE_LISTENING.value == "Continue Listening"
    assert RowType.RECENTLY_ADDED.value == "Recently Added"
    assert RowType.SERIES.value == "Series"
    assert RowType.PLAYLISTS.value == "Playlists"


def test_default_row_types_order():
    assert DEFAULT_ROW_TYPES == [
        RowType.CONTINUE_LISTENING,
        RowType.RECENTLY_ADDED,
        RowType.SERIES,
        RowType.PLAYLISTS,
    ]


# ---------------------------------------------------------------------------
# _SidebarItem
# ---------------------------------------------------------------------------

def test_sidebar_item_creates(qtbot):
    item = _SidebarItem("Audiobooks")
    qtbot.addWidget(item)
    assert item._label.text() == "Audiobooks"


def test_sidebar_item_set_state_active(qtbot):
    item = _SidebarItem("Audiobooks")
    qtbot.addWidget(item)
    item.set_state(selected=True, zone_active=True)
    # Just verify it doesn't crash and label is present
    assert item._label.text() == "Audiobooks"


def test_sidebar_item_set_state_inactive(qtbot):
    item = _SidebarItem("Audiobooks")
    qtbot.addWidget(item)
    item.set_state(selected=False, zone_active=False)
    assert item._label.text() == "Audiobooks"


def test_sidebar_item_set_state_selected_not_active(qtbot):
    item = _SidebarItem("Audiobooks")
    qtbot.addWidget(item)
    item.set_state(selected=True, zone_active=False)
    assert item._label.text() == "Audiobooks"


# ---------------------------------------------------------------------------
# _RowWidget
# ---------------------------------------------------------------------------

def test_row_widget_creates(qtbot):
    rw = _RowWidget("Continue Listening")
    qtbot.addWidget(rw)
    assert rw._title_lbl.text() == "Continue Listening"
    assert rw.card_count == 0


def test_row_widget_add_cards(qtbot):
    from sixpack.ui.widgets.media_card import MediaCard
    rw = _RowWidget("Series")
    qtbot.addWidget(rw)
    card = MediaCard(title="A Book")
    rw.add_card(card)
    assert rw.card_count == 1


def test_row_widget_clear(qtbot):
    from sixpack.ui.widgets.media_card import MediaCard
    rw = _RowWidget("Series")
    qtbot.addWidget(rw)
    rw.add_card(MediaCard(title="Book 1"))
    rw.add_card(MediaCard(title="Book 2"))
    rw.clear()
    assert rw.card_count == 0


def test_row_widget_focus_card(qtbot):
    from sixpack.ui.widgets.media_card import MediaCard
    rw = _RowWidget("Series")
    qtbot.addWidget(rw)
    c1 = MediaCard(title="A")
    c2 = MediaCard(title="B")
    rw.add_card(c1)
    rw.add_card(c2)
    rw.focus_card(0)
    assert rw.focused_idx == 0
    rw.focus_card(1)
    assert rw.focused_idx == 1


def test_row_widget_unfocus(qtbot):
    from sixpack.ui.widgets.media_card import MediaCard
    rw = _RowWidget("Series")
    qtbot.addWidget(rw)
    rw.add_card(MediaCard(title="A"))
    rw.focus_card(0)
    rw.unfocus()
    # focused_idx stays, but card is visually unfocused — just verify no crash
    assert rw.focused_idx == 0


def test_row_widget_set_row_focused(qtbot):
    rw = _RowWidget("Series")
    qtbot.addWidget(rw)
    rw.set_row_focused(True)
    rw.set_row_focused(False)


# ---------------------------------------------------------------------------
# BrowseScreen — construction
# ---------------------------------------------------------------------------

def test_browse_screen_creates(qtbot):
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    assert len(screen._row_widgets) == len(DEFAULT_ROW_TYPES)
    assert screen._zone == "sidebar"


def test_browse_screen_custom_row_types(qtbot):
    screen = BrowseScreen(row_types=[RowType.SERIES, RowType.PLAYLISTS])
    qtbot.addWidget(screen)
    assert len(screen._row_widgets) == 2
    assert screen._row_types == [RowType.SERIES, RowType.PLAYLISTS]


# ---------------------------------------------------------------------------
# BrowseScreen — load_libraries
# ---------------------------------------------------------------------------

def test_browse_screen_load_libraries(qtbot):
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    libs = [_lib("l1", "Audiobooks"), _lib("l2", "Big Finish")]
    screen.load_libraries(libs, "http://server", "token")
    assert len(screen._sidebar_items) == 2
    assert screen._sidebar_items[0]._label.text() == "Audiobooks"
    assert screen._sidebar_items[1]._label.text() == "Big Finish"


def test_browse_screen_load_libraries_resets_state(qtbot):
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    libs = [_lib("l1", "Audiobooks")]
    screen.load_libraries(libs, "http://s", "tok")
    assert screen._sidebar_idx == 0
    assert screen._loaded_library is None


def test_sidebar_layout_ends_with_trailing_stretch(qtbot):
    """Without a trailing addStretch(), items expand to fill the column,
    stretching each _SidebarItem's `border-left` accent bar across the
    whole remaining column height instead of staying item-sized."""
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "A"), _lib("l2", "B")], "http://s", "tok")
    layout = screen._sidebar_items_layout
    assert layout.count() == 3  # 2 sidebar items + 1 trailing stretch
    last_item = layout.itemAt(layout.count() - 1)
    assert last_item.widget() is None  # a stretch/spacer, not a sidebar item


def test_sidebar_layout_stretch_not_duplicated_on_reload(qtbot):
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "A")], "http://s", "tok")
    screen.load_libraries([_lib("l1", "A"), _lib("l2", "B")], "http://s", "tok")
    layout = screen._sidebar_items_layout
    assert layout.count() == 3  # 2 items + exactly one trailing stretch


# ---------------------------------------------------------------------------
# BrowseScreen — set_row_items
# ---------------------------------------------------------------------------

def test_browse_screen_set_row_items(qtbot):
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "Audiobooks")], "http://s", "tok")
    items = [_li("i1", "Book A"), _li("i2", "Book B")]
    screen.set_row_items(RowType.RECENTLY_ADDED, items)
    ra_idx = screen._row_types.index(RowType.RECENTLY_ADDED)
    assert screen._row_items[ra_idx] == items
    assert screen._row_widgets[ra_idx].card_count == 2


def test_browse_screen_set_row_items_unknown_type(qtbot):
    screen = BrowseScreen(row_types=[RowType.SERIES])
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "Audiobooks")], "http://s", "tok")
    # Setting an item type not in row_types should not crash
    screen.set_row_items(RowType.PLAYLISTS, [_playlist("p1", "P")])


# ---------------------------------------------------------------------------
# BrowseScreen — sidebar zone keyboard navigation
# ---------------------------------------------------------------------------

def test_sidebar_down_moves_selection(qtbot):
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "A"), _lib("l2", "B")], "http://s", "tok")
    screen.show()
    assert screen._sidebar_idx == 0
    _press(qtbot, screen, Qt.Key.Key_Down)
    assert screen._sidebar_idx == 1


def test_sidebar_up_does_not_go_negative(qtbot):
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "A"), _lib("l2", "B")], "http://s", "tok")
    screen.show()
    _press(qtbot, screen, Qt.Key.Key_Up)
    assert screen._sidebar_idx == 0


def test_sidebar_down_clamps_at_end(qtbot):
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "A")], "http://s", "tok")
    screen.show()
    _press(qtbot, screen, Qt.Key.Key_Down)
    assert screen._sidebar_idx == 0  # still 0 (only 1 library)


def test_sidebar_right_enters_rows(qtbot):
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "A")], "http://s", "tok")
    screen.show()
    _press(qtbot, screen, Qt.Key.Key_Right)
    assert screen._zone == "rows"


def test_sidebar_select_enters_rows(qtbot):
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "A")], "http://s", "tok")
    screen.show()
    _press(qtbot, screen, Qt.Key.Key_Return)
    assert screen._zone == "rows"


def test_sidebar_right_no_libraries_stays_in_sidebar(qtbot):
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    screen.show()
    _press(qtbot, screen, Qt.Key.Key_Right)
    assert screen._zone == "sidebar"


# ---------------------------------------------------------------------------
# BrowseScreen — library_changed signal
# ---------------------------------------------------------------------------

def test_library_changed_emitted_on_enter_rows(qtbot):
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    libs = [_lib("l1", "A"), _lib("l2", "B")]
    screen.load_libraries(libs, "http://s", "tok")
    screen.show()
    with qtbot.waitSignal(screen.library_changed, timeout=500) as blocker:
        _press(qtbot, screen, Qt.Key.Key_Right)
    assert blocker.args[0].id == "l1"


def test_library_changed_not_emitted_twice_same_library(qtbot):
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "A")], "http://s", "tok")
    screen.show()
    signals = []
    screen.library_changed.connect(lambda lib: signals.append(lib))
    _press(qtbot, screen, Qt.Key.Key_Right)  # enters rows → emits
    _press(qtbot, screen, Qt.Key.Key_Backspace)  # back to sidebar
    _press(qtbot, screen, Qt.Key.Key_Right)  # enters rows again — same lib, no re-emit
    assert len(signals) == 1


def test_library_changed_emitted_on_sidebar_down(qtbot):
    """Down arrow in sidebar immediately emits library_changed for the new library."""
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    libs = [_lib("l1", "A"), _lib("l2", "B")]
    screen.load_libraries(libs, "http://s", "tok")
    screen.show()
    signals = []
    screen.library_changed.connect(lambda lib: signals.append(lib))
    _press(qtbot, screen, Qt.Key.Key_Right)  # l1 → emits (enter rows)
    _press(qtbot, screen, Qt.Key.Key_Backspace)  # back to sidebar
    _press(qtbot, screen, Qt.Key.Key_Down)  # highlight l2 → emits immediately
    assert len(signals) == 2
    assert signals[1].id == "l2"


def test_library_changed_emitted_for_second_library(qtbot):
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    libs = [_lib("l1", "A"), _lib("l2", "B")]
    screen.load_libraries(libs, "http://s", "tok")
    screen.show()
    signals = []
    screen.library_changed.connect(lambda lib: signals.append(lib))
    _press(qtbot, screen, Qt.Key.Key_Right)       # enters rows for l1
    _press(qtbot, screen, Qt.Key.Key_Backspace)   # back to sidebar
    _press(qtbot, screen, Qt.Key.Key_Down)        # highlight l2 → eager emit
    _press(qtbot, screen, Qt.Key.Key_Right)       # enters rows for l2 — already loaded, no re-emit
    assert len(signals) == 2
    assert signals[1].id == "l2"


def test_reset_rows_shows_loading_page(qtbot):
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "A")], "http://s", "tok")
    screen._reset_rows()
    assert screen._loading is True
    assert screen._content_stack.currentIndex() == 2


def test_show_content_switches_to_rows_page(qtbot):
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "A")], "http://s", "tok")
    screen._reset_rows()
    assert screen._content_stack.currentIndex() == 2
    screen._zone = "rows"
    screen.show_content()
    assert screen._loading is False
    assert screen._content_stack.currentIndex() == 0


def test_reset_rows_clears_hero(qtbot):
    """_reset_rows() must clear the hero along with the row data it
    discards — otherwise switching libraries in the sidebar leaves the
    previous library's title/author showing over the new (empty, still
    loading) content until the user happens to enter rows again."""
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    item = _li("i1", "Lib1 Book")
    screen._reflect_focus(item)
    assert screen._hero_title.text() == "Lib1 Book"

    screen._reset_rows()

    assert screen._hero_title.text() == ""
    assert screen._hero_sub.text() == ""


def test_sidebar_down_to_unloaded_library_shows_new_library_name(qtbot):
    """Regression test: switching the sidebar selection to a library whose
    content hasn't loaded yet must not leave the previously-focused
    library's item still showing in the hero — it should show the newly
    highlighted library's name instead (sidebar zone: nothing is actually
    selected yet)."""
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "A"), _lib("l2", "B")], "http://s", "tok")
    screen.show()

    screen._loaded_library = screen._libraries[0]
    screen.set_row_items(RowType.RECENTLY_ADDED, [_li("i1", "Lib1 Book")])
    screen.show_content()
    screen._enter_rows()
    screen._handle_rows(InputAction.DOWN)  # focus the Recently Added row
    assert screen._hero_title.text() == "Lib1 Book"

    _press(qtbot, screen, Qt.Key.Key_Backspace)  # back to sidebar
    _press(qtbot, screen, Qt.Key.Key_Down)  # highlight lib2 (not yet loaded)

    assert screen._hero_title.text() == "B"
    assert screen._hero_sub.text() == ""


def test_sidebar_zone_shows_library_name_not_item_preview(qtbot):
    """Sidebar zone: the hero must show the highlighted library's name,
    never a preview of an item from its rows — even once that library's
    content has finished loading, and even if the user never leaves the
    sidebar to trigger navigation-driven reflection."""
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "A"), _lib("l2", "B")], "http://s", "tok")
    screen.show()
    assert screen._hero_title.text() == "A"  # initial load, still in sidebar

    _press(qtbot, screen, Qt.Key.Key_Down)  # highlight lib2, still in sidebar
    assert screen._zone == "sidebar"
    assert screen._hero_title.text() == "B"

    screen.set_row_items(RowType.RECENTLY_ADDED, [_li("i2", "Lib2 Book")])
    screen.show_content()

    assert screen._hero_title.text() == "B"  # not "Lib2 Book"


# ---------------------------------------------------------------------------
# BrowseScreen — rows zone keyboard navigation
# ---------------------------------------------------------------------------

def _make_screen_with_items(qtbot):
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "A")], "http://s", "tok")
    screen.set_row_items(RowType.CONTINUE_LISTENING, [_li("i1", "CL1"), _li("i2", "CL2")])
    screen.set_row_items(RowType.RECENTLY_ADDED, [_li("i3", "RA1")])
    screen.set_row_items(RowType.SERIES, [_series("s1", "S1")])
    screen.set_row_items(RowType.PLAYLISTS, [_playlist("p1", "PL1")])
    screen.show()
    # Enter rows
    screen._zone = "rows"
    screen._focused_row = 0
    screen._update_row_styles()
    return screen


def test_rows_down_moves_focused_row(qtbot):
    screen = _make_screen_with_items(qtbot)
    screen.setFocus()
    _press(qtbot, screen, Qt.Key.Key_Down)
    assert screen._focused_row == 1


def test_rows_down_clamps_at_last_row(qtbot):
    screen = _make_screen_with_items(qtbot)
    screen.setFocus()
    n = len(DEFAULT_ROW_TYPES)
    for _ in range(n + 2):
        _press(qtbot, screen, Qt.Key.Key_Down)
    assert screen._focused_row == n - 1


def test_rows_up_clamps_at_zero(qtbot):
    screen = _make_screen_with_items(qtbot)
    screen.setFocus()
    _press(qtbot, screen, Qt.Key.Key_Up)
    assert screen._focused_row == 0


def test_row_zero_scroll_resets_to_top_when_navigating_back_up(qtbot):
    """Regression test: QScrollArea.ensureWidgetVisible()'s default 50px
    margin only guarantees the target row is visible WITH some breathing
    room — it doesn't guarantee scroll=0 when the target is row 0. Row 0's
    title bar sits at the very top of the scrollable content (rows_layout's
    top margin reserves clearance for the hero overlay above it, nothing
    else does), so any nonzero residual scroll pushes that title up
    underneath the hero band. Reported live: after scrolling down several
    rows (e.g. picking a series, playing a book, coming back) and
    navigating back up to row 0, its title vanished under the hero."""
    screen = _make_screen_with_items(qtbot)
    screen.resize(1920, 700)  # short enough that all 4 rows don't fit at once
    screen.setFocus()

    for _ in range(3):
        _press(qtbot, screen, Qt.Key.Key_Down)  # row 0 -> 1 -> 2 -> 3
    assert screen._focused_row == 3
    assert screen._rows_scroll.verticalScrollBar().value() > 0

    for _ in range(3):
        _press(qtbot, screen, Qt.Key.Key_Up)  # row 3 -> 2 -> 1 -> 0
    assert screen._focused_row == 0

    assert screen._rows_scroll.verticalScrollBar().value() == 0


def test_rows_up_from_second_row(qtbot):
    screen = _make_screen_with_items(qtbot)
    screen._focused_row = 2
    screen.setFocus()
    _press(qtbot, screen, Qt.Key.Key_Up)
    assert screen._focused_row == 1


def test_rows_right_moves_item_index(qtbot):
    screen = _make_screen_with_items(qtbot)
    screen._row_item_idxs[0] = 0
    screen.setFocus()
    _press(qtbot, screen, Qt.Key.Key_Right)
    assert screen._row_item_idxs[0] == 1


def test_rows_right_at_last_item_focuses_see_all(qtbot):
    screen = _make_screen_with_items(qtbot)
    screen._row_item_idxs[0] = 1  # already at last item (2 items)
    screen.setFocus()
    _press(qtbot, screen, Qt.Key.Key_Right)
    assert screen._see_all_focused is True
    assert screen._zone == "rows"  # stays in rows until Enter is pressed


def test_see_all_left_returns_to_last_card(qtbot):
    screen = _make_screen_with_items(qtbot)
    screen._row_item_idxs[0] = 1
    screen.setFocus()
    _press(qtbot, screen, Qt.Key.Key_Right)   # focus see-all
    assert screen._see_all_focused is True
    _press(qtbot, screen, Qt.Key.Key_Left)    # back to last card
    assert screen._see_all_focused is False
    assert screen._zone == "rows"


def test_see_all_select_emits_signal(qtbot):
    screen = _make_screen_with_items(qtbot)
    screen._row_item_idxs[0] = 1
    screen.setFocus()
    _press(qtbot, screen, Qt.Key.Key_Right)   # focus see-all
    with qtbot.waitSignal(screen.see_all_requested, timeout=500) as blocker:
        _press(qtbot, screen, Qt.Key.Key_Return)
    assert blocker.args[0] == RowType.CONTINUE_LISTENING
    assert screen._zone == "grid"


def test_see_all_up_clears_focus(qtbot):
    screen = _make_screen_with_items(qtbot)
    screen._row_item_idxs[0] = 1
    screen.setFocus()
    _press(qtbot, screen, Qt.Key.Key_Right)   # focus see-all
    assert screen._see_all_focused is True
    _press(qtbot, screen, Qt.Key.Key_Up)      # change row
    assert screen._see_all_focused is False


def test_populate_grid_fills_cards(qtbot):
    screen = _make_screen_with_items(qtbot)
    screen._zone = "grid"
    screen._grid_row_idx = 2  # SERIES row
    items = [_series(f"s{i}", f"S{i}") for i in range(10)]
    screen.populate_grid(items)
    assert len(screen._grid_cards) == 10
    assert screen._grid_body_stack.currentIndex() == 1


def test_rows_left_moves_item_index(qtbot):
    screen = _make_screen_with_items(qtbot)
    screen._row_item_idxs[0] = 1
    screen._row_widgets[0].focus_card(1)
    screen.setFocus()
    _press(qtbot, screen, Qt.Key.Key_Left)
    assert screen._row_item_idxs[0] == 0


def test_rows_left_at_first_item_enters_sidebar(qtbot):
    screen = _make_screen_with_items(qtbot)
    screen._row_item_idxs[0] = 0
    screen.setFocus()
    _press(qtbot, screen, Qt.Key.Key_Left)
    assert screen._zone == "sidebar"


def test_rows_back_enters_sidebar(qtbot):
    screen = _make_screen_with_items(qtbot)
    screen.setFocus()
    _press(qtbot, screen, Qt.Key.Key_Backspace)
    assert screen._zone == "sidebar"


def test_rows_menu_enters_grid(qtbot):
    screen = _make_screen_with_items(qtbot)
    screen.setFocus()
    # use X key — no mapping. Use Enter which maps to SELECT, not MENU.
    # MENU is not in _NAV_MAP, so we need to call _enter_grid directly.
    screen._focused_row = 2  # SERIES row which has items
    screen._enter_grid(2)
    assert screen._zone == "grid"


# ---------------------------------------------------------------------------
# BrowseScreen — item activation signals in rows zone
# ---------------------------------------------------------------------------

def test_rows_select_continue_listening_emits_book(qtbot):
    screen = _make_screen_with_items(qtbot)
    screen._focused_row = 0
    screen.setFocus()
    with qtbot.waitSignal(screen.book_selected, timeout=500) as blocker:
        screen._activate_row_item(0, 0)
    assert blocker.args[0].id == "i1"


def test_rows_select_recently_added_emits_book(qtbot):
    screen = _make_screen_with_items(qtbot)
    screen._focused_row = 1
    with qtbot.waitSignal(screen.book_selected, timeout=500) as blocker:
        screen._activate_row_item(1, 0)
    assert blocker.args[0].id == "i3"


def test_rows_select_series_emits_series(qtbot):
    screen = _make_screen_with_items(qtbot)
    with qtbot.waitSignal(screen.series_selected, timeout=500) as blocker:
        screen._activate_row_item(2, 0)  # SERIES row
    assert blocker.args[0].id == "s1"


def test_rows_select_playlist_emits_playlist(qtbot):
    screen = _make_screen_with_items(qtbot)
    with qtbot.waitSignal(screen.playlist_selected, timeout=500) as blocker:
        screen._activate_row_item(3, 0)  # PLAYLISTS row
    assert blocker.args[0].id == "p1"


def test_rows_select_out_of_bounds_does_nothing(qtbot):
    screen = _make_screen_with_items(qtbot)
    fired = []
    screen.book_selected.connect(lambda x: fired.append(x))
    screen._activate_row_item(0, 99)  # out of range
    assert not fired


# ---------------------------------------------------------------------------
# BrowseScreen — grid zone
# ---------------------------------------------------------------------------

def _make_screen_in_grid(qtbot, row_idx=2):
    screen = _make_screen_with_items(qtbot)
    screen._enter_grid(row_idx)
    screen.setFocus()
    return screen


def test_enter_grid_switches_content_page(qtbot):
    screen = _make_screen_in_grid(qtbot, 2)
    assert screen._zone == "grid"
    assert screen._content_stack.currentIndex() == 1


def test_grid_page_top_margin_clears_the_hero(qtbot):
    """The hero overlay is a fixed-height widget stacked on top of whichever
    content-stack page is showing (see _build_hero/_hero_geometry) — it isn't
    tied to a particular page. The rows page (page 0) accounts for this via
    `rows_layout.setContentsMargins(32, self._HERO_H, 32, 24)`; the grid page
    (page 1) must reserve the same top clearance or its title/first row sit
    underneath the hero band."""
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    grid_page = screen._content_stack.widget(1)
    margins = grid_page.layout().contentsMargins()
    assert margins.top() == screen._HERO_H


def test_grid_right_moves_focus(qtbot):
    screen = _make_screen_with_items(qtbot)
    # Give SERIES row 3 items
    screen.set_row_items(RowType.SERIES, [_series(f"s{i}", f"S{i}") for i in range(3)])
    screen._enter_grid(2)
    screen.setFocus()
    assert screen._grid_focus_idx == 0
    _press(qtbot, screen, Qt.Key.Key_Right)
    assert screen._grid_focus_idx == 1


def test_grid_right_clamps_at_end(qtbot):
    screen = _make_screen_in_grid(qtbot, 2)  # 1 series item
    screen.setFocus()
    _press(qtbot, screen, Qt.Key.Key_Right)
    assert screen._grid_focus_idx == 0  # unchanged


def test_grid_left_moves_focus(qtbot):
    screen = _make_screen_with_items(qtbot)
    screen.set_row_items(RowType.SERIES, [_series(f"s{i}", f"S{i}") for i in range(3)])
    screen._enter_grid(2)
    screen._set_grid_focus(2)
    screen.setFocus()
    _press(qtbot, screen, Qt.Key.Key_Left)
    assert screen._grid_focus_idx == 1


def test_grid_left_at_first_exits_grid(qtbot):
    screen = _make_screen_in_grid(qtbot, 2)
    screen.setFocus()
    _press(qtbot, screen, Qt.Key.Key_Left)
    assert screen._zone == "rows"
    assert screen._content_stack.currentIndex() == 0


def test_grid_back_exits_grid(qtbot):
    screen = _make_screen_in_grid(qtbot, 2)
    screen.setFocus()
    _press(qtbot, screen, Qt.Key.Key_Backspace)
    assert screen._zone == "rows"


def test_grid_select_emits_signal(qtbot):
    screen = _make_screen_in_grid(qtbot, 2)  # SERIES row
    screen.setFocus()
    # _enter_grid populates _grid_items from _row_items
    assert len(screen._grid_items) > 0
    with qtbot.waitSignal(screen.series_selected, timeout=500) as blocker:
        screen._activate_grid_item(0)
    assert blocker.args[0].id == "s1"


def test_grid_down_moves_focus_by_column(qtbot):
    from sixpack.ui.screens.browse import _GRID_COLS
    # Create enough items to have two rows in the grid
    items = [_series(f"s{i}", f"S{i}") for i in range(_GRID_COLS + 1)]
    screen = BrowseScreen(row_types=[RowType.SERIES])
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "A")], "http://s", "tok")
    screen.set_row_items(RowType.SERIES, items)
    screen._enter_grid(0)
    screen.setFocus()
    assert screen._grid_focus_idx == 0
    _press(qtbot, screen, Qt.Key.Key_Down)
    assert screen._grid_focus_idx == _GRID_COLS


def test_grid_down_clamps_at_last_row(qtbot):
    screen = _make_screen_in_grid(qtbot, 2)  # 1 item only
    screen.setFocus()
    _press(qtbot, screen, Qt.Key.Key_Down)
    assert screen._grid_focus_idx == 0  # unchanged


def test_grid_up_clamps_at_first_row(qtbot):
    screen = _make_screen_in_grid(qtbot, 2)
    screen.setFocus()
    _press(qtbot, screen, Qt.Key.Key_Up)
    assert screen._grid_focus_idx == 0  # unchanged


def test_exit_grid_syncs_row_position(qtbot):
    screen = _make_screen_with_items(qtbot)
    screen.set_row_items(RowType.SERIES, [_series(f"s{i}", f"S{i}") for i in range(3)])
    screen._enter_grid(2)
    screen._set_grid_focus(2)
    screen._exit_grid()
    assert screen._row_item_idxs[2] == 2
    assert screen._zone == "rows"


# ---------------------------------------------------------------------------
# BrowseScreen — enter_grid with empty row does not switch zone
# ---------------------------------------------------------------------------

def test_enter_grid_empty_row_stays_in_rows(qtbot):
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "A")], "http://s", "tok")
    screen._zone = "rows"
    screen._enter_grid(0)  # CONTINUE_LISTENING is empty
    assert screen._zone == "rows"  # no transition, row is empty


# ---------------------------------------------------------------------------
# BrowseScreen — populate_row with Series/Playlist items
# ---------------------------------------------------------------------------

def test_populate_row_with_series(qtbot):
    screen = BrowseScreen(row_types=[RowType.SERIES])
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "A")], "http://s", "tok")
    series_list = [_series("s1", "Series A", 3), _series("s2", "Series B", 1)]
    screen.set_row_items(RowType.SERIES, series_list)
    assert screen._row_widgets[0].card_count == 2


def test_populate_row_with_playlists(qtbot):
    screen = BrowseScreen(row_types=[RowType.PLAYLISTS])
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "A")], "http://s", "tok")
    playlists = [_playlist("p1", "P1"), _playlist("p2", "P2", 3)]
    screen.set_row_items(RowType.PLAYLISTS, playlists)
    assert screen._row_widgets[0].card_count == 2


# ---------------------------------------------------------------------------
# BrowseScreen — media_type wiring (_make_card)
# ---------------------------------------------------------------------------

def test_populate_row_wires_media_type_from_library_item(qtbot):
    screen = BrowseScreen(row_types=[RowType.RECENTLY_ADDED])
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "A")], "http://s", "tok")
    podcast_item = LibraryItem(
        id="i1",
        libraryId="lib1",
        mediaType="podcast",
        media=LibraryItemMedia(metadata={"title": "Cast", "authorName": "Someone"}),
    )
    screen.set_row_items(RowType.RECENTLY_ADDED, [podcast_item])
    card = screen._row_widgets[0]._cards[0]
    assert card._media_type == "podcast"


def test_populate_row_series_and_playlists_default_media_type_book(qtbot):
    # Series/Playlist have no natural single media_type of their own —
    # _make_card's getattr(..., "book") fallback should apply.
    screen = BrowseScreen(row_types=[RowType.SERIES, RowType.PLAYLISTS])
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "A")], "http://s", "tok")
    screen.set_row_items(RowType.SERIES, [_series("s1", "S1")])
    screen.set_row_items(RowType.PLAYLISTS, [_playlist("p1", "P1")])
    assert screen._row_widgets[0]._cards[0]._media_type == "book"
    assert screen._row_widgets[1]._cards[0]._media_type == "book"


def test_enter_grid_wires_media_type(qtbot):
    screen = BrowseScreen(row_types=[RowType.RECENTLY_ADDED])
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "A")], "http://s", "tok")
    podcast_item = LibraryItem(
        id="i1",
        libraryId="lib1",
        mediaType="podcast",
        media=LibraryItemMedia(metadata={"title": "Cast", "authorName": "Someone"}),
    )
    screen.set_row_items(RowType.RECENTLY_ADDED, [podcast_item])
    screen._enter_grid(0)
    assert screen._grid_cards[0]._media_type == "podcast"


# ---------------------------------------------------------------------------
# BrowseScreen — unmapped key is passed to super
# ---------------------------------------------------------------------------

def test_unmapped_key_does_not_crash(qtbot):
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    screen.show()
    _press(qtbot, screen, Qt.Key.Key_A)  # not in _NAV_MAP


# ---------------------------------------------------------------------------
# Additional model property tests
# ---------------------------------------------------------------------------

def test_series_title_property():
    s = _series("s1", "My Series")
    assert s.title == "My Series"


def test_series_subtitle_singular():
    books = [SeriesBook(id="b1", media=LibraryItemMedia(metadata={"title": "B1"}))]
    s = Series(id="s1", name="Solo", books=books)
    assert s.subtitle == "1 book"


def test_series_subtitle_plural():
    s = _series("s1", "Multi", n_books=3)
    assert s.subtitle == "3 books"


def test_playlist_title_property():
    p = _playlist("p1", "My Playlist", 2)
    assert p.title == "My Playlist"


def test_playlist_subtitle_singular():
    p = _playlist("p1", "P", 1)
    assert p.subtitle == "1 item"


def test_playlist_subtitle_plural():
    p = _playlist("p1", "P", 5)
    assert p.subtitle == "5 items"


def test_library_item_subtitle():
    li = _li("i1", "My Book", "Jane Austen")
    assert li.subtitle == "Jane Austen"


# ---------------------------------------------------------------------------
# BrowseScreen — reflective hero
# ---------------------------------------------------------------------------

def test_hero_reflects_library_item(qtbot):
    screen = BrowseScreen(row_types=list(DEFAULT_ROW_TYPES))
    qtbot.addWidget(screen)
    item = _li("i1", "The Sandman", author="Neil Gaiman")
    screen._reflect_focus(item)
    assert screen._hero_title.text() == "The Sandman"
    assert "Neil Gaiman" in screen._hero_sub.text()


def test_hero_reflects_series(qtbot):
    screen = BrowseScreen(row_types=list(DEFAULT_ROW_TYPES))
    qtbot.addWidget(screen)
    s = _series("s1", "Discworld", n_books=3)
    screen._reflect_focus(s)
    assert screen._hero_title.text() == "Discworld"
    assert "3 books" in screen._hero_sub.text()


def test_hero_clears_on_none(qtbot):
    screen = BrowseScreen(row_types=list(DEFAULT_ROW_TYPES))
    qtbot.addWidget(screen)
    screen._reflect_focus(None)
    assert screen._hero_title.text() == ""
    assert screen._hero_sub.text() == ""


def test_row_focus_updates_hero(qtbot):
    screen = BrowseScreen(row_types=list(DEFAULT_ROW_TYPES))
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("lib1", "Audiobooks")], "http://abs.test", "t")
    # Mark the library as already-loaded so the _enter_rows() call below
    # doesn't itself call _reset_rows() (which would wipe the row items set
    # just below it right back out — see _enter_rows()'s "lib is not
    # self._loaded_library" check).
    screen._loaded_library = screen._libraries[0]
    screen.set_row_items(RowType.RECENTLY_ADDED, [_li("i1", "Book One"), _li("i2", "Book Two")])
    screen.show_content()
    screen._enter_rows()
    # focused row defaults to 0 (Continue Listening, empty) — move down to
    # Recently Added, whose item index resets to 0 on set_row_items(), so
    # the focused card is deterministically "Book One".
    screen._handle_rows(InputAction.DOWN)
    assert screen._focused_row == screen._row_types.index(RowType.RECENTLY_ADDED)
    assert screen._hero_title.text() == "Book One"


def test_stale_fetch_backdrop_callback_does_not_override_newer_focus(qtbot):
    """Regression guard for the stale-backdrop race: focusing item A
    (uncached — its cover_cache.fetch_backdrop() callback doesn't resolve
    immediately) then item B (whose callback resolves right away) must
    leave B's backdrop displayed even if A's callback finally fires late.
    """
    from PyQt6.QtGui import QColor, QPixmap

    class _FakeCoverCache:
        """Captures fetch_backdrop callbacks instead of invoking them,
        so the test can control exactly when (and in what order) each
        one resolves — simulating a cold cache where an earlier item's
        network fetch is still in flight when focus moves on."""

        def __init__(self):
            self.calls = []

        def fetch_backdrop(self, url, token, callback):
            self.calls.append(callback)

        def fetch(self, url, token, callback):
            pass

    fake_cache = _FakeCoverCache()
    screen = BrowseScreen(cover_cache=fake_cache)
    qtbot.addWidget(screen)
    screen._server_url = "http://s"
    screen._token = "t"

    item_a = _li("a1", "Item A")
    item_b = _li("b1", "Item B")

    # Focus A — its fetch_backdrop callback is captured but not yet fired
    # (simulating an in-flight network request).
    screen._reflect_focus(item_a)
    assert len(fake_cache.calls) == 1
    stale_callback_for_a = fake_cache.calls[0]

    # Focus moves on to B before A's fetch resolves.
    screen._reflect_focus(item_b)
    assert len(fake_cache.calls) == 2
    callback_for_b = fake_cache.calls[1]

    pix_b = QPixmap(10, 10)
    pix_b.fill(QColor(0, 200, 0))
    callback_for_b(pix_b)
    assert screen._backdrop._incoming_pixmap is pix_b

    # A's callback finally arrives late — must be dropped, not painted.
    pix_a = QPixmap(10, 10)
    pix_a.fill(QColor(200, 0, 0))
    stale_callback_for_a(pix_a)

    assert screen._backdrop._incoming_pixmap is pix_b


def test_stale_cover_fetch_callback_does_not_crash_on_deleted_card(qtbot):
    """Regression guard for a real crash: a row rebuild (e.g. "see all",
    or any _reset_rows()) calls MediaCard.deleteLater() on the old cards,
    but CoverCache._pending still holds their cover-fetch callbacks. If
    the fetch resolves after the card's C++ object is actually deleted,
    calling card.set_cover() raises RuntimeError inside a Qt slot, which
    is fatal — nothing else catches it. Reproduces the exact sequence:
    populate a row (captures a cover-fetch callback for its card), clear
    the row (deleteLater()s the card, matching _reset_rows()), let Qt
    actually delete it, then fire the stale callback.
    """
    from PyQt6.QtGui import QColor, QPixmap

    class _FakeCoverCache:
        def __init__(self):
            self.calls = []

        def fetch(self, url, token, callback):
            self.calls.append(callback)

        def fetch_backdrop(self, url, token, callback):
            pass

    fake_cache = _FakeCoverCache()
    screen = BrowseScreen(cover_cache=fake_cache, row_types=list(DEFAULT_ROW_TYPES))
    qtbot.addWidget(screen)
    screen._server_url = "http://s"
    screen._token = "t"

    row_idx = 0
    screen.set_row_items(screen._row_types[row_idx], [_li("a1", "Item A")])
    assert len(fake_cache.calls) == 1
    stale_callback = fake_cache.calls[0]

    # Matches _reset_rows(): clear() calls deleteLater() on the card.
    screen._row_widgets[row_idx].clear()
    # deleteLater() posts a DeferredDelete event that plain processEvents()
    # does NOT drain (Qt defers it specially to avoid deleting objects
    # mid-signal-emission) — it must be flushed explicitly to actually
    # delete the C++ object before the stale callback fires below.
    from PyQt6.QtCore import QCoreApplication, QEvent
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    pix = QPixmap(10, 10)
    pix.fill(QColor(200, 0, 0))
    stale_callback(pix)  # must not raise


def test_sidebar_item_has_icon_and_active_state(qtbot):
    from sixpack.ui import theme
    from sixpack.ui.screens.browse import _SidebarItem

    item = _SidebarItem("Podcasts", media_type="podcast")
    qtbot.addWidget(item)
    assert item._icon.text() != ""  # an icon glyph is shown

    # Exercise all three states set_state() distinguishes and assert each
    # one actually produces a visually distinct style — not just "doesn't
    # crash". selected+active is the filled accent pill; selected-but-
    # inactive shows the accent as a hint without the fill; unselected has
    # neither.
    item.set_state(selected=True, zone_active=True)
    active_style = item.styleSheet()
    active_label_style = item._label.styleSheet()

    item.set_state(selected=True, zone_active=False)
    selected_inactive_style = item.styleSheet()
    selected_inactive_label_style = item._label.styleSheet()

    item.set_state(selected=False, zone_active=False)
    unselected_style = item.styleSheet()
    unselected_label_style = item._label.styleSheet()

    assert len({active_style, selected_inactive_style, unselected_style}) == 3
    assert len(
        {active_label_style, selected_inactive_label_style, unselected_label_style}
    ) == 3

    assert theme.ACCENT in active_style  # filled accent background
    assert theme.SURFACE_HIGH in selected_inactive_style  # muted bg, accent hint only
    assert theme.ACCENT in selected_inactive_style
    assert "transparent" in unselected_style
    assert theme.ACCENT not in unselected_style


# ---------------------------------------------------------------------------
# _emit_item podcast dispatch
# ---------------------------------------------------------------------------

def test_emit_item_podcast_show_without_recent_episode_emits_podcast_selected(qtbot):
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    show = _podcast_show()
    received = []
    screen.podcast_selected.connect(received.append)
    screen._emit_item(RowType.RECENTLY_ADDED, show)
    assert received == [show]


def test_emit_item_podcast_show_with_recent_episode_emits_podcast_episode_selected(qtbot):
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    show = _podcast_show_with_recent_episode()
    received = []
    screen.podcast_episode_selected.connect(lambda s, e: received.append((s, e)))
    screen._emit_item(RowType.CONTINUE_LISTENING, show)
    assert len(received) == 1
    assert received[0][0] is show
    assert received[0][1] is show.recent_episode


def test_emit_item_plain_book_still_emits_book_selected(qtbot):
    """Regression guard: podcast dispatch must not affect books."""
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    item = _li("i1", "A Book")
    received = []
    screen.book_selected.connect(received.append)
    screen._emit_item(RowType.RECENTLY_ADDED, item)
    assert received == [item]
