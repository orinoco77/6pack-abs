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

from sixpack.api.models import MediaProgress
from sixpack.ui import theme
from sixpack.ui.cover_cache import CoverCache, dominant_color
from sixpack.ui.widgets.confirm_popup import ConfirmPopup
from sixpack.ui.widgets.focus_grid import FocusGrid
from sixpack.ui.widgets.hero_backdrop import HeroBackdrop
from sixpack.ui.widgets.media_card import MediaCard


class DetailGridScreen(QWidget):
    """Base shell for a Backdrop + hero + FocusGrid detail screen.

    Subclasses must override _item_key, _item_progress, _item_title,
    _item_subtitle, _item_cover_url, _item_progress_ids. _item_media_type
    has a "book" default and is optional to override.
    """

    item_activated = pyqtSignal(object)
    finished_changed = pyqtSignal(str, float, float, bool, str)
    back_requested = pyqtSignal()

    def __init__(self, cover_cache: CoverCache | None = None, parent=None) -> None:
        super().__init__(parent)
        self._cover_cache = cover_cache
        self._items: list[Any] = []
        self._progress: dict = {}
        self._server_url = ""
        self._token = ""
        self._dom_colors: dict[str, QColor] = {}
        # Index _populate() last auto-focused, so _refresh_progress() can
        # tell whether the user has navigated away since -- see its
        # docstring for why re-focusing unconditionally is a bug.
        self._auto_focus_idx: int | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        self._hero_backdrop = HeroBackdrop(self)

        self._grid = FocusGrid(columns=5)
        self._grid.item_activated.connect(self._on_item_activated)
        self._grid.focus_changed.connect(self._on_grid_focus_changed)
        self._grid.long_press_activated.connect(self._on_grid_long_press)

        self._finish_popup = ConfirmPopup(self)
        self._finish_popup.confirmed.connect(self._on_finish_confirmed)
        self._finish_popup.cancelled.connect(self._on_finish_cancelled)
        self._pending_finish_index: int | None = None

        layout = QVBoxLayout(self)
        # Top margin pushes the grid below the hero band, applied here to
        # the outer QVBoxLayout directly (not inside a scroll area) so
        # content is clipped at the hero's bottom edge rather than scrolling
        # under it — unlike browse.py's rows_layout, which applies its
        # margin INSIDE a scroll area so content scrolls under a translucent
        # hero as the user scrolls — so the first row of cards doesn't start
        # already overlapping the hero's title/subtitle text.
        layout.setContentsMargins(0, HeroBackdrop.HERO_H, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._grid)
        # Explicit z-order: HeroBackdrop only manages stacking among its own
        # children (backdrop vs. hero overlay), not relative to external
        # siblings like _grid — see HeroBackdrop's class docstring.
        self._hero_backdrop.lower()

    def resizeEvent(self, event) -> None:
        self._hero_backdrop.setGeometry(self.rect())
        w, h = int(self.width() * 0.5), 180
        self._finish_popup.setGeometry((self.width() - w) // 2, (self.height() - h) // 2, w, h)
        self._finish_popup.update_scrim_geometry()
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

    def _item_progress_ids(self, item: Any) -> tuple[str, str | None]:
        """(item_id, episode_id) for the update_progress() API call --
        distinct from _item_key(), which is the progress-dict lookup key
        and (for podcast episodes specifically) holds a different value:
        _item_key returns the episode's own id, but update_progress needs
        the show's library-item id as item_id and the episode's id
        separately as episode_id."""
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
    ) -> None:
        self._items = items
        self._progress = progress
        self._server_url = server_url
        self._token = token
        self._hero_backdrop.set_title(title)
        self._finish_popup.hide()
        self._pending_finish_index = None

        self._grid.clear()
        for item in items:
            self._grid.add_item(self._make_card(item))

        if self._grid.item_count:
            idx = self._find_resume_index()
            self._grid.focus_item(idx)
            self._auto_focus_idx = idx
        else:
            # No items — clear whatever subtitle/backdrop a previously
            # populated (and now stale) series/playlist left behind on this
            # reused screen instance, rather than leaving it visible under
            # the new (correct) hero title.
            self._auto_focus_idx = None
            self._hero_backdrop.set_subtitle("")
            self._hero_backdrop.backdrop.set_expected_key("")
            self._hero_backdrop.backdrop.show_color(QColor(theme.SURFACE))

    def _refresh_progress(self, progress: dict) -> None:
        """Update progress bars/finished badges on the existing cards
        in place (see test_detail_grid_refresh_progress_updates_in_place_
        without_rebuild) without necessarily re-focusing.

        This is called once real progress data lands shortly after a fast,
        progress-less _populate() (e.g. show_loading() -> update_progress()
        for series/playlist detail screens, per app.py's "series_detail"/
        "playlist_detail" worker results). If the user has already
        navigated away from the index _populate() auto-focused in that
        gap, jumping back to the (now progress-aware) resume index would
        silently undo their navigation -- the same bug fixed in
        BrowseScreen.set_row_items() for its cache-then-network row
        refresh. Only re-focus if focus is still exactly where we last
        left it.
        """
        self._progress = progress
        for item, card in zip(self._items, self._grid._items, strict=True):
            fraction, finished = self._item_progress(item, progress)
            card.set_progress(fraction)
            card.set_finished(finished)
        if self._grid.item_count and self._grid.focused_index == self._auto_focus_idx:
            idx = self._find_resume_index()
            self._grid.focus_item(idx)
            self._auto_focus_idx = idx

    def _find_resume_index(self) -> int:
        for i, item in enumerate(self._items):
            _fraction, finished = self._item_progress(item, self._progress)
            if not finished:
                return i
        return 0

    def _on_grid_long_press(self, index: int) -> None:
        if not (0 <= index < len(self._items)):
            return
        item = self._items[index]
        _fraction, finished = self._item_progress(item, self._progress)
        self._pending_finish_index = index
        if finished:
            self._finish_popup.show_confirm(
                f"Mark '{self._item_title(item)}' as unfinished?",
                confirm_label="Mark Unfinished",
            )
        else:
            self._finish_popup.show_confirm(
                f"Mark '{self._item_title(item)}' as finished?",
                confirm_label="Mark Finished",
            )

    def _on_finish_confirmed(self) -> None:
        if self._pending_finish_index is not None:
            self._toggle_finished(self._pending_finish_index)
        self._pending_finish_index = None
        self._grid.setFocus()

    def _on_finish_cancelled(self) -> None:
        self._pending_finish_index = None
        self._grid.setFocus()

    def _toggle_finished(self, index: int) -> None:
        if not (0 <= index < len(self._items)):
            return
        item = self._items[index]
        key = self._item_key(item)
        prog: MediaProgress | None = self._progress.get(key)
        _fraction, finished = self._item_progress(item, self._progress)
        new_finished = not finished
        duration = item.duration
        if new_finished:
            current_time = duration
        elif prog is not None and prog.current_time < duration:
            current_time = prog.current_time
        else:
            current_time = 0.0
        item_id, episode_id = self._item_progress_ids(item)
        self.finished_changed.emit(item_id, current_time, duration, new_finished, episode_id or "")
        # Optimistic local update -- reflects immediately, no round trip wait.
        self._progress[key] = MediaProgress(
            libraryItemId=item_id, episodeId=episode_id,
            currentTime=current_time, duration=duration, isFinished=new_finished,
        )
        fraction, finished = self._item_progress(item, self._progress)
        self._grid._items[index].set_progress(fraction)
        self._grid._items[index].set_finished(finished)

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
        sub = self._item_subtitle(item)
        title = self._item_title(item)
        self._hero_backdrop.set_subtitle(f"{sub} · {title}" if sub else title)
        if self._cover_cache is None:
            return
        cover = self._item_cover_url(item, self._server_url, self._token)
        if not cover:
            return
        key = self._item_key(item)
        color = self._dom_colors.get(key)
        self._hero_backdrop.backdrop.set_expected_key(key)
        if color is not None:
            self._hero_backdrop.backdrop.show_color(color, key=key)
        self._cover_cache.fetch_backdrop(
            cover, self._token,
            lambda pm, k=key: self._hero_backdrop.backdrop.show_image(pm, key=k),
        )

    def focus_item_by_key(self, key: str) -> None:
        for i, item in enumerate(self._items):
            if self._item_key(item) == key:
                self._grid.focus_item(i)
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
