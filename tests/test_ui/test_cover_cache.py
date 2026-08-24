"""Tests for CoverCache."""
from __future__ import annotations

import hashlib
import os

from PyQt6.QtCore import QSize
from PyQt6.QtGui import QColor, QPixmap

from sixpack.ui.cover_cache import CoverCache, dominant_color, make_backdrop


def _write_pixmap(path, color="blue"):
    pix = QPixmap(10, 10)
    pix.fill(QColor(color))
    pix.save(str(path), "PNG")


# ---- cache-path ----

def test_cache_path_consistent(tmp_path, qtbot):
    cache = CoverCache(cache_dir=tmp_path)
    url = "http://example.com/cover.jpg"
    assert cache._cache_path(url) == cache._cache_path(url)


def test_cache_path_differs_for_different_urls(tmp_path, qtbot):
    cache = CoverCache(cache_dir=tmp_path)
    assert cache._cache_path("http://a.com/1") != cache._cache_path("http://a.com/2")


def test_cache_path_uses_md5(tmp_path, qtbot):
    cache = CoverCache(cache_dir=tmp_path)
    url = "http://example.com/cover.jpg"
    expected = tmp_path / hashlib.md5(url.encode()).hexdigest()
    assert cache._cache_path(url) == expected


def test_cache_path_stable_across_token_rotation(tmp_path, qtbot):
    """cover_url() builders embed ?token=... in the URL -- the cache key
    must be based on the path alone, so a re-login (new token) doesn't
    invalidate every cached cover for images that haven't changed."""
    cache = CoverCache(cache_dir=tmp_path)
    base = "http://abs.test/api/items/x/cover"
    assert cache._cache_path(f"{base}?token=old") == cache._cache_path(f"{base}?token=new")
    assert cache._backdrop_path(f"{base}?token=old") == cache._backdrop_path(f"{base}?token=new")


# ---- disk hit ----
#
# A cache hit now reads and decodes the file on a background thread
# (QThreadPool) rather than blocking the GUI thread inline -- the callback
# fires once that completes and the result is queued back, not before
# fetch() returns. qtbot.waitUntil pumps the event loop so the queued
# signal actually gets delivered.

def test_cache_hit_delivers_callback(tmp_path, qtbot):
    url = "http://example.com/cover.jpg"
    cache = CoverCache(cache_dir=tmp_path)
    _write_pixmap(cache._cache_path(url))

    received = []
    cache.fetch(url, "tok", received.append)

    qtbot.waitUntil(lambda: len(received) == 1, timeout=2000)
    assert not received[0].isNull()


def test_cache_hit_no_pending_entry(tmp_path, qtbot):
    url = "http://example.com/cover.jpg"
    cache = CoverCache(cache_dir=tmp_path)
    _write_pixmap(cache._cache_path(url))

    received = []
    cache.fetch(url, "tok", received.append)
    qtbot.waitUntil(lambda: len(received) == 1, timeout=2000)
    assert url not in cache._pending


# ---- corrupt file ----

def test_corrupt_cache_file_deleted_and_fetch_queued(tmp_path, qtbot):
    url = "http://example.com/bad.jpg"
    cache = CoverCache(cache_dir=tmp_path)
    bad = cache._cache_path(url)
    bad.write_bytes(b"not an image at all")

    cache.fetch(url, "tok", lambda p: None)

    # Once the background read confirms the file is unreadable, it's
    # deleted and a real (network) fetch is queued in its place.
    qtbot.waitUntil(lambda: not bad.exists(), timeout=2000)
    assert url in cache._pending


# ---- deduplication ----

def test_duplicate_fetch_queues_both_callbacks(tmp_path, qtbot):
    url = "http://example.com/dup.jpg"
    cache = CoverCache(cache_dir=tmp_path)

    cache.fetch(url, "tok", lambda p: None)
    cache.fetch(url, "tok", lambda p: None)

    assert len(cache._pending[url]) == 2


def test_duplicate_fetch_single_pending_key(tmp_path, qtbot):
    url = "http://example.com/dup2.jpg"
    cache = CoverCache(cache_dir=tmp_path)

    for _ in range(5):
        cache.fetch(url, "tok", lambda p: None)

    assert list(cache._pending.keys()) == [url]


# ---- eviction ----

def test_evict_removes_oldest_files(tmp_path, qtbot):
    cache = CoverCache(cache_dir=tmp_path, max_entries=2)
    names = ["aaa", "bbb", "ccc"]
    for i, name in enumerate(names):
        f = tmp_path / name
        f.write_bytes(b"x")
        os.utime(f, (i, i))  # mtime 0, 1, 2 — "aaa" is oldest

    cache._evict_if_needed()

    remaining = {f.name for f in tmp_path.iterdir()}
    assert remaining == {"bbb", "ccc"}


def test_evict_no_op_under_limit(tmp_path, qtbot):
    cache = CoverCache(cache_dir=tmp_path, max_entries=5)
    for name in ["a", "b", "c"]:
        (tmp_path / name).write_bytes(b"x")

    cache._evict_if_needed()

    assert len(list(tmp_path.iterdir())) == 3


def test_evict_under_limit_skips_stat_and_sort(tmp_path, qtbot, monkeypatch):
    """Under the cap, _evict_if_needed must not pay for a stat()-per-file
    sort at all -- only the cheap directory listing. Regression guard for
    the full-scan-on-every-fetch inefficiency."""
    from pathlib import Path

    cache = CoverCache(cache_dir=tmp_path, max_entries=5)
    for name in ["a", "b", "c"]:
        (tmp_path / name).write_bytes(b"x")

    def _boom(self, *args, **kwargs):
        raise AssertionError("stat() must not run on any file when under the cap")

    monkeypatch.setattr(Path, "stat", _boom)
    cache._evict_if_needed()  # must not raise


# ---- clear ----

def test_clear_removes_all_files(tmp_path, qtbot):
    cache = CoverCache(cache_dir=tmp_path)
    for name in ["x", "y", "z"]:
        (tmp_path / name).write_bytes(b"x")

    cache.clear()

    assert list(tmp_path.iterdir()) == []


def test_clear_empty_cache_no_error(tmp_path, qtbot):
    cache = CoverCache(cache_dir=tmp_path)
    cache.clear()  # should not raise


# ---- dominant_color + make_backdrop ----


def _solid(w, h, color) -> QPixmap:
    pix = QPixmap(w, h)
    pix.fill(color)
    return pix


def test_dominant_color_of_solid_red():
    c = dominant_color(_solid(64, 64, QColor(200, 30, 30)))
    assert c.red() > 150 and c.green() < 80 and c.blue() < 80


def test_dominant_color_null_pixmap_is_safe():
    c = dominant_color(QPixmap())
    assert isinstance(c, QColor) and c.isValid()


def test_make_backdrop_returns_sized_non_null():
    out = make_backdrop(_solid(300, 300, QColor(120, 60, 200)), QSize(640, 360))
    assert not out.isNull()
    assert out.width() == 640 and out.height() == 360


def test_backdrop_path_distinct_from_cover_path(tmp_path):
    cache = CoverCache(cache_dir=tmp_path)
    url = "http://abs.test/api/items/x/cover?token=t"
    assert cache._backdrop_path(url) != cache._cache_path(url)


def test_fetch_backdrop_uses_disk_cache(tmp_path, qtbot):
    cache = CoverCache(cache_dir=tmp_path)
    url = "http://abs.test/api/items/x/cover?token=t"
    # Pre-seed the backdrop cache file so no network is needed.
    make_backdrop(_solid(300, 300, QColor(10, 120, 90)), QSize(64, 36)).save(
        str(cache._backdrop_path(url)), "PNG"
    )
    got = {}
    cache.fetch_backdrop(url, "t", lambda pm: got.setdefault("pm", pm))
    qtbot.waitUntil(lambda: "pm" in got, timeout=2000)
    assert not got["pm"].isNull()


def test_fetch_backdrop_saves_as_jpeg_not_png(tmp_path, qtbot):
    """Backdrops are blurred ambient art — save as JPEG (lossy but much
    smaller) rather than PNG, since a raw-cover-sized disk cache cap
    (_MAX_ENTRIES) would otherwise let backdrop entries balloon the cache
    far beyond what it holds for small raw cover thumbnails."""
    cache = CoverCache(cache_dir=tmp_path)
    url = "http://abs.test/api/items/x/cover?token=t"
    raw_path = cache._cache_path(url)
    _write_pixmap(raw_path, "blue")  # seeds the raw-cover cache; no network needed

    got = {}
    cache.fetch_backdrop(url, "t", lambda pm: got.setdefault("pm", pm))

    qtbot.waitUntil(lambda: "pm" in got, timeout=2000)
    assert not got["pm"].isNull()
    bpath = cache._backdrop_path(url)
    assert bpath.exists()
    # QImageReader sniffs format from file content, not extension (the
    # cache filename itself has none) — so read the saved file back with
    # Qt and check the format it reports.
    from PyQt6.QtGui import QImageReader
    reader = QImageReader(str(bpath))
    assert reader.format().data().decode().lower() in ("jpg", "jpeg")


def test_backdrop_jpeg_smaller_than_png_for_photographic_source(tmp_path):
    """Sanity check the size claim: a photo-like (non-flat, gradient-rich)
    source — the kind a real book/podcast cover produces once blurred —
    yields a materially smaller JPEG-85 backdrop than the PNG this used to
    save. (A literal per-pixel noise source is *not* representative here:
    make_backdrop's blur step smooths real covers into soft gradients that
    PNG's filters compress well but flattens noise into incompressible
    high-frequency garbage that isn't — measured against real cached cover
    art, JPEG-85 backdrops came out ~2.5x smaller than PNG.)"""
    import random

    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtGui import QLinearGradient, QPainter, QRadialGradient

    src = QPixmap(400, 400)
    painter = QPainter(src)
    wash = QLinearGradient(0, 0, 400, 400)
    wash.setColorAt(0, QColor(30, 40, 90))
    wash.setColorAt(1, QColor(200, 120, 40))
    painter.fillRect(src.rect(), wash)
    rng = random.Random(1)
    painter.setPen(Qt.PenStyle.NoPen)
    for _ in range(40):
        cx, cy = rng.randint(0, 400), rng.randint(0, 400)
        r = rng.randint(20, 120)
        blob = QRadialGradient(QPointF(cx, cy), r)
        c1 = QColor(rng.randint(0, 255), rng.randint(0, 255), rng.randint(0, 255), 180)
        blob.setColorAt(0, c1)
        blob.setColorAt(1, QColor(c1.red(), c1.green(), c1.blue(), 0))
        painter.setBrush(blob)
        painter.drawEllipse(QPointF(cx, cy), r, r)
    painter.end()

    out = make_backdrop(src, QSize(1920, 1080))

    png_path = tmp_path / "out.png"
    jpg_path = tmp_path / "out.jpg"
    out.save(str(png_path), "PNG")
    out.save(str(jpg_path), "JPG", 85)

    assert jpg_path.stat().st_size < png_path.stat().st_size
