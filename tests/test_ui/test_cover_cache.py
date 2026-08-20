"""Tests for CoverCache."""
from __future__ import annotations

import hashlib
import os

import pytest
from PyQt6.QtGui import QColor, QPixmap

from sixpack.ui.cover_cache import CoverCache


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


# ---- disk hit ----

def test_cache_hit_fires_callback_synchronously(tmp_path, qtbot):
    url = "http://example.com/cover.jpg"
    cache = CoverCache(cache_dir=tmp_path)
    _write_pixmap(cache._cache_path(url))

    received = []
    cache.fetch(url, "tok", received.append)

    assert len(received) == 1
    assert not received[0].isNull()


def test_cache_hit_no_pending_entry(tmp_path, qtbot):
    url = "http://example.com/cover.jpg"
    cache = CoverCache(cache_dir=tmp_path)
    _write_pixmap(cache._cache_path(url))

    cache.fetch(url, "tok", lambda p: None)
    assert url not in cache._pending


# ---- corrupt file ----

def test_corrupt_cache_file_deleted_and_fetch_queued(tmp_path, qtbot):
    url = "http://example.com/bad.jpg"
    cache = CoverCache(cache_dir=tmp_path)
    bad = cache._cache_path(url)
    bad.write_bytes(b"not an image at all")

    cache.fetch(url, "tok", lambda p: None)

    assert not bad.exists()
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

from PyQt6.QtCore import QSize  # noqa: E402
from PyQt6.QtGui import QColor, QPixmap  # noqa: E402

from sixpack.ui.cover_cache import CoverCache, dominant_color, make_backdrop  # noqa: E402


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
    assert "pm" in got and not got["pm"].isNull()
