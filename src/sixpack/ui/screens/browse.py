"""Kodi-style browse screen — library sidebar + horizontal content rows."""
from __future__ import annotations

from enum import Enum
from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
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
from sixpack.ui.cover_cache import CoverCache
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

class _SidebarItem(QWidget):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 12, 20, 12)
        layout.setSpacing(0)
        self._label = QLabel(text)
        self._label.setStyleSheet("background: transparent;")
        layout.addWidget(self._label)
        self.set_state(selected=False, zone_active=False)

    def set_state(self, *, selected: bool, zone_active: bool) -> None:
        if selected and zone_active:
            bg, fg = theme.ACCENT, theme.TEXT_PRIMARY
        elif selected:
            bg, fg = theme.SURFACE_HIGH, theme.ACCENT
        else:
            bg, fg = "transparent", theme.TEXT_SECONDARY
        self.setStyleSheet(
            f"QWidget {{ background-color: {bg}; border-radius: 4px; }}"
        )
        self._label.setStyleSheet(
            f"color: {fg}; font-size: {theme.FONT_BODY}pt; background: transparent;"
        )


# ---------------------------------------------------------------------------
# Row widget — one titled horizontal strip of MediaCards
# ---------------------------------------------------------------------------

class _RowWidget(QWidget):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cards: list[MediaCard] = []
        self._focused_idx = -1

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 4, 0, 4)
        outer.setSpacing(6)

        # Title bar
        title_bar = QWidget()
        title_bar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        tb_layout = QHBoxLayout(title_bar)
        tb_layout.setContentsMargins(0, 0, 0, 0)

        self._title_lbl = QLabel(title)
        self._title_lbl.setStyleSheet(
            f"font-size: {theme.FONT_HEADING}pt; font-weight: bold; color: {theme.TEXT_PRIMARY};"
        )
        tb_layout.addWidget(self._title_lbl)
        tb_layout.addStretch()

        self._see_all = QLabel("See all  →")
        self._see_all.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: {theme.FONT_META}pt;"
        )
        tb_layout.addWidget(self._see_all)
        outer.addWidget(title_bar)

        # Horizontal card strip
        self._strip = QWidget()
        self._strip.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._strip_layout = QHBoxLayout(self._strip)
        self._strip_layout.setContentsMargins(0, 0, 0, 0)
        self._strip_layout.setSpacing(16)
        self._strip_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidget(self._strip)
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(theme.CARD_HEIGHT + 12)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        scroll.setStyleSheet("border: none; background: transparent;")
        self._scroll = scroll
        outer.addWidget(scroll)

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
        color = theme.ACCENT if focused else theme.TEXT_MUTED
        self._see_all.setStyleSheet(
            f"color: {color}; font-size: {theme.FONT_META}pt;"
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

    Zones:
      "sidebar"  — arrow Up/Down moves sidebar selection
      "rows"     — arrow Left/Right scrolls within a row; Up/Down changes rows
      "grid"     — expanded full-pane grid for one row
    """

    series_selected = pyqtSignal(object)    # Series
    playlist_selected = pyqtSignal(object)  # Playlist
    book_selected = pyqtSignal(object)      # LibraryItem
    library_changed = pyqtSignal(object)    # Library — emitted when entering rows for a new lib

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

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_sidebar())
        root.addWidget(self._build_content(), stretch=1)

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setFixedWidth(_SIDEBAR_W)
        sidebar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        sidebar.setStyleSheet(f"background-color: {theme.SURFACE};")
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

        # --- Page 0: rows view ---
        rows_inner = QWidget()
        rows_inner.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        rows_layout = QVBoxLayout(rows_inner)
        rows_layout.setContentsMargins(32, 24, 32, 24)
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
        self._content_stack.addWidget(self._rows_scroll)

        # --- Page 1: expanded grid view ---
        grid_page = QWidget()
        grid_page.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        grid_page_layout = QVBoxLayout(grid_page)
        grid_page_layout.setContentsMargins(32, 24, 32, 24)
        grid_page_layout.setSpacing(16)

        self._grid_title_lbl = QLabel()
        self._grid_title_lbl.setStyleSheet(
            f"font-size: {theme.FONT_HEADING}pt; font-weight: bold; color: {theme.TEXT_PRIMARY};"
        )
        grid_page_layout.addWidget(self._grid_title_lbl)

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
        grid_page_layout.addWidget(self._grid_scroll)
        self._content_stack.addWidget(grid_page)

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
        for lib in self._libraries:
            item = _SidebarItem(lib.name)
            self._sidebar_items.append(item)
            self._sidebar_items_layout.addWidget(item)

    def _populate_row(self, row_idx: int) -> None:
        rw = self._row_widgets[row_idx]
        items = self._row_items[row_idx]
        rw.clear()
        for item in items:
            cover = item.cover_url(self._server_url, self._token) if callable(
                getattr(item, "cover_url", None)
            ) else None
            card = MediaCard(
                title=getattr(item, "title", ""),
                subtitle=getattr(item, "subtitle", ""),
            )
            if cover and self._cover_cache is not None:
                self._cover_cache.fetch(cover, self._token, card.set_cover)
            rw.add_card(card)

        if self._zone == "rows" and row_idx == self._focused_row and items:
            rw.focus_card(self._row_item_idxs[row_idx])

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
        if action == InputAction.UP and self._sidebar_idx > 0:
            self._sidebar_idx -= 1
            self._update_sidebar_styles()
        elif action == InputAction.DOWN and self._sidebar_idx < n - 1:
            self._sidebar_idx += 1
            self._update_sidebar_styles()
        elif action in (InputAction.RIGHT, InputAction.SELECT) and self._libraries:
            self._enter_rows()

    def _handle_rows(self, action: InputAction) -> None:
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
                self._enter_sidebar()
        elif action == InputAction.RIGHT:
            cur = self._row_item_idxs[self._focused_row]
            if cur < len(focused_items) - 1:
                self._row_item_idxs[self._focused_row] = cur + 1
                self._row_widgets[self._focused_row].focus_card(cur + 1)
        elif action == InputAction.SELECT:
            self._activate_row_item(self._focused_row, self._row_item_idxs[self._focused_row])
        elif action == InputAction.MENU:
            self._enter_grid(self._focused_row)
        elif action == InputAction.BACK:
            self._enter_sidebar()

    def _handle_grid(self, action: InputAction) -> None:
        count = len(self._grid_cards)
        idx = self._grid_focus_idx

        if action == InputAction.RIGHT and idx + 1 < count:
            self._set_grid_focus(idx + 1)
        elif action == InputAction.LEFT:
            if idx > 0:
                self._set_grid_focus(idx - 1)
            else:
                self._exit_grid()
        elif action == InputAction.DOWN and idx + _GRID_COLS < count:
            self._set_grid_focus(idx + _GRID_COLS)
        elif action == InputAction.UP:
            if idx - _GRID_COLS >= 0:
                self._set_grid_focus(idx - _GRID_COLS)
        elif action == InputAction.SELECT:
            self._activate_grid_item(idx)
        elif action == InputAction.BACK:
            self._exit_grid()

    # ------------------------------------------------------------------
    # Zone transitions
    # ------------------------------------------------------------------

    def _enter_rows(self) -> None:
        lib = self._libraries[self._sidebar_idx] if self._libraries else None
        if lib and lib is not self._loaded_library:
            self._loaded_library = lib
            self.library_changed.emit(lib)
        self._zone = "rows"
        self._content_stack.setCurrentIndex(0)
        self._update_sidebar_styles()
        self._update_row_styles()
        # Focus first item in the focused row if available
        if self._row_items[self._focused_row]:
            self._row_widgets[self._focused_row].focus_card(
                self._row_item_idxs[self._focused_row]
            )

    def _enter_sidebar(self) -> None:
        self._row_widgets[self._focused_row].unfocus()
        self._zone = "sidebar"
        self._update_sidebar_styles()
        self._update_row_styles()

    def _enter_grid(self, row_idx: int) -> None:
        items = self._row_items[row_idx]
        if not items:
            return
        self._zone = "grid"
        self._grid_row_idx = row_idx
        self._grid_focus_idx = self._row_item_idxs[row_idx]
        self._grid_title_lbl.setText(self._row_types[row_idx].value)

        # Clear old cards
        for card in self._grid_cards:
            self._grid_layout.removeWidget(card)
            card.deleteLater()
        self._grid_cards.clear()

        for i, item in enumerate(items):
            cover = item.cover_url(self._server_url, self._token) if callable(
                getattr(item, "cover_url", None)
            ) else None
            card = MediaCard(
                title=getattr(item, "title", ""),
                subtitle=getattr(item, "subtitle", ""),
            )
            card.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            if cover and self._cover_cache is not None:
                self._cover_cache.fetch(cover, self._token, card.set_cover)
            row, col = divmod(i, _GRID_COLS)
            self._grid_layout.addWidget(card, row, col)
            self._grid_cards.append(card)

        self._content_stack.setCurrentIndex(1)
        self._set_grid_focus(self._grid_focus_idx)
        self.setFocus()

    def _exit_grid(self) -> None:
        self._zone = "rows"
        # Sync row position to where we were in the grid
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

    # ------------------------------------------------------------------
    # Activation
    # ------------------------------------------------------------------

    def _activate_row_item(self, row_idx: int, item_idx: int) -> None:
        items = self._row_items[row_idx]
        if not items or item_idx >= len(items):
            return
        self._emit_item(self._row_types[row_idx], items[item_idx])

    def _activate_grid_item(self, idx: int) -> None:
        items = self._row_items[self._grid_row_idx]
        if not items or idx >= len(items):
            return
        self._emit_item(self._row_types[self._grid_row_idx], items[idx])

    def _emit_item(self, row_type: RowType, item: Any) -> None:
        if row_type == RowType.SERIES:
            self.series_selected.emit(item)
        elif row_type == RowType.PLAYLISTS:
            self.playlist_selected.emit(item)
        else:
            self.book_selected.emit(item)
