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
