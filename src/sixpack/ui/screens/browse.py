"""Kodi-style browse screen — library sidebar + horizontal content rows."""
from __future__ import annotations

from enum import Enum
from typing import Any

from PyQt6 import sip
from PyQt6.QtCore import QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from sixpack.api.models import Library
from sixpack.input.actions import InputAction
from sixpack.input.keyboard import key_to_action
from sixpack.ui import theme
from sixpack.ui.cover_cache import CoverCache, dominant_color
from sixpack.ui.widgets.backdrop import Backdrop
from sixpack.ui.widgets.media_card import MediaCard

_SIDEBAR_W = 220
_GRID_COLS = 5


class RowType(Enum):
    CONTINUE_LISTENING = "Continue Listening"
    RECENTLY_ADDED = "Recently Added"
    SERIES = "Series"
    PLAYLISTS = "Playlists"


DEFAULT_ROW_TYPES: list[RowType] = [
    RowType.CONTINUE_LISTENING,
    RowType.RECENTLY_ADDED,
    RowType.SERIES,
    RowType.PLAYLISTS,
]


# ---------------------------------------------------------------------------
# Sidebar item
# ---------------------------------------------------------------------------

_LIB_ICONS = {"book": "📚", "podcast": "🎙", "ebook": "📖"}


class _SidebarItem(QWidget):
    def __init__(
        self, text: str, media_type: str = "book", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 12, 20, 12)
        layout.setSpacing(10)
        self._icon = QLabel(_LIB_ICONS.get(media_type, "📚"))
        self._icon.setStyleSheet("background: transparent;")
        self._label = QLabel(text)
        self._label.setStyleSheet("background: transparent;")
        layout.addWidget(self._icon)
        layout.addWidget(self._label)
        layout.addStretch()
        self.set_state(selected=False, zone_active=False)

    def set_state(self, *, selected: bool, zone_active: bool) -> None:
        if selected and zone_active:
            bg, fg, bar = theme.ACCENT, theme.TEXT_PRIMARY, theme.ACCENT
        elif selected:
            bg, fg, bar = theme.SURFACE_HIGH, theme.ACCENT, theme.ACCENT
        else:
            bg, fg, bar = "transparent", theme.TEXT_SECONDARY, "transparent"
        self.setStyleSheet(
            f"QWidget {{ background-color: {bg}; border-radius: 4px; "
            f"border-left: 3px solid {bar}; }}"
        )
        self._label.setStyleSheet(
            f"color: {fg}; font-size: {theme.FONT_BODY}pt; background: transparent; border: none;"
        )
        self._icon.setStyleSheet("background: transparent; border: none;")


# ---------------------------------------------------------------------------
# Row widget — one titled horizontal strip of MediaCards
# ---------------------------------------------------------------------------

_BODY_H = theme.CARD_HEIGHT + 12  # fixed height for the card body area


class _RowWidget(QWidget):
    """
    Titled horizontal strip with three body states:
      loading  — shows "Loading…" while content is being fetched
      empty    — shows "Nothing here" when fetch returned no items
      cards    — shows the horizontal scroll of MediaCards
    """

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cards: list[MediaCard] = []
        self._focused_idx = -1
        self._row_is_focused = False
        self._see_all_is_focused = False

        # Like every plain QWidget in this app, `self` and its child
        # container widgets get an opaque background painted by the
        # app-wide stylesheet's `QWidget { background-color: ... }` rule
        # unless overridden — which would occlude `BrowseScreen._backdrop`
        # just as badly as the un-fixed page-level scroll areas did.
        self.setStyleSheet("background: transparent;")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 4, 0, 4)
        outer.setSpacing(6)

        # Title bar
        title_bar = QWidget()
        title_bar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        title_bar.setStyleSheet("background: transparent;")
        tb_layout = QHBoxLayout(title_bar)
        tb_layout.setContentsMargins(0, 0, 0, 0)

        self._title_lbl = QLabel(title)
        self._title_lbl.setStyleSheet(
            f"font-size: {theme.FONT_HEADING}pt; font-weight: bold; color: {theme.TEXT_PRIMARY};"
        )
        tb_layout.addWidget(self._title_lbl)
        tb_layout.addStretch()

        self._see_all = QLabel("See all →")
        self._see_all.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: {theme.FONT_META}pt;"
        )
        tb_layout.addWidget(self._see_all)
        outer.addWidget(title_bar)

        self._strip = QWidget()
        self._strip.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._strip.setStyleSheet("background: transparent;")
        self._strip_layout = QHBoxLayout(self._strip)
        self._strip_layout.setContentsMargins(0, 0, 0, 0)
        self._strip_layout.setSpacing(16)
        self._strip_layout.addStretch()

        self._scroll = QScrollArea()
        self._scroll.setWidget(self._strip)
        self._scroll.setFixedHeight(_BODY_H)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._scroll.setStyleSheet("border: none; background: transparent;")
        self._scroll.viewport().setStyleSheet("background: transparent;")
        outer.addWidget(self._scroll)

    # ------------------------------------------------------------------

    def clear(self) -> None:
        while self._strip_layout.count() > 1:
            it = self._strip_layout.takeAt(0)
            if w := it.widget():
                w.deleteLater()
        self._cards.clear()
        self._focused_idx = -1

    def add_card(self, card: MediaCard) -> None:
        card.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._cards.append(card)
        self._strip_layout.insertWidget(self._strip_layout.count() - 1, card)

    @property
    def card_count(self) -> int:
        return len(self._cards)

    def focus_card(self, idx: int) -> None:
        if not self._cards:
            return
        idx = max(0, min(idx, len(self._cards) - 1))
        if 0 <= self._focused_idx < len(self._cards):
            self._cards[self._focused_idx].set_focused(False)
        self._focused_idx = idx
        self._cards[idx].set_focused(True)
        self._scroll.ensureWidgetVisible(self._cards[idx])

    def unfocus(self) -> None:
        if 0 <= self._focused_idx < len(self._cards):
            self._cards[self._focused_idx].set_focused(False)

    def set_row_focused(self, focused: bool) -> None:
        self._row_is_focused = focused
        self._refresh_see_all_style()

    def set_see_all_focused(self, focused: bool) -> None:
        self._see_all_is_focused = focused
        self._refresh_see_all_style()

    def _refresh_see_all_style(self) -> None:
        if self._see_all_is_focused:
            self._see_all.setStyleSheet(
                f"color: {theme.TEXT_PRIMARY}; background-color: {theme.ACCENT}; "
                f"font-size: {theme.FONT_META}pt; border-radius: 4px; padding: 2px 8px;"
            )
        elif self._row_is_focused:
            self._see_all.setStyleSheet(
                f"color: {theme.ACCENT}; background: transparent; font-size: {theme.FONT_META}pt;"
            )
        else:
            self._see_all.setStyleSheet(
                f"color: {theme.TEXT_SECONDARY}; background-color: {theme.SURFACE_HIGH}; "
                f"font-size: {theme.FONT_META}pt; border-radius: 4px; padding: 2px 8px;"
            )

    @property
    def focused_idx(self) -> int:
        return self._focused_idx


# ---------------------------------------------------------------------------
# BrowseScreen
# ---------------------------------------------------------------------------

class BrowseScreen(QWidget):
    """
    Kodi-style home screen.

    Left sidebar lists libraries; right pane shows horizontal content rows.
    All keyboard navigation is handled here — no child widget takes Qt focus.

    Content starts loading as soon as a library is highlighted in the sidebar
    (not just when the user presses Right to enter the rows zone), so there is
    always something to show (or a loading indicator) immediately.

    Zones:
      "sidebar"  — arrow Up/Down moves sidebar selection
      "rows"     — arrow Left/Right scrolls within a row; Up/Down changes rows
      "grid"     — expanded full-pane grid for one row (sidebar stays visible)
    """

    series_selected = pyqtSignal(object)    # Series
    playlist_selected = pyqtSignal(object)  # Playlist
    book_selected = pyqtSignal(object)      # LibraryItem
    library_changed = pyqtSignal(object)    # Library — emitted whenever a new library is selected
    see_all_requested = pyqtSignal(object)  # RowType — user wants the full uncapped dataset

    def __init__(
        self,
        row_types: list[RowType] | None = None,
        cover_cache: CoverCache | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._row_types = row_types or DEFAULT_ROW_TYPES
        self._cover_cache = cover_cache
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._zone = "sidebar"
        self._loading = False
        self._see_all_focused = False
        self._grid_items: list[Any] = []
        self._libraries: list[Library] = []
        self._loaded_library: Library | None = None
        self._sidebar_idx = 0
        self._server_url = ""
        self._token = ""

        self._row_items: list[list[Any]] = [[] for _ in self._row_types]
        self._focused_row = 0
        self._row_item_idxs: list[int] = [0] * len(self._row_types)

        # Grid (expanded) state
        self._grid_row_idx = 0
        self._grid_focus_idx = 0
        self._grid_cards: list[MediaCard] = []

        self._sidebar_items: list[_SidebarItem] = []
        self._build_ui()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    _HERO_H = 150

    def _build_ui(self) -> None:
        self.setObjectName("screen_root")
        self._backdrop = Backdrop(self)
        self._backdrop.lower()
        self._dom_colors: dict[str, QColor] = {}

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_sidebar())
        root.addWidget(self._build_content(), stretch=1)
        self._build_hero()  # overlay child on the content pane

    def resizeEvent(self, event) -> None:
        self._backdrop.setGeometry(self.rect())
        if hasattr(self, "_hero"):
            self._hero.setGeometry(self._hero_geometry())
        super().resizeEvent(event)

    def _build_hero(self) -> None:
        self._hero = QWidget(self)
        self._hero.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        # A flat opaque background here would fully hide the backdrop behind
        # the hero band and create a hard edge where rows scroll up underneath
        # it (ensureWidgetVisible). A top-opaque/bottom-transparent scrim
        # keeps the title/subtitle legible while letting the backdrop (and
        # any content scrolling up underneath) show through at the bottom.
        self._hero.setStyleSheet(f"background: {theme.GRADIENT_HERO_SCRIM};")
        lay = QVBoxLayout(self._hero)
        lay.setContentsMargins(36, 24, 36, 8)
        lay.setSpacing(4)
        self._hero_title = QLabel("")
        self._hero_title.setStyleSheet(
            f"font-size: {theme.FONT_HUGE}pt; font-weight: bold; "
            f"color: {theme.TEXT_PRIMARY}; background: transparent;"
        )
        self._hero_sub = QLabel("")
        self._hero_sub.setStyleSheet(
            f"font-size: {theme.FONT_HEADING}pt; color: {theme.TEXT_SECONDARY}; "
            f"background: transparent;"
        )
        lay.addWidget(self._hero_title)
        lay.addWidget(self._hero_sub)
        self._hero.raise_()

    def _hero_geometry(self) -> QRect:
        return QRect(_SIDEBAR_W, 0, max(0, self.width() - _SIDEBAR_W), self._HERO_H)

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setFixedWidth(_SIDEBAR_W)
        sidebar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        sidebar.setStyleSheet("background-color: rgba(21,21,21,200);")
        sidebar.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 24, 0, 24)
        layout.setSpacing(0)

        header = QLabel("LIBRARIES")
        header.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: {theme.FONT_META - 1}pt; "
            f"font-weight: bold; padding: 0 20px 12px 20px; letter-spacing: 2px; "
            f"background: transparent;"
        )
        layout.addWidget(header)

        self._sidebar_items_container = QWidget()
        self._sidebar_items_container.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._sidebar_items_layout = QVBoxLayout(self._sidebar_items_container)
        self._sidebar_items_layout.setContentsMargins(8, 0, 8, 0)
        self._sidebar_items_layout.setSpacing(2)

        sidebar_scroll = QScrollArea()
        sidebar_scroll.setWidget(self._sidebar_items_container)
        sidebar_scroll.setWidgetResizable(True)
        sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sidebar_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sidebar_scroll.setStyleSheet("background: transparent; border: none;")
        sidebar_scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._sidebar_scroll = sidebar_scroll
        layout.addWidget(sidebar_scroll)

        return sidebar

    def _build_content(self) -> QWidget:
        self._content_stack = QStackedWidget()
        self._content_stack.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # The app-wide stylesheet's `QWidget { background-color: ... }` rule
        # paints every plain QWidget opaque (that's how Qt style sheets
        # work once an app-level sheet targets the base QWidget class) —
        # which fully occludes `self._backdrop` (lowered behind this whole
        # content pane). Make the stack itself transparent; the rows/grid
        # scroll areas below get the same treatment for the same reason.
        self._content_stack.setStyleSheet("background: transparent;")

        # --- Page 0: rows view ---
        rows_inner = QWidget()
        rows_inner.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        rows_layout = QVBoxLayout(rows_inner)
        rows_layout.setContentsMargins(32, self._HERO_H, 32, 24)
        rows_layout.setSpacing(12)

        self._row_widgets: list[_RowWidget] = []
        for rt in self._row_types:
            rw = _RowWidget(rt.value)
            rw.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self._row_widgets.append(rw)
            rows_layout.addWidget(rw)
        rows_layout.addStretch()

        self._rows_scroll = QScrollArea()
        self._rows_scroll.setWidget(rows_inner)
        self._rows_scroll.setWidgetResizable(True)
        self._rows_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._rows_scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # QScrollArea (and its viewport, and the plain QWidget it wraps) all
        # get an opaque background-color painted onto them by the app-wide
        # stylesheet unless explicitly overridden — same occlusion issue as
        # `self._content_stack` above. Without this, `self._backdrop` never
        # shows through the rows page at all.
        self._rows_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self._rows_scroll.viewport().setStyleSheet("background: transparent;")
        rows_inner.setStyleSheet("background: transparent;")
        self._content_stack.addWidget(self._rows_scroll)

        # --- Page 1: expanded grid view ---
        grid_page = QWidget()
        grid_page.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # Same occlusion issue as the rows page: this plain QWidget (and the
        # QStackedWidget it wraps below) get an opaque app-wide background
        # unless overridden, which would hide the backdrop behind any empty
        # space in the grid.
        grid_page.setStyleSheet("background: transparent;")
        grid_page_layout = QVBoxLayout(grid_page)
        # The hero overlay is stacked on top of whichever content-stack page
        # is showing (see _build_hero/_hero_geometry) — it isn't specific to
        # the rows page. Reserve the same top clearance the rows page uses
        # (rows_layout above) or the grid's title/first row sit underneath it.
        grid_page_layout.setContentsMargins(32, self._HERO_H, 32, 24)
        grid_page_layout.setSpacing(16)

        self._grid_title_lbl = QLabel()
        self._grid_title_lbl.setStyleSheet(
            f"font-size: {theme.FONT_HEADING}pt; font-weight: bold; color: {theme.TEXT_PRIMARY};"
        )
        grid_page_layout.addWidget(self._grid_title_lbl)

        self._grid_body_stack = QStackedWidget()
        self._grid_body_stack.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._grid_body_stack.setStyleSheet("background: transparent;")

        # Page 0: loading label shown while full dataset is fetched
        grid_loading = QWidget()
        grid_loading.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        gl_layout = QVBoxLayout(grid_loading)
        gl_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        gl_lbl = QLabel("Loading…")
        gl_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        gl_lbl.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: {theme.FONT_HEADING}pt;"
        )
        gl_layout.addWidget(gl_lbl)
        self._grid_body_stack.addWidget(grid_loading)

        # Page 1: the actual grid
        self._grid_container = QWidget()
        self._grid_container.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._grid_layout = QGridLayout(self._grid_container)
        self._grid_layout.setHorizontalSpacing(20)
        self._grid_layout.setVerticalSpacing(20)
        self._grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._grid_layout.setContentsMargins(0, 0, 0, 0)

        self._grid_scroll = QScrollArea()
        self._grid_scroll.setWidget(self._grid_container)
        self._grid_scroll.setWidgetResizable(True)
        self._grid_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._grid_scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # Same transparent treatment as `self._rows_scroll` above — otherwise
        # the grid page occludes the backdrop just as badly as the rows page did.
        self._grid_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self._grid_scroll.viewport().setStyleSheet("background: transparent;")
        self._grid_container.setStyleSheet("background: transparent;")
        self._grid_body_stack.addWidget(self._grid_scroll)

        grid_page_layout.addWidget(self._grid_body_stack)
        self._content_stack.addWidget(grid_page)

        # --- Page 2: full-pane loading indicator ---
        loading_page = QWidget()
        loading_page.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        lp_layout = QVBoxLayout(loading_page)
        lp_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading_lbl = QLabel("Loading…")
        self._loading_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading_lbl.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: {theme.FONT_HEADING}pt;"
        )
        lp_layout.addWidget(self._loading_lbl)
        self._content_stack.addWidget(loading_page)

        return self._content_stack

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def load_libraries(
        self, libraries: list[Library], server_url: str, token: str
    ) -> None:
        self._libraries = libraries
        self._server_url = server_url
        self._token = token
        self._rebuild_sidebar()
        self._sidebar_idx = 0
        self._loaded_library = None
        self._update_sidebar_styles()
        self._reset_rows()  # show Loading… immediately

    def _reset_rows(self) -> None:
        """Clear all rows and show the full-pane loading indicator."""
        for i, rw in enumerate(self._row_widgets):
            self._row_items[i] = []
            self._row_item_idxs[i] = 0
            rw.clear()
        self._focused_row = 0
        self._loading = True
        self._content_stack.setCurrentIndex(2)
        # Discarding row data can leave the hero reflecting an item that no
        # longer belongs to the now-selected library (e.g. switching
        # libraries in the sidebar) — keep it in sync with the (now empty)
        # focus rather than leaving stale title/author/backdrop showing.
        self._reflect_current()

    def show_content(self) -> None:
        """Switch from the loading page to the rows page once content is ready."""
        self._loading = False
        if self._zone in ("sidebar", "rows"):
            self._content_stack.setCurrentIndex(0)
        # Content just became available — sync the hero to whatever's now
        # focused (e.g. the sidebar zone's first-item preview), since
        # nothing else reflects it until the user navigates by hand.
        self._reflect_current()

    def set_row_items(self, row_type: RowType, items: list[Any]) -> None:
        try:
            idx = self._row_types.index(row_type)
        except ValueError:
            return
        self._row_items[idx] = items
        self._row_item_idxs[idx] = 0
        self._populate_row(idx)

    def _rebuild_sidebar(self) -> None:
        for w in self._sidebar_items:
            w.deleteLater()
        self._sidebar_items.clear()
        # Drop any leftover layout items (e.g. the addStretch() below, or
        # entries left behind by the widgets deleteLater()'d above) so a
        # second load_libraries() call doesn't accumulate stray stretches.
        while self._sidebar_items_layout.count():
            self._sidebar_items_layout.takeAt(0)
        for lib in self._libraries:
            item = _SidebarItem(lib.name, media_type=getattr(lib, "media_type", "book"))
            self._sidebar_items.append(item)
            self._sidebar_items_layout.addWidget(item)
        # Without this, items expand to fill the column's remaining vertical
        # space — which, combined with the `border-left: 3px solid {bar}`
        # accent styling in _SidebarItem.set_state(), makes the accent bar
        # stretch across the whole column instead of staying item-sized.
        self._sidebar_items_layout.addStretch()

    def _make_card(self, item: Any) -> MediaCard:
        """Build a MediaCard for `item`, wiring cover art + media-type glyph.

        Shared by every MediaCard call site (row strips, "see all" grid,
        expanded row grid) so cover-fetch wiring and media_type only need to
        be written once.
        """
        cover = item.cover_url(self._server_url, self._token) if callable(
            getattr(item, "cover_url", None)
        ) else None
        card = MediaCard(
            title=getattr(item, "title", ""),
            subtitle=getattr(item, "subtitle", ""),
            media_type=getattr(item, "media_type", "book"),
        )
        if cover and self._cover_cache is not None:
            self._fetch_cover(card, cover, getattr(item, "id", "") or cover)
        return card

    def _populate_row(self, row_idx: int) -> None:
        rw = self._row_widgets[row_idx]
        items = self._row_items[row_idx]
        rw.clear()
        for item in items:
            rw.add_card(self._make_card(item))

        if self._zone == "rows" and row_idx == self._focused_row and items:
            rw.focus_card(self._row_item_idxs[row_idx])

    # ------------------------------------------------------------------
    # Cover art + reflective hero
    # ------------------------------------------------------------------

    def _fetch_cover(self, card: MediaCard, cover_url: str, key: str) -> None:
        def _cb(pm):
            # The card can be deleted (e.g. a row/grid rebuild via "see
            # all", or navigating away) before an in-flight cover fetch
            # resolves — CoverCache holds this callback in _pending
            # regardless of whether the widget it targets still exists.
            # Touching a deleted C++ QWidget from a callback raises
            # RuntimeError, which is fatal here since nothing else catches
            # exceptions raised inside a Qt slot.
            if sip.isdeleted(card):
                return
            card.set_cover(pm)
            if key not in self._dom_colors:
                self._dom_colors[key] = dominant_color(pm)

        self._cover_cache.fetch(cover_url, self._token, _cb)

    def _reflect_focus(self, item: Any) -> None:
        title = getattr(item, "title", "") if item is not None else ""
        sub = getattr(item, "subtitle", "") if item is not None else ""
        self._hero_title.setText(title or "")
        self._hero_sub.setText(sub or "")
        if item is None or self._cover_cache is None:
            return
        cover = item.cover_url(self._server_url, self._token) if callable(
            getattr(item, "cover_url", None)
        ) else None
        if not cover:
            return
        key = getattr(item, "id", "") or cover
        # Record which item the backdrop should now be showing *before*
        # kicking off the (possibly async) fetch below. On a cold disk
        # cache, an uncached item's fetch can still be in flight when focus
        # moves on to a different (already-cached) item that paints first —
        # tagging the callback with `key` lets Backdrop drop it if it
        # resolves after we're no longer looking at this item.
        self._backdrop.set_expected_key(key)
        color = self._dom_colors.get(key)
        if color is not None:
            self._backdrop.show_color(color, key=key)
        self._cover_cache.fetch_backdrop(
            cover, self._token, lambda pm, k=key: self._backdrop.show_image(pm, k)
        )

    def _current_focused_item(self) -> Any | None:
        if self._zone == "grid":
            if self._grid_items and 0 <= self._grid_focus_idx < len(self._grid_items):
                return self._grid_items[self._grid_focus_idx]
            return None
        if self._zone == "rows":
            items = self._row_items[self._focused_row]
            idx = self._row_item_idxs[self._focused_row]
            if items and 0 <= idx < len(items):
                return items[idx]
            return None
        # sidebar zone: preview the first item of the first non-empty row
        for items in self._row_items:
            if items:
                return items[0]
        return None

    def _reflect_current(self) -> None:
        self._reflect_focus(self._current_focused_item())

    # ------------------------------------------------------------------
    # Style helpers
    # ------------------------------------------------------------------

    def _update_sidebar_styles(self) -> None:
        active = self._zone == "sidebar"
        for i, item in enumerate(self._sidebar_items):
            item.set_state(selected=(i == self._sidebar_idx), zone_active=active)

    def _update_row_styles(self) -> None:
        in_rows = self._zone == "rows"
        for i, rw in enumerate(self._row_widgets):
            rw.set_row_focused(in_rows and i == self._focused_row)
        if in_rows and self._row_widgets:
            if self._focused_row == 0:
                # ensureWidgetVisible()'s default margin only guarantees the
                # row is visible with SOME breathing room, not scroll==0 —
                # row 0's title sits at the very top of the scrollable
                # content (nothing above it but the hero's reserved
                # clearance), so any nonzero residual scroll pushes that
                # title up underneath the hero overlay. Force it flush.
                self._rows_scroll.verticalScrollBar().setValue(0)
            else:
                self._rows_scroll.ensureWidgetVisible(self._row_widgets[self._focused_row])

    # ------------------------------------------------------------------
    # Key handling
    # ------------------------------------------------------------------

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.setFocus()

    def keyPressEvent(self, event) -> None:
        action = key_to_action(event.key())
        if action is None:
            super().keyPressEvent(event)
            return
        if self._zone == "sidebar":
            self._handle_sidebar(action)
        elif self._zone == "rows":
            self._handle_rows(action)
        elif self._zone == "grid":
            self._handle_grid(action)

    def _handle_sidebar(self, action: InputAction) -> None:
        n = len(self._sidebar_items)
        moved = False

        if action == InputAction.UP and self._sidebar_idx > 0:
            self._sidebar_idx -= 1
            moved = True
        elif action == InputAction.DOWN and self._sidebar_idx < n - 1:
            self._sidebar_idx += 1
            moved = True

        if moved:
            self._update_sidebar_styles()
            self._start_loading_selected_library()
        elif action in (InputAction.RIGHT, InputAction.SELECT) and self._libraries:
            self._enter_rows()

    def _start_loading_selected_library(self) -> None:
        """Eagerly trigger a content fetch for the currently highlighted library."""
        if not self._libraries:
            return
        lib = self._libraries[self._sidebar_idx]
        if lib is self._loaded_library:
            return
        self._loaded_library = lib
        self._reset_rows()
        self.library_changed.emit(lib)

    def _handle_rows(self, action: InputAction) -> None:
        # When "See all" is focused, only a subset of actions are meaningful
        if self._see_all_focused:
            if action == InputAction.SELECT:
                self._trigger_see_all()
            elif action == InputAction.LEFT:
                self._set_see_all_focused(False)
                items = self._row_items[self._focused_row]
                if items:
                    self._row_widgets[self._focused_row].focus_card(
                        self._row_item_idxs[self._focused_row]
                    )
                self._reflect_current()
            elif action == InputAction.BACK:
                self._set_see_all_focused(False)
                self._enter_sidebar()
            elif action in (InputAction.UP, InputAction.DOWN):
                self._set_see_all_focused(False)
                # fall through to normal Up/Down handling below
            else:
                return
            if action not in (InputAction.UP, InputAction.DOWN):
                return

        n_rows = len(self._row_types)
        focused_items = self._row_items[self._focused_row]

        if action == InputAction.UP:
            if self._focused_row > 0:
                self._row_widgets[self._focused_row].unfocus()
                self._focused_row -= 1
                self._update_row_styles()
                if self._row_items[self._focused_row]:
                    self._row_widgets[self._focused_row].focus_card(
                        self._row_item_idxs[self._focused_row]
                    )
        elif action == InputAction.DOWN:
            if self._focused_row < n_rows - 1:
                self._row_widgets[self._focused_row].unfocus()
                self._focused_row += 1
                self._update_row_styles()
                if self._row_items[self._focused_row]:
                    self._row_widgets[self._focused_row].focus_card(
                        self._row_item_idxs[self._focused_row]
                    )
        elif action == InputAction.LEFT:
            cur = self._row_item_idxs[self._focused_row]
            if cur > 0:
                self._row_item_idxs[self._focused_row] = cur - 1
                self._row_widgets[self._focused_row].focus_card(cur - 1)
            else:
                # _enter_sidebar() already ends with its own
                # _reflect_current() call — return here rather than
                # falling through to the trailing call below, which would
                # otherwise fire self._reflect_focus() a second time for
                # the same (now sidebar-zone) focus.
                self._enter_sidebar()
                return
        elif action == InputAction.RIGHT:
            cur = self._row_item_idxs[self._focused_row]
            if cur < len(focused_items) - 1:
                self._row_item_idxs[self._focused_row] = cur + 1
                self._row_widgets[self._focused_row].focus_card(cur + 1)
            elif focused_items:
                self._set_see_all_focused(True)
        elif action == InputAction.SELECT:
            self._activate_row_item(self._focused_row, self._row_item_idxs[self._focused_row])
        elif action == InputAction.BACK:
            # Same reasoning as the LEFT-at-boundary branch above:
            # _enter_sidebar() already reflects, so return instead of
            # falling through to the trailing call.
            self._enter_sidebar()
            return
        self._reflect_current()

    def _handle_grid(self, action: InputAction) -> None:
        count = len(self._grid_cards)
        idx = self._grid_focus_idx

        # _set_grid_focus() already ends with its own _reflect_current()
        # call, so the branches that call it return immediately rather
        # than falling through to the trailing call below (which would
        # otherwise fire self._reflect_focus() a second time for the same
        # focus). _exit_grid() does NOT reflect internally, so the
        # LEFT-at-boundary and BACK branches (which call it instead) must
        # keep falling through to the trailing call — as must the no-op
        # boundary cases (RIGHT/DOWN/UP with no room to move) and SELECT,
        # none of which change focus but still rely on the trailing call
        # to keep the hero/backdrop consistent.
        if action == InputAction.RIGHT and idx + 1 < count:
            self._set_grid_focus(idx + 1)
            return
        elif action == InputAction.LEFT:
            if idx > 0:
                self._set_grid_focus(idx - 1)
                return
            else:
                self._exit_grid()
        elif action == InputAction.DOWN and idx + _GRID_COLS < count:
            self._set_grid_focus(idx + _GRID_COLS)
            return
        elif action == InputAction.UP:
            if idx - _GRID_COLS >= 0:
                self._set_grid_focus(idx - _GRID_COLS)
                return
        elif action == InputAction.SELECT:
            self._activate_grid_item(idx)
        elif action == InputAction.BACK:
            self._exit_grid()
        self._reflect_current()

    # ------------------------------------------------------------------
    # Zone transitions
    # ------------------------------------------------------------------

    def _enter_rows(self) -> None:
        # Trigger a content load if this library hasn't been loaded yet
        # (handles the case where user goes Right without having moved Up/Down)
        if self._libraries:
            lib = self._libraries[self._sidebar_idx]
            if lib is not self._loaded_library:
                self._loaded_library = lib
                self._reset_rows()
                self.library_changed.emit(lib)
        self._zone = "rows"
        if not self._loading:
            self._content_stack.setCurrentIndex(0)
        self._update_sidebar_styles()
        self._update_row_styles()
        if self._row_items[self._focused_row]:
            self._row_widgets[self._focused_row].focus_card(
                self._row_item_idxs[self._focused_row]
            )
        self._reflect_current()

    def _set_see_all_focused(self, focused: bool) -> None:
        self._see_all_focused = focused
        self._row_widgets[self._focused_row].set_see_all_focused(focused)

    def _trigger_see_all(self) -> None:
        """Enter the grid in loading state and ask app.py for the full dataset."""
        row_idx = self._focused_row
        self._set_see_all_focused(False)
        self._zone = "grid"
        self._grid_row_idx = row_idx
        self._grid_focus_idx = 0
        self._grid_items = []
        self._grid_title_lbl.setText(self._row_types[row_idx].value)
        for card in self._grid_cards:
            self._grid_layout.removeWidget(card)
            card.deleteLater()
        self._grid_cards.clear()
        self._grid_body_stack.setCurrentIndex(0)  # loading page
        self._content_stack.setCurrentIndex(1)
        self.setFocus()
        self.see_all_requested.emit(self._row_types[row_idx])

    def populate_grid(self, items: list[Any]) -> None:
        """Fill the grid with the full dataset returned by app.py."""
        self._grid_items = items
        for card in self._grid_cards:
            self._grid_layout.removeWidget(card)
            card.deleteLater()
        self._grid_cards.clear()
        for i, item in enumerate(items):
            card = self._make_card(item)
            card.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            row, col = divmod(i, _GRID_COLS)
            self._grid_layout.addWidget(card, row, col)
            self._grid_cards.append(card)
        self._grid_body_stack.setCurrentIndex(1)  # content page
        if self._grid_cards:
            self._set_grid_focus(0)

    def _enter_sidebar(self) -> None:
        if self._see_all_focused:
            self._set_see_all_focused(False)
        self._row_widgets[self._focused_row].unfocus()
        self._zone = "sidebar"
        self._update_sidebar_styles()
        self._update_row_styles()
        self._reflect_current()

    def _enter_grid(self, row_idx: int) -> None:
        items = self._row_items[row_idx]
        if not items:
            return
        self._zone = "grid"
        self._grid_row_idx = row_idx
        self._grid_focus_idx = self._row_item_idxs[row_idx]
        self._grid_title_lbl.setText(self._row_types[row_idx].value)

        for card in self._grid_cards:
            self._grid_layout.removeWidget(card)
            card.deleteLater()
        self._grid_cards.clear()

        for i, item in enumerate(items):
            card = self._make_card(item)
            card.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            row, col = divmod(i, _GRID_COLS)
            self._grid_layout.addWidget(card, row, col)
            self._grid_cards.append(card)

        self._grid_items = list(items)
        self._grid_body_stack.setCurrentIndex(1)  # content page
        self._content_stack.setCurrentIndex(1)
        self._set_grid_focus(self._grid_focus_idx)
        self.setFocus()

    def _exit_grid(self) -> None:
        self._zone = "rows"
        self._row_item_idxs[self._grid_row_idx] = self._grid_focus_idx
        self._row_widgets[self._grid_row_idx].focus_card(self._grid_focus_idx)
        self._content_stack.setCurrentIndex(0)
        self._focused_row = self._grid_row_idx
        self._update_row_styles()

    def _set_grid_focus(self, idx: int) -> None:
        if not self._grid_cards:
            return
        idx = max(0, min(idx, len(self._grid_cards) - 1))
        if 0 <= self._grid_focus_idx < len(self._grid_cards):
            self._grid_cards[self._grid_focus_idx].set_focused(False)
        self._grid_focus_idx = idx
        self._grid_cards[idx].set_focused(True)
        self._grid_scroll.ensureWidgetVisible(self._grid_cards[idx])
        self._reflect_current()

    # ------------------------------------------------------------------
    # Activation
    # ------------------------------------------------------------------

    def _activate_row_item(self, row_idx: int, item_idx: int) -> None:
        items = self._row_items[row_idx]
        if not items or item_idx >= len(items):
            return
        self._emit_item(self._row_types[row_idx], items[item_idx])

    def _activate_grid_item(self, idx: int) -> None:
        if not self._grid_items or idx >= len(self._grid_items):
            return
        self._emit_item(self._row_types[self._grid_row_idx], self._grid_items[idx])

    def _emit_item(self, row_type: RowType, item: Any) -> None:
        if row_type == RowType.SERIES:
            self.series_selected.emit(item)
        elif row_type == RowType.PLAYLISTS:
            self.playlist_selected.emit(item)
        else:
            self.book_selected.emit(item)
