"""Playlist detail screen — item grid with progress indicators."""
from __future__ import annotations

from sixpack.api.models import MediaProgress, Playlist, PlaylistItem
from sixpack.ui.cover_cache import CoverCache
from sixpack.ui.screens.detail_grid import DetailGridScreen


class PlaylistDetailScreen(DetailGridScreen):
    """
    Shows the item grid for a playlist. Emits item_activated(item) —
    the caller (app.py) decides whether to play directly or route through
    chapter selection. Emits back_requested() on Back.
    """

    def __init__(self, cover_cache: CoverCache | None = None, parent=None) -> None:
        super().__init__(cover_cache=cover_cache, parent=parent)

    def _item_key(self, item: PlaylistItem) -> str:
        return item.library_item_id

    def _item_progress(self, item: PlaylistItem, progress: dict) -> tuple[float, bool]:
        prog: MediaProgress | None = progress.get(item.library_item_id)
        if prog is None or not item.duration:
            return 0.0, False
        finished = bool(prog.is_finished)
        fraction = 0.0 if finished else max(0.0, min(1.0, prog.current_time / item.duration))
        return fraction, finished

    def _item_progress_ids(self, item: PlaylistItem) -> tuple[str, str | None]:
        return item.library_item_id, item.episode_id

    def _item_title(self, item: PlaylistItem) -> str:
        return item.title

    def _item_subtitle(self, item: PlaylistItem) -> str:
        return ""

    def _item_cover_url(self, item: PlaylistItem, server_url: str, token: str) -> str | None:
        return item.cover_url(server_url, token)

    def _item_media_type(self, item: PlaylistItem) -> str:
        return item.media_type

    def show_loading(self, playlist: Playlist, server_url: str = "", token: str = "") -> None:
        self._populate(playlist.name, playlist.items, {}, server_url, token)

    def load(
        self,
        playlist: Playlist,
        progress: dict[str, MediaProgress],
        server_url: str = "",
        token: str = "",
    ) -> None:
        self._populate(playlist.name, playlist.items, progress, server_url, token)

    def update_progress(self, progress: dict[str, MediaProgress]) -> None:
        self._refresh_progress(progress)
