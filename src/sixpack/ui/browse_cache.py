"""Disk-backed cache for library/browse catalog data, keyed by server URL.

This is a stale-while-revalidate cache, not a substitute for the network
fetch: callers read it synchronously for an instant first paint, then still
fetch fresh data over the network as normal and call save_* to keep the
cache current. No expiry — every load re-validates against the network
regardless of how old the cache is.
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from sixpack.api.models import Library, LibraryItem, Playlist, Series
from sixpack.ui.screens.browse import RowType

logger = logging.getLogger(__name__)

_DEFAULT_CACHE_DIR = Path.home() / ".cache" / "sixpack" / "browse"

_ROW_MODELS = {
    RowType.CONTINUE_LISTENING: LibraryItem,
    RowType.RECENTLY_ADDED: LibraryItem,
    RowType.SERIES: Series,
    RowType.PLAYLISTS: Playlist,
}


class BrowseCache:
    def __init__(self, cache_dir: Path | None = None) -> None:
        self._cache_dir = cache_dir or _DEFAULT_CACHE_DIR
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Libraries (the filtered list shown in the sidebar)
    # ------------------------------------------------------------------

    def save_libraries(self, server_url: str, libraries: list[Library]) -> None:
        self._write(
            self._path(server_url, "libraries"),
            [lib.model_dump(mode="json") for lib in libraries],
        )

    def load_libraries(self, server_url: str) -> list[Library] | None:
        data = self._read(self._path(server_url, "libraries"))
        if data is None:
            return None
        try:
            return [Library.model_validate(item) for item in data]
        except Exception as exc:
            logger.warning("Discarding corrupt libraries cache for %s: %s", server_url, exc)
            return None

    # ------------------------------------------------------------------
    # Browse content (the four rows for one library)
    # ------------------------------------------------------------------

    def save_browse_content(
        self, server_url: str, library_id: str, rows: dict[RowType, list[Any]]
    ) -> None:
        payload = {
            row_type.value: [item.model_dump(mode="json") for item in items]
            for row_type, items in rows.items()
        }
        self._write(self._path(server_url, library_id), payload)

    def load_browse_content(
        self, server_url: str, library_id: str
    ) -> dict[RowType, list[Any]] | None:
        data = self._read(self._path(server_url, library_id))
        if data is None:
            return None
        try:
            return {
                row_type: [
                    _ROW_MODELS[row_type].model_validate(item)
                    for item in data.get(row_type.value, [])
                ]
                for row_type in RowType
            }
        except Exception as exc:
            logger.warning(
                "Discarding corrupt browse-content cache for %s/%s: %s",
                server_url, library_id, exc,
            )
            return None

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _path(self, server_url: str, key: str) -> Path:
        digest = hashlib.md5(f"{server_url}:{key}".encode()).hexdigest()
        return self._cache_dir / f"{digest}.json"

    def _write(self, path: Path, data: Any) -> None:
        try:
            path.write_text(json.dumps(data))
        except OSError as exc:
            logger.warning("Failed to write browse cache %s: %s", path, exc)

    def _read(self, path: Path) -> Any | None:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            logger.warning("Failed to read browse cache %s: %s", path, exc)
            return None
