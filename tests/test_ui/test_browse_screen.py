"""Tests for the Kodi-style BrowseScreen."""
from __future__ import annotations

from PyQt6.QtCore import Qt

from sixpack.api.models import (
    Library,
    LibraryItem,
    LibraryItemMedia,
    MediaProgress,
    Playlist,
    PlaylistItem,
    PodcastEpisode,
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


def _li_dur(item_id, title, duration):
    return LibraryItem(
        id=item_id, libraryId="lib1", mediaType="book",
        media=LibraryItemMedia(metadata={"title": title}, duration=duration),
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
    assert RowType.ALL_BOOKS.value == "All Books"
    assert RowType.PLAYLISTS.value == "Playlists"


def test_default_row_types_order():
    assert DEFAULT_ROW_TYPES == [
        RowType.CONTINUE_LISTENING,
        RowType.RECENTLY_ADDED,
        RowType.SERIES,
        RowType.ALL_BOOKS,
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


def test_sidebar_item_click_emits_activated(qtbot):
    item = _SidebarItem("Audiobooks")
    qtbot.addWidget(item)
    item.show()

    activated = []
    item.activated.connect(lambda: activated.append(True))

    qtbot.mouseClick(item, Qt.MouseButton.LeftButton)

    assert activated == [True]


def test_sidebar_item_double_click_emits_activated_once(qtbot):
    """Regression: unlike MediaCard (which tracks a `_pressed` flag in
    mousePressEvent and only emits from mouseReleaseEvent if it was set),
    _SidebarItem has no mousePressEvent at all -- only mouseReleaseEvent,
    unconditionally emitting on every left-button release inside its
    bounds. A real double-click's second press arrives as a
    MouseButtonDblClick event, a type mousePressEvent never receives (the
    widget doesn't override mouseDoubleClickEvent) -- so a real double-
    click is one mousePressEvent followed by TWO mouseReleaseEvents, with
    no second mousePressEvent in between. Simulated that way here (rather
    than via qtbot.mouseDClick, which sends only a bare
    MouseButtonDblClick with no surrounding press/release in this Qt
    version and so doesn't exercise mouseReleaseEvent at all) -- verified
    against MediaCard's own already-correct behavior first, which emits
    exactly once under this exact sequence."""
    item = _SidebarItem("Audiobooks")
    qtbot.addWidget(item)
    item.show()

    activated = []
    item.activated.connect(lambda: activated.append(True))

    qtbot.mousePress(item, Qt.MouseButton.LeftButton)
    qtbot.mouseRelease(item, Qt.MouseButton.LeftButton)  # first click's release
    qtbot.mouseRelease(item, Qt.MouseButton.LeftButton)  # second click's release

    assert activated == [True]


def test_sidebar_item_enter_emits_hovered(qtbot):
    from PyQt6.QtCore import QPointF
    from PyQt6.QtGui import QEnterEvent

    item = _SidebarItem("Audiobooks")
    qtbot.addWidget(item)

    hovered = []
    item.hovered.connect(lambda: hovered.append(True))

    item.enterEvent(QEnterEvent(QPointF(0, 0), QPointF(0, 0), QPointF(0, 0)))

    assert hovered == [True]


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


def test_row_widget_card_hover_reemits_with_index(qtbot):
    from sixpack.ui.widgets.media_card import MediaCard
    row = _RowWidget("Continue Listening")
    qtbot.addWidget(row)
    row.add_card(MediaCard(title="A"))
    row.add_card(MediaCard(title="B"))

    hovered = []
    row.card_hovered.connect(lambda idx: hovered.append(idx))

    row._cards[1].hovered.emit()

    assert hovered == [1]


def test_row_widget_card_activated_reemits_with_index(qtbot):
    from sixpack.ui.widgets.media_card import MediaCard
    row = _RowWidget("Continue Listening")
    qtbot.addWidget(row)
    row.add_card(MediaCard(title="A"))

    activated = []
    row.card_activated.connect(lambda idx: activated.append(idx))

    row._cards[0].activated.emit()

    assert activated == [0]


def test_row_widget_card_long_pressed_reemits_with_index(qtbot):
    from sixpack.ui.widgets.media_card import MediaCard
    row = _RowWidget("Continue Listening")
    qtbot.addWidget(row)
    row.add_card(MediaCard(title="A"))

    long_pressed = []
    row.card_long_pressed.connect(lambda idx: long_pressed.append(idx))

    row._cards[0].long_pressed.emit()

    assert long_pressed == [0]


def test_row_widget_see_all_hover_and_click(qtbot):
    from PyQt6.QtCore import QEvent, QPointF
    from PyQt6.QtGui import QMouseEvent

    row = _RowWidget("Continue Listening")
    qtbot.addWidget(row)
    row.show()

    hovered = []
    activated = []
    row.see_all_hovered.connect(lambda: hovered.append(True))
    row.see_all_activated.connect(lambda: activated.append(True))

    row.eventFilter(row._see_all, QEvent(QEvent.Type.Enter))
    assert hovered == [True]

    release = QMouseEvent(
        QEvent.Type.MouseButtonRelease, QPointF(1, 1), Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    row.eventFilter(row._see_all, release)
    assert activated == [True]


def test_row_widget_see_all_right_click_does_not_activate(qtbot):
    """Regression: every other clickable widget in this app (MediaCard,
    ChapterItem, _SidebarItem) guards its release handling with
    `event.button() == Qt.MouseButton.LeftButton` before activating --
    "See all"'s eventFilter was the only one missing that check, so a
    right-click (or middle-click) would activate it too."""
    from PyQt6.QtCore import QEvent, QPointF
    from PyQt6.QtGui import QMouseEvent

    row = _RowWidget("Continue Listening")
    qtbot.addWidget(row)
    row.show()

    activated = []
    row.see_all_activated.connect(lambda: activated.append(True))

    release = QMouseEvent(
        QEvent.Type.MouseButtonRelease, QPointF(1, 1), Qt.MouseButton.RightButton,
        Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier,
    )
    row.eventFilter(row._see_all, release)

    assert activated == []


def test_row_widget_see_all_release_outside_rect_does_not_activate(qtbot):
    """Regression: a release outside the "See all" chip's own bounds (e.g.
    a press-then-drag-off) must cancel silently instead of activating --
    every other clickable widget in this app already guards for this."""
    from PyQt6.QtCore import QEvent, QPointF
    from PyQt6.QtGui import QMouseEvent

    row = _RowWidget("Continue Listening")
    qtbot.addWidget(row)
    row.show()

    activated = []
    row.see_all_activated.connect(lambda: activated.append(True))

    release = QMouseEvent(
        QEvent.Type.MouseButtonRelease, QPointF(-50, -50), Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    row.eventFilter(row._see_all, release)

    assert activated == []


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
    assert len(screen._sidebar_items) == 3  # Exit + 2 libraries
    assert screen._sidebar_items[0]._label.text() == "Exit"
    assert screen._sidebar_items[1]._label.text() == "Audiobooks"
    assert screen._sidebar_items[2]._label.text() == "Big Finish"


def test_browse_screen_load_libraries_resets_state(qtbot):
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    libs = [_lib("l1", "Audiobooks")]
    screen.load_libraries(libs, "http://s", "tok")
    assert screen._sidebar_idx == 1  # defaults to the first library, not Exit (index 0)
    assert screen._loaded_library is None


def test_sidebar_layout_ends_with_trailing_stretch(qtbot):
    """Without a trailing addStretch(), items expand to fill the column,
    stretching each _SidebarItem's `border-left` accent bar across the
    whole remaining column height instead of staying item-sized."""
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "A"), _lib("l2", "B")], "http://s", "tok")
    layout = screen._sidebar_items_layout
    # Exit + divider + 2 library items + 1 trailing stretch
    assert layout.count() == 5
    last_item = layout.itemAt(layout.count() - 1)
    assert last_item.widget() is None  # a stretch/spacer, not a sidebar item


def test_sidebar_layout_stretch_not_duplicated_on_reload(qtbot):
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "A")], "http://s", "tok")
    screen.load_libraries([_lib("l1", "A"), _lib("l2", "B")], "http://s", "tok")
    layout = screen._sidebar_items_layout
    # Exit + divider + 2 library items + exactly one trailing stretch
    assert layout.count() == 5


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


def test_set_row_items_repopulate_preserves_navigated_focus(qtbot):
    """Regression: BrowseScreen shows a row instantly from the on-disk
    cache, then set_row_items() is called again moments later with the
    real network result for the same row (see app.py's
    _fetch_browse_content: cache-primed render superseded by the async
    fetch). If the user has already navigated within that row during the
    gap, the second call must not snap focus back to the first card."""
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "Audiobooks")], "http://s", "tok")
    ra_idx = screen._row_types.index(RowType.RECENTLY_ADDED)
    screen.set_row_items(RowType.RECENTLY_ADDED, [_li("i1", "A"), _li("i2", "B")])
    screen.show()
    screen._zone = "rows"
    screen._focused_row = ra_idx
    screen._row_item_idxs[ra_idx] = 1  # user navigated to the 2nd card

    # The real fetch resolves with the same (or refreshed) items.
    screen.set_row_items(RowType.RECENTLY_ADDED, [_li("i1", "A"), _li("i2", "B")])

    assert screen._row_item_idxs[ra_idx] == 1
    assert screen._row_widgets[ra_idx]._focused_idx == 1


def test_set_row_items_repopulate_clamps_shorter_list(qtbot):
    """If the refreshed row is shorter than before, the preserved index
    must clamp into range rather than pointing past the end."""
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "Audiobooks")], "http://s", "tok")
    ra_idx = screen._row_types.index(RowType.RECENTLY_ADDED)
    screen.set_row_items(
        RowType.RECENTLY_ADDED, [_li("i1", "A"), _li("i2", "B"), _li("i3", "C")]
    )
    screen.show()
    screen._zone = "rows"
    screen._focused_row = ra_idx
    screen._row_item_idxs[ra_idx] = 2

    screen.set_row_items(RowType.RECENTLY_ADDED, [_li("i1", "A")])

    assert screen._row_item_idxs[ra_idx] == 0


def test_set_row_items_first_population_still_defaults_to_zero(qtbot):
    """A row's genuine first population (no prior items) must still start
    at index 0 -- only a re-population of an already-populated row
    preserves the existing index."""
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "Audiobooks")], "http://s", "tok")
    ra_idx = screen._row_types.index(RowType.RECENTLY_ADDED)
    screen.set_row_items(RowType.RECENTLY_ADDED, [_li("i1", "A"), _li("i2", "B")])
    assert screen._row_item_idxs[ra_idx] == 0


# ---------------------------------------------------------------------------
# BrowseScreen — sidebar zone keyboard navigation
# ---------------------------------------------------------------------------

def test_sidebar_down_moves_selection(qtbot):
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "A"), _lib("l2", "B")], "http://s", "tok")
    screen.show()
    assert screen._sidebar_idx == 1  # defaults to the first library
    _press(qtbot, screen, Qt.Key.Key_Down)
    assert screen._sidebar_idx == 2


def test_sidebar_up_from_first_library_reaches_exit(qtbot):
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "A"), _lib("l2", "B")], "http://s", "tok")
    screen.show()
    _press(qtbot, screen, Qt.Key.Key_Up)
    assert screen._sidebar_idx == 0  # Exit


def test_sidebar_up_does_not_go_negative(qtbot):
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "A"), _lib("l2", "B")], "http://s", "tok")
    screen.show()
    _press(qtbot, screen, Qt.Key.Key_Up)  # already at Exit (0) after one Up
    _press(qtbot, screen, Qt.Key.Key_Up)
    assert screen._sidebar_idx == 0


def test_sidebar_down_clamps_at_end(qtbot):
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "A")], "http://s", "tok")
    screen.show()
    _press(qtbot, screen, Qt.Key.Key_Down)
    assert screen._sidebar_idx == 1  # still 1 (Exit + only 1 library)


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
    """With zero libraries loaded, _sidebar_idx defaults to 0 (Exit, which
    is always present) — Right/Select reaches Exit's confirmation rather
    than doing nothing, so the app can still be quit even if the library
    list never populates. _zone itself never changes for this (see the
    Exit-confirm tests below for why)."""
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    screen.show()
    _press(qtbot, screen, Qt.Key.Key_Right)
    assert screen._zone == "sidebar"
    assert screen._exit_overlay.isVisible()


def test_sidebar_item_hover_moves_sidebar_index(qtbot):
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "A"), _lib("l2", "B")], "http://s", "tok")
    screen.show()
    screen._zone = "rows"  # start somewhere other than sidebar

    screen._sidebar_items[2].hovered.emit()

    assert screen._zone == "sidebar"
    assert screen._sidebar_idx == 2


def test_sidebar_item_click_on_library_enters_rows(qtbot):
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "A")], "http://s", "tok")
    screen.show()

    screen._sidebar_items[1].activated.emit()

    assert screen._zone == "rows"


def test_sidebar_item_click_on_exit_shows_exit_confirm(qtbot):
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "A")], "http://s", "tok")
    screen.show()

    screen._sidebar_items[0].activated.emit()

    assert screen._exit_overlay.isVisible()


def test_sidebar_item_hover_clears_stale_see_all_focus(qtbot):
    """Regression: mousing over a sidebar item while "See all" is focused
    (e.g. after pressing RIGHT at the end of a row) must clear
    _see_all_focused, exactly like the keyboard's _enter_sidebar() does —
    otherwise the "See all" chip stays highlighted and _handle_rows's own
    `if self._see_all_focused:` guard can later swallow a RIGHT keypress."""
    screen = _make_screen_with_items(qtbot)
    screen._row_item_idxs[0] = 1  # already at last item (2 items)
    screen.setFocus()
    _press(qtbot, screen, Qt.Key.Key_Right)  # focus see-all
    assert screen._see_all_focused is True

    screen._sidebar_items[1].hovered.emit()

    assert screen._see_all_focused is False


def test_sidebar_item_hover_exits_grid_zone(qtbot):
    """Regression: mousing over a sidebar item while _zone == "grid" must
    exit the grid (like keyboard's LEFT/BACKSPACE path through
    _exit_grid()) rather than just flipping _zone to "sidebar" directly,
    which would leave _content_stack still showing the grid page."""
    screen = _make_screen_with_items(qtbot)
    # _make_screen_with_items() populates rows directly without going
    # through _start_loading_selected_library(), so mark the library as
    # already loaded -- otherwise the post-_exit_grid() hover would also
    # kick off a fresh library load (a real, separate, already-covered
    # code path) whose _reset_rows() legitimately re-shows the loading
    # page, which isn't what this test is isolating.
    screen._loaded_library = screen._libraries[0]
    screen._focused_row = 2  # SERIES row, has items
    screen._enter_grid(2)
    assert screen._zone == "grid"

    screen._sidebar_items[1].hovered.emit()

    assert screen._zone == "sidebar"
    assert screen._content_stack.currentIndex() == 0


# ---------------------------------------------------------------------------
# BrowseScreen — Exit sidebar item + confirmation
# ---------------------------------------------------------------------------

def test_exit_is_first_sidebar_item_before_any_libraries_loaded(qtbot):
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    assert len(screen._sidebar_items) == 1
    assert screen._sidebar_items[0]._label.text() == "Exit"
    assert screen._sidebar_idx == 0


def test_selecting_exit_shows_confirmation_overlay(qtbot):
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "A")], "http://s", "tok")
    screen.show()
    _press(qtbot, screen, Qt.Key.Key_Up)  # from the default first library to Exit
    assert screen._sidebar_idx == 0

    _press(qtbot, screen, Qt.Key.Key_Right)

    assert screen._exit_overlay.isVisible()
    assert screen._zone == "sidebar"  # unchanged — the overlay just floats on top


def test_select_on_exit_does_not_trigger_a_library_load(qtbot):
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "A")], "http://s", "tok")
    screen.show()
    signals = []
    screen.library_changed.connect(lambda lib: signals.append(lib))

    _press(qtbot, screen, Qt.Key.Key_Up)  # Exit
    _press(qtbot, screen, Qt.Key.Key_Right)  # opens confirmation

    assert signals == []


def test_exit_confirm_defaults_focus_to_no(qtbot):
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "A")], "http://s", "tok")
    screen.show()
    _press(qtbot, screen, Qt.Key.Key_Up)
    _press(qtbot, screen, Qt.Key.Key_Right)
    assert screen._exit_confirm_idx == 1  # No


def test_exit_confirm_left_right_toggles_yes_no(qtbot):
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "A")], "http://s", "tok")
    screen.show()
    _press(qtbot, screen, Qt.Key.Key_Up)
    _press(qtbot, screen, Qt.Key.Key_Right)

    _press(qtbot, screen, Qt.Key.Key_Left)
    assert screen._exit_confirm_idx == 0  # Yes

    _press(qtbot, screen, Qt.Key.Key_Left)
    assert screen._exit_confirm_idx == 0  # doesn't go past Yes

    _press(qtbot, screen, Qt.Key.Key_Right)
    assert screen._exit_confirm_idx == 1  # No

    _press(qtbot, screen, Qt.Key.Key_Right)
    assert screen._exit_confirm_idx == 1  # doesn't go past No


def test_exit_confirm_select_no_dismisses_without_exit_requested(qtbot):
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "A")], "http://s", "tok")
    screen.show()
    signals = []
    screen.exit_requested.connect(lambda: signals.append(True))

    _press(qtbot, screen, Qt.Key.Key_Up)
    _press(qtbot, screen, Qt.Key.Key_Right)  # opens, defaults to No
    _press(qtbot, screen, Qt.Key.Key_Return)  # selects No

    assert not screen._exit_overlay.isVisible()
    assert signals == []


def test_exit_confirm_select_yes_emits_exit_requested(qtbot):
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "A")], "http://s", "tok")
    screen.show()
    signals = []
    screen.exit_requested.connect(lambda: signals.append(True))

    _press(qtbot, screen, Qt.Key.Key_Up)
    _press(qtbot, screen, Qt.Key.Key_Right)  # opens, defaults to No
    _press(qtbot, screen, Qt.Key.Key_Left)  # move to Yes
    _press(qtbot, screen, Qt.Key.Key_Return)

    assert not screen._exit_overlay.isVisible()
    assert signals == [True]


def test_exit_confirm_back_cancels(qtbot):
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "A")], "http://s", "tok")
    screen.show()
    signals = []
    screen.exit_requested.connect(lambda: signals.append(True))

    _press(qtbot, screen, Qt.Key.Key_Up)
    _press(qtbot, screen, Qt.Key.Key_Right)
    _press(qtbot, screen, Qt.Key.Key_Left)  # move to Yes, to prove Back overrides it
    _press(qtbot, screen, Qt.Key.Key_Backspace)  # Back

    assert not screen._exit_overlay.isVisible()
    assert signals == []


def test_exit_confirm_reopens_defaulting_to_no_each_time(qtbot):
    """A cancelled confirmation must not leave the next one pre-focused on
    Yes — each opening defaults fresh to No."""
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "A")], "http://s", "tok")
    screen.show()

    _press(qtbot, screen, Qt.Key.Key_Up)
    _press(qtbot, screen, Qt.Key.Key_Right)
    _press(qtbot, screen, Qt.Key.Key_Left)  # move to Yes
    _press(qtbot, screen, Qt.Key.Key_Backspace)  # cancel

    _press(qtbot, screen, Qt.Key.Key_Right)  # reopen
    assert screen._exit_confirm_idx == 1  # No, not still on Yes


def test_reflect_library_blank_when_exit_focused(qtbot):
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "Audiobooks")], "http://s", "tok")
    screen.show()
    _press(qtbot, screen, Qt.Key.Key_Up)  # Exit
    assert screen._hero_title.text() == ""
    assert screen._hero_sub.text() == ""


def test_exit_confirm_geometry_never_shorter_than_its_own_content(qtbot):
    """Regression: the overlay's assigned height must come from its own
    sizeHint(), not a hardcoded pixel constant. A hardcoded value chosen
    against one machine's font rendering can end up shorter than what the
    same point-sized font actually needs elsewhere, squeezing the button
    row short enough to clip its own text vertically -- exactly what
    happened on a deployed (4K) instance even though it wasn't visible in
    this dev environment's own font rendering."""
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    screen.resize(1920, 1080)
    geometry = screen._exit_confirm_geometry()
    assert geometry.height() >= screen._exit_overlay.sizeHint().height()


# ---------------------------------------------------------------------------
# BrowseScreen — Exit confirmation's modal mouse-input shield ("scrim")
#
# _exit_overlay is a small centered widget, not full-screen. Keyboard input
# is already gated (keyPressEvent checks `_exit_overlay.isVisible()` before
# any zone dispatch), but mouse input isn't gated by focus/state at all --
# Qt delivers mouse/enter/leave events to whichever widget is topmost under
# the cursor, regardless of what's "logically" open. Without a full-screen
# shield underneath the overlay, a real click on a row card elsewhere on
# screen would still reach it and fire book_selected, switching the whole
# app to the player screen while leaving the (now hidden-behind-it) exit
# confirmation still open underneath.
# ---------------------------------------------------------------------------


def test_exit_scrim_shows_and_covers_full_screen(qtbot):
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    screen.resize(1000, 700)
    screen.load_libraries([_lib("l1", "A")], "http://s", "tok")
    screen.show()

    screen._show_exit_confirm()

    assert screen._exit_scrim.isVisible()
    assert screen._exit_scrim.geometry() == screen.rect()


def test_exit_scrim_hidden_before_confirm_opens(qtbot):
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    assert not screen._exit_scrim.isVisible()


def test_exit_scrim_hidden_after_back_cancels(qtbot):
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "A")], "http://s", "tok")
    screen.show()
    _press(qtbot, screen, Qt.Key.Key_Up)
    _press(qtbot, screen, Qt.Key.Key_Right)  # opens
    assert screen._exit_scrim.isVisible()

    _press(qtbot, screen, Qt.Key.Key_Backspace)  # Back cancels

    assert not screen._exit_scrim.isVisible()


def test_exit_scrim_hidden_after_selecting_no(qtbot):
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "A")], "http://s", "tok")
    screen.show()
    _press(qtbot, screen, Qt.Key.Key_Up)
    _press(qtbot, screen, Qt.Key.Key_Right)  # opens, defaults to No
    assert screen._exit_scrim.isVisible()

    _press(qtbot, screen, Qt.Key.Key_Return)  # selects No

    assert not screen._exit_scrim.isVisible()


def test_exit_scrim_shields_row_card_from_real_click(qtbot):
    """End-to-end regression, mirroring the real bug: with the exit
    confirmation open, a real click over a row card elsewhere on screen
    must land on the shield, not on the card -- proving the card can never
    receive that click (and so can never fire card_activated/book_selected)
    while the confirmation is open, regardless of what a raw signal.emit()
    on the card would otherwise trigger."""
    screen = _make_screen_with_items(qtbot)
    screen.resize(1200, 800)
    screen.show_content()
    screen.show()
    qtbot.waitExposed(screen)
    qtbot.wait(20)  # let the row/scroll layout settle before hit-testing it

    card = screen._row_widgets[0]._cards[0]
    pos = card.mapTo(screen, card.rect().center())
    assert screen.childAt(pos) is card or card.isAncestorOf(screen.childAt(pos))

    screen._show_exit_confirm()

    assert screen.childAt(pos) is screen._exit_scrim


def test_exit_scrim_no_longer_shields_card_once_confirm_closes(qtbot):
    """Complementary to the above: closing the confirmation must restore
    normal clickability -- the shield isn't left stuck covering the
    screen."""
    screen = _make_screen_with_items(qtbot)
    screen.resize(1200, 800)
    screen.show_content()
    screen.show()
    qtbot.waitExposed(screen)
    qtbot.wait(20)

    card = screen._row_widgets[0]._cards[0]
    pos = card.mapTo(screen, card.rect().center())

    screen._show_exit_confirm()
    assert screen.childAt(pos) is screen._exit_scrim

    screen._activate_exit_confirm(1)  # No

    assert screen.childAt(pos) is card or card.isAncestorOf(screen.childAt(pos))


def test_sidebar_icons_use_the_bundled_icon_font_not_raw_emoji(qtbot):
    """Regression: sidebar icons used to be raw emoji (📚🎙📖🚪), which
    don't share a consistent visual style across platforms and, per an
    earlier real bug, aren't reliably covered by every system's emoji
    font at all (U+23FB fell back to a missing-glyph box on a deployed
    Linux instance). All sidebar icons -- including Exit -- now come
    from the same bundled Material Icons Outlined font already used for
    the player screen's transport controls, for a consistent look and a
    single, already-verified-working rendering path."""
    from sixpack.ui import theme

    screen = BrowseScreen()
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "Audiobooks")], "http://s", "tok")

    for item in (screen._exit_item, screen._sidebar_items[1]):
        assert theme.ICON_FONT_FAMILY in item._icon.styleSheet()
        assert item._icon.text() in (
            theme.ICON_LOGOUT, theme.ICON_MENU_BOOK,
            theme.ICON_PODCASTS, theme.ICON_AUTO_STORIES,
        )


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


def test_reset_rows_resets_scroll_position(qtbot):
    """Regression test: switching libraries in the sidebar must reset the
    rows page's scroll position, not just the focused-row index. A user
    scrolled deep into one library's rows (e.g. its last, densely-populated
    row) who then switches to a smaller library must not land on a
    scrolled-down view of the NEW library's rows that may be entirely
    empty — _reset_rows() already resets _focused_row to 0, but the
    scroll-to-0 side effect lives only in _update_row_styles(), which
    _reset_rows() never calls."""
    screen = BrowseScreen()
    screen.resize(1920, 700)  # short enough that scrolling is meaningful
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "A")], "http://s", "tok")
    screen.set_row_items(RowType.CONTINUE_LISTENING, [_li("i1", "CL1")])
    screen.set_row_items(RowType.RECENTLY_ADDED, [_li("i2", "RA1")])
    screen.set_row_items(RowType.SERIES, [_series("s1", "S1")])
    screen.set_row_items(RowType.PLAYLISTS, [_playlist("p1", "PL1")])
    screen.show_content()
    screen.setFocus()
    screen._enter_rows()

    for _ in range(3):
        _press(qtbot, screen, Qt.Key.Key_Down)  # scroll deep into the rows
    assert screen._rows_scroll.verticalScrollBar().value() > 0

    screen._reset_rows()  # simulates switching to a new library

    assert screen._rows_scroll.verticalScrollBar().value() == 0


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
    screen.set_row_items(RowType.ALL_BOOKS, [_li("i4", "AB1")])
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
        screen._activate_row_item(4, 0)  # PLAYLISTS row
    assert blocker.args[0].id == "p1"


def test_rows_select_out_of_bounds_does_nothing(qtbot):
    screen = _make_screen_with_items(qtbot)
    fired = []
    screen.book_selected.connect(lambda x: fired.append(x))
    screen._activate_row_item(0, 99)  # out of range
    assert not fired


def test_row_card_hover_syncs_zone_row_and_item(qtbot):
    screen = _make_screen_with_items(qtbot)
    screen._zone = "sidebar"  # start somewhere other than this row

    screen._row_widgets[1].card_hovered.emit(0)

    assert screen._zone == "rows"
    assert screen._focused_row == 1
    assert screen._row_item_idxs[1] == 0


def test_row_card_click_activates_item(qtbot):
    screen = _make_screen_with_items(qtbot)

    with qtbot.waitSignal(screen.book_selected, timeout=500) as blocker:
        screen._row_widgets[0].card_activated.emit(1)

    assert blocker.args[0].id == "i2"


def test_row_see_all_hover_focuses_see_all(qtbot):
    screen = _make_screen_with_items(qtbot)
    screen._zone = "sidebar"

    screen._row_widgets[0].see_all_hovered.emit()

    assert screen._zone == "rows"
    assert screen._focused_row == 0
    assert screen._see_all_focused is True


def test_row_see_all_click_triggers_see_all(qtbot):
    screen = _make_screen_with_items(qtbot)

    with qtbot.waitSignal(screen.see_all_requested, timeout=500) as blocker:
        screen._row_widgets[0].see_all_activated.emit()

    assert blocker.args[0] == RowType.CONTINUE_LISTENING
    assert screen._zone == "grid"


def test_see_all_hover_on_new_row_clears_previous_rows_stale_highlight(qtbot):
    """Regression: hovering row 0's "See all" then row 1's "See all" used
    to leave BOTH rows' chips accent-highlighted simultaneously --
    _on_see_all_hovered() reassigned _focused_row before calling
    _set_see_all_focused(True), so the OLD row's _RowWidget never got its
    own _see_all_is_focused flag reset (unlike _on_sidebar_item_hovered and
    _on_row_card_hovered, which both reset it up front). Unreachable via
    keyboard (which always clears the flag before moving rows), but
    directly reachable via mouse since the "See all" chips sit vertically
    stacked."""
    screen = _make_screen_with_items(qtbot)

    screen._row_widgets[0].see_all_hovered.emit()
    assert screen._row_widgets[0]._see_all_is_focused is True

    screen._row_widgets[1].see_all_hovered.emit()

    assert screen._row_widgets[0]._see_all_is_focused is False
    assert screen._row_widgets[1]._see_all_is_focused is True


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


def test_grid_card_hover_moves_grid_focus(qtbot):
    screen = _make_screen_in_grid(qtbot, row_idx=0)  # CONTINUE_LISTENING -> i1, i2

    screen._grid_cards[1].hovered.emit()

    assert screen._grid_focus_idx == 1


def test_grid_card_click_activates_item(qtbot):
    screen = _make_screen_in_grid(qtbot, row_idx=0)  # CONTINUE_LISTENING -> i1, i2

    with qtbot.waitSignal(screen.book_selected, timeout=500) as blocker:
        screen._grid_cards[1].activated.emit()

    assert blocker.args[0].id == "i2"


def test_grid_card_long_press_requests_finish_progress(qtbot):
    screen = _make_screen_in_grid(qtbot, row_idx=0)  # CONTINUE_LISTENING -> i1, i2
    requested = []
    screen.finish_progress_requested.connect(requested.append)

    screen._grid_cards[0].long_pressed.emit()

    assert len(requested) == 1
    assert requested[0].id == "i1"


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


def test_exit_grid_from_see_all_clamps_row_position_to_row_bounds(qtbot):
    """Regression test: "See all" populates the grid from a separately-
    fetched, uncapped dataset (e.g. up to 500 series), while the row itself
    only ever holds its own capped list (e.g. 5 items shown in the strip).
    Exiting the grid after focusing something beyond the row's own length
    must clamp the synced row index to the row's actual bounds — writing
    the raw grid index straight into _row_item_idxs leaves it permanently
    out of range: _RowWidget.focus_card() visually clamps to the last card
    every time, but the STORED index doesn't move into range until LEFT is
    pressed enough times to walk it back down — looking completely stuck.
    """
    screen = _make_screen_with_items(qtbot)
    small_row_items = [_series(f"s{i}", f"S{i}") for i in range(5)]
    screen.set_row_items(RowType.SERIES, small_row_items)
    screen._focused_row = 2  # SERIES row — _trigger_see_all() acts on this

    screen._trigger_see_all()
    large_see_all_items = [_series(f"s{i}", f"S{i}") for i in range(30)]
    screen.populate_grid(large_see_all_items)
    screen._set_grid_focus(25)  # beyond the row's own 5-item length

    screen._exit_grid()

    assert screen._row_item_idxs[2] == 4  # clamped to the row's last valid index
    # The visible card focus and the stored index must now agree — LEFT
    # should immediately move focus, not silently decrement a still-out-
    # of-range number.
    assert screen._row_widgets[2]._focused_idx == 4


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
    # crash". selected+active is an accent border + a soft translucent
    # tint (not a solid fill — a restrained selection style, closer to
    # Plex/YouTube TV's sidebar than a flat accent-block); selected-but-
    # inactive drops the tint and dims the border, using accent-tinted
    # text as the only hint that this is still the current library;
    # unselected has neither.
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

    assert theme.ACCENT_TINT in active_style  # translucent tint, not a solid fill
    assert theme.ACCENT in active_style  # accent border
    assert theme.TEXT_PRIMARY in active_label_style  # bright text when actively focused
    assert theme.ACCENT_DIM in selected_inactive_style  # dimmed border
    assert "transparent" in selected_inactive_style  # no tint when not the active zone
    assert theme.ACCENT in selected_inactive_label_style  # accent-tinted text hint
    assert "transparent" in unselected_style
    assert theme.ACCENT not in unselected_style
    assert theme.ACCENT not in unselected_label_style


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


# ---------------------------------------------------------------------------
# Mark finished — long-press on a Continue Listening / Recently Added card
#
# Regression coverage for: mark-as-finished only worked from
# SeriesDetailScreen (via DetailGridScreen's FocusGrid long-press), not for
# standalone books/podcasts encountered directly in BrowseScreen's own rows
# or "See all" grid, because BrowseScreen never implemented the long-press
# gesture at all.
# ---------------------------------------------------------------------------

def _make_screen_with_durationed_item(qtbot, item=None):
    item = item or _li_dur("i1", "CL1", 3600.0)
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "A")], "http://s", "tok")
    screen.set_row_items(RowType.CONTINUE_LISTENING, [item])
    screen.set_row_items(RowType.RECENTLY_ADDED, [])
    screen.set_row_items(RowType.SERIES, [])
    screen.set_row_items(RowType.PLAYLISTS, [])
    screen.show()
    screen._zone = "rows"
    screen._focused_row = 0
    screen._update_row_styles()
    return screen, item


def test_long_press_on_continue_listening_card_requests_finish_progress(qtbot):
    screen = _make_screen_with_items(qtbot)
    screen.setFocus()
    requested = []
    screen.finish_progress_requested.connect(requested.append)

    qtbot.keyPress(screen, Qt.Key.Key_Return)
    qtbot.wait(600)  # past the 500ms hold threshold
    qtbot.keyRelease(screen, Qt.Key.Key_Return)
    qtbot.wait(50)

    assert len(requested) == 1
    assert requested[0].id == "i1"


def test_short_tap_on_continue_listening_card_still_activates_it(qtbot):
    """Regression guard: adding the long-press gesture must not break the
    existing short-tap-to-play behavior."""
    screen = _make_screen_with_items(qtbot)
    screen.setFocus()
    selected = []
    requested = []
    screen.book_selected.connect(selected.append)
    screen.finish_progress_requested.connect(requested.append)

    qtbot.keyClick(screen, Qt.Key.Key_Return)  # press+release, near-instant
    qtbot.wait(50)

    assert len(selected) == 1
    assert selected[0].id == "i1"
    assert requested == []


def test_long_press_on_all_books_card_requests_finish_progress(qtbot):
    """All Books cards are plain library items just like Continue
    Listening/Recently Added -- mark-finished must work there too."""
    screen = _make_screen_with_items(qtbot)
    screen._handle_rows(InputAction.DOWN)
    screen._handle_rows(InputAction.DOWN)
    screen._handle_rows(InputAction.DOWN)  # row 3 = ALL_BOOKS
    screen.setFocus()
    requested = []
    screen.finish_progress_requested.connect(requested.append)

    qtbot.keyPress(screen, Qt.Key.Key_Return)
    qtbot.wait(600)
    qtbot.keyRelease(screen, Qt.Key.Key_Return)
    qtbot.wait(50)

    assert len(requested) == 1
    assert requested[0].id == "i4"


def test_long_press_on_series_row_does_not_request_finish_progress(qtbot):
    """Series/Playlists rows hold Series/Playlist objects, not individual
    items -- long-press there must be a no-op, not crash or misfire."""
    screen = _make_screen_with_items(qtbot)
    screen._handle_rows(InputAction.DOWN)
    screen._handle_rows(InputAction.DOWN)  # row 2 = SERIES
    screen.setFocus()
    requested = []
    screen.finish_progress_requested.connect(requested.append)

    qtbot.keyPress(screen, Qt.Key.Key_Return)
    qtbot.wait(600)
    qtbot.keyRelease(screen, Qt.Key.Key_Return)
    qtbot.wait(50)

    assert requested == []


def test_long_press_in_grid_zone_requests_finish_progress(qtbot):
    screen = _make_screen_in_grid(qtbot, row_idx=0)  # Continue Listening
    requested = []
    screen.finish_progress_requested.connect(requested.append)

    qtbot.keyPress(screen, Qt.Key.Key_Return)
    qtbot.wait(600)
    qtbot.keyRelease(screen, Qt.Key.Key_Return)
    qtbot.wait(50)

    assert len(requested) == 1
    assert requested[0].id == "i1"


def test_long_press_on_see_all_pseudo_item_does_not_request_finish_progress(qtbot):
    screen = _make_screen_with_items(qtbot)
    screen._row_item_idxs[0] = 1
    screen.setFocus()
    _press(qtbot, screen, Qt.Key.Key_Right)  # focus "See all"
    assert screen._see_all_focused is True
    requested = []
    screen.finish_progress_requested.connect(requested.append)

    qtbot.keyPress(screen, Qt.Key.Key_Return)
    qtbot.wait(600)
    qtbot.keyRelease(screen, Qt.Key.Key_Return)
    qtbot.wait(50)

    assert requested == []


def test_show_finish_confirm_unstarted_item_offers_mark_finished(qtbot):
    screen, item = _make_screen_with_durationed_item(qtbot)
    screen.setFocus()
    screen._pending_finish_item = item

    screen.show_finish_confirm(item, None)

    assert screen._finish_popup.isVisible()
    assert "as finished?" in screen._finish_popup._message_label.text()


def test_show_finish_confirm_finished_item_offers_mark_unfinished(qtbot):
    screen, item = _make_screen_with_durationed_item(qtbot)
    screen.setFocus()
    screen._pending_finish_item = item
    progress = MediaProgress(
        libraryItemId=item.id, isFinished=True, currentTime=3600.0, duration=3600.0,
    )

    screen.show_finish_confirm(item, progress)

    assert "as unfinished?" in screen._finish_popup._message_label.text()


def test_show_finish_confirm_shows_popup_for_all_books_card(qtbot):
    """Regression: _on_select_long_press() allows ALL_BOOKS, but
    show_finish_confirm() has its own, separate row-type check (used to
    detect the user navigating away while the progress fetch was in
    flight) -- it must allow ALL_BOOKS too, or the popup silently never
    appears even though finish_progress_requested fired correctly."""
    screen = _make_screen_with_items(qtbot)
    screen._handle_rows(InputAction.DOWN)
    screen._handle_rows(InputAction.DOWN)
    screen._handle_rows(InputAction.DOWN)  # row 3 = ALL_BOOKS
    screen.setFocus()
    item = screen._row_items[3][0]
    screen._pending_finish_item = item

    screen.show_finish_confirm(item, None)

    assert screen._finish_popup.isVisible()


def test_show_finish_confirm_ignores_response_superseded_by_a_later_long_press(qtbot):
    screen = _make_screen_with_items(qtbot)
    screen.setFocus()
    old_item = screen._row_items[0][0]
    new_item = screen._row_items[0][1]
    screen._pending_finish_item = new_item  # a second long-press already landed

    screen.show_finish_confirm(old_item, None)

    assert not screen._finish_popup.isVisible()


def test_show_finish_confirm_ignores_response_after_navigating_away(qtbot):
    screen = _make_screen_with_items(qtbot)
    screen.setFocus()
    item = screen._row_items[0][0]
    screen._pending_finish_item = item
    screen._handle_rows(InputAction.DOWN)  # user moved on before the fetch landed

    screen.show_finish_confirm(item, None)

    assert not screen._finish_popup.isVisible()
    assert screen._pending_finish_item is None


def test_confirming_mark_finished_emits_finished_changed_and_updates_card_badge(qtbot):
    screen, item = _make_screen_with_durationed_item(qtbot)
    screen.setFocus()
    screen._pending_finish_item = item
    screen._pending_finish_progress = None

    changes = []
    screen.finished_changed.connect(lambda *args: changes.append(args))
    screen._on_finish_confirmed()

    assert changes == [(item.id, item.duration, item.duration, True, "")]
    card = screen._row_widgets[0]._cards[0]
    assert card._finished is True
    assert screen._pending_finish_item is None


def test_confirming_mark_unfinished_restores_current_time_and_clears_badge(qtbot):
    screen, item = _make_screen_with_durationed_item(qtbot)
    screen.setFocus()
    progress = MediaProgress(
        libraryItemId=item.id, isFinished=True, currentTime=1200.0, duration=item.duration,
    )
    screen._pending_finish_item = item
    screen._pending_finish_progress = progress

    changes = []
    screen.finished_changed.connect(lambda *args: changes.append(args))
    screen._on_finish_confirmed()

    assert changes == [(item.id, 1200.0, item.duration, False, "")]
    card = screen._row_widgets[0]._cards[0]
    assert card._finished is False


def test_confirming_mark_finished_on_podcast_uses_recent_episode_id(qtbot):
    show = _podcast_show_with_recent_episode()
    screen, _item = _make_screen_with_durationed_item(qtbot, item=show)
    screen.setFocus()
    screen._pending_finish_item = show
    screen._pending_finish_progress = None

    changes = []
    screen.finished_changed.connect(lambda *args: changes.append(args))
    screen._on_finish_confirmed()

    assert changes[0][0] == show.id
    assert changes[0][4] == "ep1"


def test_cancelling_finish_popup_does_not_emit_finished_changed(qtbot):
    screen, item = _make_screen_with_durationed_item(qtbot)
    screen.setFocus()
    screen._pending_finish_item = item

    changes = []
    screen.finished_changed.connect(lambda *args: changes.append(args))
    screen._on_finish_cancelled()

    assert changes == []
    assert screen._pending_finish_item is None
