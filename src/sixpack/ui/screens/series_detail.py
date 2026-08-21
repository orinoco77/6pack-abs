"""Series detail screen — episode grid with progress indicators."""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal

from sixpack.api.models import MediaProgress, Series, SeriesBook
from sixpack.ui.cover_cache import CoverCache
from sixpack.ui.screens.detail_grid import DetailGridScreen


class SeriesDetailScreen(DetailGridScreen):
    """
    Shows the episode grid for a series. Emits episode_activated(book) —
    the caller (app.py) decides whether to play directly or route through
    chapter selection, exactly as before this rewrite. Emits
    back_requested() on Back.
    """

    episode_activated = pyqtSignal(object)  # SeriesBook

    def __init__(self, cover_cache: CoverCache | None = None, parent=None) -> None:
        super().__init__(cover_cache=cover_cache, parent=parent)
        self.item_activated.connect(self.episode_activated)

    def _item_key(self, item: SeriesBook) -> str:
        return item.id

    def _item_progress(self, item: SeriesBook, progress: dict) -> tuple[float, bool]:
        prog: MediaProgress | None = progress.get(item.id)
        if prog is None or not item.duration:
            return 0.0, False
        finished = bool(prog.is_finished)
        fraction = 0.0 if finished else max(0.0, min(1.0, prog.current_time / item.duration))
        return fraction, finished

    def _item_title(self, item: SeriesBook) -> str:
        return item.title

    def _item_subtitle(self, item: SeriesBook) -> str:
        return f"Episode {item.sequence}" if item.sequence else ""

    def _item_cover_url(self, item: SeriesBook, server_url: str, token: str) -> str | None:
        return item.cover_url(server_url, token)

    def show_loading(self, series: Series, server_url: str = "", token: str = "") -> None:
        self._populate(series.name, series.sorted_books, {}, server_url, token, loading=True)

    def load(
        self,
        series: Series,
        progress: dict[str, MediaProgress],
        server_url: str = "",
        token: str = "",
    ) -> None:
        self._populate(series.name, series.sorted_books, progress, server_url, token)

    def update_progress(self, progress: dict[str, MediaProgress]) -> None:
        self._refresh_progress(progress)
