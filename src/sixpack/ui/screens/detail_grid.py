"""Shared shell for series-episode and playlist-item grid screens.

Backdrop + a static-title/dynamic-subtitle hero + a FocusGrid of
MediaCards. Subclasses (SeriesDetailScreen, PlaylistDetailScreen) supply
how to read title/subtitle/cover/progress from their own item type;
this class owns the shell, card construction, cover fetching, and focus
reflection, all of which are otherwise near-identical between the two.
"""
from __future__ import annotations

from typing import Any

from PyQt6 import sip
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from sixpack.ui.cover_cache import CoverCache, dominant_color
from sixpack.ui.widgets.focus_grid import FocusGrid
from sixpack.ui.widgets.hero_backdrop import HeroBackdrop
from sixpack.ui.widgets.media_card import MediaCard


class DetailGridScreen(QWidget):
    """Base shell for a Backdrop + hero + FocusGrid detail screen.

    Subclasses must override _item_key, _item_progress, _item_title,
    _item_subtitle, _item_cover_url. _item_media_type has a "book"
    default and is optional to override.
    """

    item_activated = pyqtSignal(object)
    back_requested = pyqtSignal()

    def __init__(self, cover_cache: CoverCache | None = None, parent=None) -> None:
        super().__init__(parent)
        self._cover_cache = cover_cache
        self._items: list[Any] = []
        self._progress: dict = {}
        self._server_url = ""
        self._token = ""
        self._dom_colors: dict[str, QColor] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        self._hero_backdrop = HeroBackdrop(self)

        self._grid = FocusGrid(columns=5)
        self._grid.item_activated.connect(self._on_item_activated)
        self._grid.focus_changed.connect(self._on_grid_focus_changed)

        layout = QVBoxLayout(self)
        # Top margin pushes the grid below the hero band (matches browse.py's
        # rows_layout treatment) so the first row of cards doesn't start
        # already overlapping the hero's title/subtitle text.
        layout.setContentsMargins(0, HeroBackdrop.HERO_H, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._grid)

    def resizeEvent(self, event) -> None:
        self._hero_backdrop.setGeometry(self.rect())
        super().resizeEvent(event)

    # ------------------------------------------------------------------
    # Subclass contract
    # ------------------------------------------------------------------

    def _item_key(self, item: Any) -> str:
        raise NotImplementedError

    def _item_progress(self, item: Any, progress: dict) -> tuple[float, bool]:
        raise NotImplementedError

    def _item_title(self, item: Any) -> str:
        raise NotImplementedError

    def _item_subtitle(self, item: Any) -> str:
        raise NotImplementedError

    def _item_cover_url(self, item: Any, server_url: str, token: str) -> str | None:
        raise NotImplementedError

    def _item_media_type(self, item: Any) -> str:
        return "book"

    # ------------------------------------------------------------------
    # Population
    # ------------------------------------------------------------------

    def _populate(
        self,
        title: str,
        items: list[Any],
        progress: dict,
        server_url: str,
        token: str,
        loading: bool = False,  # noqa: ARG002 — reserved for a future loading indicator; unused for now
    ) -> None:
        self._items = items
        self._progress = progress
        self._server_url = server_url
        self._token = token
        self._hero_backdrop.set_title(title)

        self._grid.clear()
        for item in items:
            self._grid.add_item(self._make_card(item))

        if self._grid.item_count:
            idx = self._find_resume_index()
            self._grid.focus_item(idx)
            self._reflect_focus(items[idx])

    def _refresh_progress(self, progress: dict) -> None:
        self._progress = progress
        for item, card in zip(self._items, self._grid._items):
            fraction, finished = self._item_progress(item, progress)
            card.set_progress(fraction)
            card.set_finished(finished)
        if self._grid.item_count:
            idx = self._find_resume_index()
            self._grid.focus_item(idx)
            self._reflect_focus(self._items[idx])

    def _find_resume_index(self) -> int:
        for i, item in enumerate(self._items):
            _fraction, finished = self._item_progress(item, self._progress)
            if not finished:
                return i
        return 0

    def _make_card(self, item: Any) -> MediaCard:
        card = MediaCard(
            title=self._item_title(item),
            subtitle=self._item_subtitle(item),
            media_type=self._item_media_type(item),
        )
        fraction, finished = self._item_progress(item, self._progress)
        card.set_progress(fraction)
        card.set_finished(finished)
        cover = self._item_cover_url(item, self._server_url, self._token)
        if cover and self._cover_cache is not None:
            key = self._item_key(item)
            self._fetch_cover(card, cover, key)
        return card

    def _fetch_cover(self, card: MediaCard, cover_url: str, key: str) -> None:
        def _cb(pm):
            # See browse.py's identical guard: a card can be deleted (grid
            # rebuild) before an in-flight cover fetch resolves.
            if sip.isdeleted(card):
                return
            card.set_cover(pm)
            if key not in self._dom_colors:
                self._dom_colors[key] = dominant_color(pm)

        self._cover_cache.fetch(cover_url, self._token, _cb)

    # ------------------------------------------------------------------
    # Focus reflection (hero subtitle + backdrop)
    # ------------------------------------------------------------------

    def _on_item_activated(self, index: int) -> None:
        if 0 <= index < len(self._items):
            self.item_activated.emit(self._items[index])

    def _on_grid_focus_changed(self, index: int) -> None:
        if 0 <= index < len(self._items):
            self._reflect_focus(self._items[index])

    def _reflect_focus(self, item: Any) -> None:
        self._hero_backdrop.set_subtitle(self._item_subtitle(item) or self._item_title(item))
        if self._cover_cache is None:
            return
        cover = self._item_cover_url(item, self._server_url, self._token)
        if not cover:
            return
        key = self._item_key(item)
        color = self._dom_colors.get(key)
        self._hero_backdrop.backdrop.set_expected_key(key)
        if color is not None:
            self._hero_backdrop.backdrop.show_color(color)
        self._cover_cache.fetch_backdrop(
            cover, self._token,
            lambda pm, k=key: self._hero_backdrop.backdrop.show_image(pm, key=k),
        )

    def focus_item_by_key(self, key: str) -> None:
        for i, item in enumerate(self._items):
            if self._item_key(item) == key:
                self._grid.focus_item(i)
                self._reflect_focus(item)
                return

    # ------------------------------------------------------------------
    # Keyboard
    # ------------------------------------------------------------------

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._grid.setFocus()

    def keyPressEvent(self, event) -> None:
        from sixpack.input.actions import InputAction
        from sixpack.input.keyboard import key_to_action

        action = key_to_action(event.key())
        if action == InputAction.BACK:
            self.back_requested.emit()
        else:
            super().keyPressEvent(event)
