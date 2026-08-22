"""Podcast detail screen — episode grid with progress indicators."""
from __future__ import annotations

from sixpack.api.models import LibraryItem, MediaProgress, PodcastEpisode
from sixpack.ui.cover_cache import CoverCache
from sixpack.ui.screens.detail_grid import DetailGridScreen


class PodcastDetailScreen(DetailGridScreen):
    """
    Shows the episode grid for a podcast show. Emits item_activated(episode)
    — the caller (app.py) decides whether to route through chapter
    selection or play directly. Emits back_requested() on Back.
    """

    def __init__(self, cover_cache: CoverCache | None = None, parent=None) -> None:
        super().__init__(cover_cache=cover_cache, parent=parent)
        self._show: LibraryItem | None = None

    def _item_key(self, item: PodcastEpisode) -> str:
        return item.id

    def _item_progress(self, item: PodcastEpisode, progress: dict) -> tuple[float, bool]:
        prog: MediaProgress | None = progress.get(item.id)
        if prog is None or not item.duration:
            return 0.0, False
        finished = bool(prog.is_finished)
        fraction = 0.0 if finished else max(0.0, min(1.0, prog.current_time / item.duration))
        return fraction, finished

    def _item_title(self, item: PodcastEpisode) -> str:
        return item.title

    def _item_subtitle(self, item: PodcastEpisode) -> str:
        return ""

    def _item_cover_url(self, item: PodcastEpisode, server_url: str, token: str) -> str | None:
        # Episodes have no cover of their own — every card uses the show's.
        if self._show is None:
            return None
        return self._show.cover_url(server_url, token)

    def _item_media_type(self, item: PodcastEpisode) -> str:
        return "podcast"

    def show_loading(self, show: LibraryItem, server_url: str = "", token: str = "") -> None:
        self._show = show
        self._populate(show.title, show.media.episodes, {}, server_url, token)

    def load(
        self,
        show: LibraryItem,
        progress: dict[str, MediaProgress],
        server_url: str = "",
        token: str = "",
    ) -> None:
        self._show = show
        self._populate(show.title, show.media.episodes, progress, server_url, token)

    def update_progress(self, progress: dict[str, MediaProgress]) -> None:
        self._refresh_progress(progress)
