"""Disk-backed cover art cache."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QObject, QUrl
from PyQt6.QtGui import QPixmap
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

_DEFAULT_CACHE_DIR = Path.home() / ".cache" / "sixpack" / "covers"
_MAX_ENTRIES = 1000


class CoverCache(QObject):
    """
    Disk-backed cover art cache.

    fetch(url, token, callback) — if the image is already on disk the
    callback fires synchronously; otherwise a network request is made and
    the callback fires when the download completes.  Concurrent fetch()
    calls for the same URL while a request is in flight are coalesced: only
    one HTTP request is made and all callbacks fire when it finishes.
    """

    def __init__(
        self,
        cache_dir: Path | None = None,
        max_entries: int = _MAX_ENTRIES,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._cache_dir = cache_dir or _DEFAULT_CACHE_DIR
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._max_entries = max_entries
        self._nam = QNetworkAccessManager(self)
        self._pending: dict[str, list[Callable[[QPixmap], None]]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch(self, url: str, token: str, callback: Callable[[QPixmap], None]) -> None:
        path = self._cache_path(url)
        if path.exists():
            pix = QPixmap()
            if pix.load(str(path)) and not pix.isNull():
                callback(pix)
                return
            path.unlink(missing_ok=True)  # corrupt — delete and re-fetch

        if url in self._pending:
            self._pending[url].append(callback)
            return

        self._pending[url] = [callback]
        self._start_fetch(url, token)

    def clear(self) -> None:
        for f in self._cache_dir.iterdir():
            try:
                f.unlink()
            except OSError:
                pass

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _cache_path(self, url: str) -> Path:
        return self._cache_dir / hashlib.md5(url.encode()).hexdigest()

    def _start_fetch(self, url: str, token: str) -> None:
        request = QNetworkRequest(QUrl(url))
        if token:
            request.setRawHeader(b"Authorization", f"Bearer {token}".encode())
        reply = self._nam.get(request)
        reply.finished.connect(lambda r=reply, u=url: self._on_reply(r, u))

    def _on_reply(self, reply: QNetworkReply, url: str) -> None:
        callbacks = self._pending.pop(url, [])
        if reply.error() == QNetworkReply.NetworkError.NoError:
            data = reply.readAll()
            path = self._cache_path(url)
            path.write_bytes(bytes(data))
            pix = QPixmap()
            pix.loadFromData(data)
            if not pix.isNull():
                for cb in callbacks:
                    cb(pix)
            self._evict_if_needed()
        reply.deleteLater()

    def _evict_if_needed(self) -> None:
        try:
            files = sorted(
                self._cache_dir.iterdir(),
                key=lambda f: f.stat().st_mtime,
            )
        except OSError:
            return
        while len(files) > self._max_entries:
            try:
                files.pop(0).unlink()
            except OSError:
                pass
