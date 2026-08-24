"""Disk-backed cover art cache."""
from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, QUrl, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QImage, QLinearGradient, QPainter, QPixmap
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from sixpack.ui import theme


def dominant_color(pixmap: QPixmap) -> QColor:
    """Average colour of the image, via a 1x1 smooth downscale."""
    if pixmap.isNull():
        return QColor(theme.SURFACE_HIGH)
    small = pixmap.scaled(
        1, 1, Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    return QColor(small.toImage().pixel(0, 0))


def make_backdrop(pixmap: QPixmap, size: QSize) -> QPixmap:
    """Scale-to-fill, cheap box blur, darken, and apply a bottom scrim."""
    filled = pixmap.scaled(
        size, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    # Crop the overspill to exactly `size`.
    x = max(0, (filled.width() - size.width()) // 2)
    y = max(0, (filled.height() - size.height()) // 2)
    filled = filled.copy(x, y, size.width(), size.height())
    # Cheap blur: downscale then upscale smoothly. Measured empirically:
    # Qt's SmoothTransformation does not behave like a proper box/mipmap
    # filter here — downscaling in several ~2x steps (e.g. 1920x1080 ->
    # 960x540 -> 480x270 -> 240x135) leaves high-contrast detail (cover
    # title text especially) fully legible at every step, all the way down
    # to 240x135. Only a much smaller single-step target (~1/120th, e.g.
    # 16x9 for a 1920x1080 backdrop) actually destroys legibility and
    # produces a genuinely soft wash — confirmed visually across a range of
    # intermediate sizes (30x17 still shows ghosted letterforms; 16x9 does
    # not).
    target_w = max(1, size.width() // 120)
    target_h = max(1, size.height() // 120)
    small = filled.scaled(
        target_w, target_h,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    blurred = small.scaled(
        size, Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    painter = QPainter(blurred)
    # Darken.
    painter.fillRect(
        blurred.rect(),
        QColor(0, 0, 0, int(255 * theme.BACKDROP_DARKEN)),
    )
    # Bottom scrim so text/cards stay legible.
    grad = QLinearGradient(0, 0, 0, size.height())
    grad.setColorAt(0.0, QColor(theme.BACKDROP_SCRIM_TOP))
    grad.setColorAt(1.0, QColor(theme.BACKDROP_SCRIM_BOTTOM))
    painter.fillRect(blurred.rect(), QBrush(grad))
    painter.end()
    return blurred


_DEFAULT_CACHE_DIR = Path.home() / ".cache" / "sixpack" / "covers"
_MAX_ENTRIES = 1000
_NETWORK_TIMEOUT_MS = 15_000


def _cache_key_url(url: str) -> str:
    """`url` minus its `?token=...` query string. cover_url() builders
    embed the bearer token in the URL, and hashing the full URL as the
    cache key means every re-login (token rotation) invalidates every
    cached cover even though the underlying images haven't changed --
    strip it so the key is stable across a token rotation."""
    return url.split("?", 1)[0]


class _CacheReadSignals(QObject):
    """Lives on CoverCache (i.e. the GUI thread) so its `finished` signal
    auto-marshals a QThreadPool worker's result back to the GUI thread as
    a QueuedConnection -- Qt's own mechanism for this, no manual
    QMetaObject.invokeMethod needed."""

    finished = pyqtSignal(str, QImage)  # url, decoded image (null if unreadable)


class _CacheReadTask(QRunnable):
    """Reads and decodes a cached cover off the GUI thread. QImage (unlike
    QPixmap) is safe to construct/decode on a non-GUI thread; the result is
    converted to a QPixmap back on the GUI thread, in the `finished` slot."""

    def __init__(self, path: Path, url: str, signals: _CacheReadSignals) -> None:
        super().__init__()
        self._path = path
        self._url = url
        self._signals = signals

    def run(self) -> None:
        img = QImage()
        try:
            data = self._path.read_bytes()
        except OSError:
            self._signals.finished.emit(self._url, img)
            return
        img.loadFromData(data)
        self._signals.finished.emit(self._url, img)


class CoverCache(QObject):
    """
    Disk-backed cover art cache.

    fetch(url, token, callback) — a cache hit reads and decodes the file on
    a background thread (QThreadPool), delivering the callback once that
    completes; a cache miss makes a network request and the callback fires
    when the download completes. Concurrent fetch() calls for the same URL
    while a read or request is in flight are coalesced: only one disk read
    or HTTP request happens and all callbacks fire when it finishes.
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
        # Token per in-flight URL, kept only so a corrupt-cache-file
        # recovery (_on_cache_read's fallback to a real fetch) can retry
        # with the same auth token fetch() was originally called with.
        self._pending_tokens: dict[str, str] = {}
        self._read_signals = _CacheReadSignals(self)
        self._read_signals.finished.connect(self._on_cache_read)
        # A second, independent pending/signals pair for fetch_backdrop()'s
        # own on-disk cache of already-processed (blurred/scrimmed) backdrop
        # images -- a separate cache from the raw-cover one above, keyed by
        # the same URLs, so it needs its own coalescing dict to avoid
        # colliding with fetch()'s.
        self._backdrop_pending: dict[str, list[Callable[[QPixmap], None]]] = {}
        self._backdrop_read_signals = _CacheReadSignals(self)
        self._backdrop_read_signals.finished.connect(self._on_backdrop_cache_read)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch(self, url: str, token: str, callback: Callable[[QPixmap], None]) -> None:
        if url in self._pending:
            self._pending[url].append(callback)
            return

        path = self._cache_path(url)
        self._pending[url] = [callback]
        self._pending_tokens[url] = token
        if path.exists():
            task = _CacheReadTask(path, url, self._read_signals)
            QThreadPool.globalInstance().start(task)
        else:
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
        return self._cache_dir / hashlib.md5(_cache_key_url(url).encode()).hexdigest()

    def _backdrop_path(self, url: str) -> Path:
        key = "backdrop:" + _cache_key_url(url)
        return self._cache_dir / hashlib.md5(key.encode()).hexdigest()

    def _on_cache_read(self, url: str, image: QImage) -> None:
        callbacks = self._pending.pop(url, [])
        token = self._pending_tokens.pop(url, "")
        if not image.isNull():
            pix = QPixmap.fromImage(image)
            if not pix.isNull():
                for cb in callbacks:
                    cb(pix)
                return
        # Corrupt/unreadable cache entry -- delete and fall through to a
        # real fetch, restoring the callbacks that were waiting on it.
        self._cache_path(url).unlink(missing_ok=True)
        if callbacks:
            self._pending[url] = callbacks
            self._pending_tokens[url] = token
            self._start_fetch(url, token)

    def fetch_backdrop(self, url: str, token: str, callback: Callable[[QPixmap], None]) -> None:
        if url in self._backdrop_pending:
            self._backdrop_pending[url].append(callback)
            return

        bpath = self._backdrop_path(url)
        if bpath.exists():
            self._backdrop_pending[url] = [callback]
            task = _CacheReadTask(bpath, url, self._backdrop_read_signals)
            QThreadPool.globalInstance().start(task)
            return

        self._make_and_deliver_backdrop(url, token, callback)

    def _on_backdrop_cache_read(self, url: str, image: QImage) -> None:
        callbacks = self._backdrop_pending.pop(url, [])
        if not image.isNull():
            pix = QPixmap.fromImage(image)
            if not pix.isNull():
                for cb in callbacks:
                    cb(pix)
                return
        self._backdrop_path(url).unlink(missing_ok=True)
        for cb in callbacks:
            self._make_and_deliver_backdrop(url, "", cb)

    def _make_and_deliver_backdrop(
        self, url: str, token: str, callback: Callable[[QPixmap], None]
    ) -> None:
        bpath = self._backdrop_path(url)
        size = QSize(theme.BACKDROP_W, theme.BACKDROP_H)

        def _process(raw: QPixmap) -> None:
            out = make_backdrop(raw, size)
            # Backdrops are blurred, intentionally lossy ambient art — JPEG
            # at quality 85 is visually indistinguishable from the PNG this
            # used to save as, but roughly an order of magnitude smaller
            # (a ~500KB PNG becomes tens of KB), which matters a lot given
            # these entries share the same _MAX_ENTRIES disk-cache cap as
            # much smaller raw cover thumbnails. Like raw covers (see
            # `_cache_path`), the cache filename has no extension — both
            # `QPixmap.save`/`.load` and Qt's image-format sniffing work
            # from content, not the path, so no filename change is needed.
            out.save(str(bpath), "JPG", 85)
            callback(out)

        # Reuse the raw-cover fetch (caches raw on disk, coalesces in-flight).
        self.fetch(url, token, _process)

    def _start_fetch(self, url: str, token: str) -> None:
        request = QNetworkRequest(QUrl(url))
        if token:
            request.setRawHeader(b"Authorization", f"Bearer {token}".encode())
        request.setTransferTimeout(_NETWORK_TIMEOUT_MS)
        reply = self._nam.get(request)
        reply.finished.connect(lambda r=reply, u=url: self._on_reply(r, u))

    def _on_reply(self, reply: QNetworkReply, url: str) -> None:
        callbacks = self._pending.pop(url, [])
        self._pending_tokens.pop(url, None)
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
            entries = list(self._cache_dir.iterdir())
        except OSError:
            return
        # Cheap unconditional listing first -- the expensive part (a
        # stat() per file, to sort by mtime) only runs when actually over
        # the cap, not on every single completed fetch.
        if len(entries) <= self._max_entries:
            return
        try:
            files = sorted(entries, key=lambda f: f.stat().st_mtime)
        except OSError:
            return
        while len(files) > self._max_entries:
            try:
                files.pop(0).unlink()
            except OSError:
                pass
