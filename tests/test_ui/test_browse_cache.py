"""Tests for BrowseCache."""
from __future__ import annotations

from sixpack.api.models import Library, LibraryItem, LibraryItemMedia, Playlist, Series, SeriesBook
from sixpack.ui.browse_cache import BrowseCache
from sixpack.ui.screens.browse import RowType


def _lib(lib_id="lib1", name="Audiobooks"):
    return Library(id=lib_id, name=name, mediaType="book")


def _item(item_id="i1", title="Book 1"):
    return LibraryItem(
        id=item_id, libraryId="lib1", mediaType="book",
        media=LibraryItemMedia(metadata={"title": title, "authorName": "Author"}),
    )


def _series(series_id="s1", name="A Series"):
    book = SeriesBook(
        id="b1", libraryId="lib1",
        media=LibraryItemMedia(metadata={"title": "Book 1"}), sequence="1",
    )
    return Series(id=series_id, name=name, books=[book])


def _playlist(pid="p1", name="A Playlist"):
    li = _item("pi1", "Playlist Track")
    from sixpack.api.models import PlaylistItem
    return Playlist(id=pid, name=name, items=[PlaylistItem(libraryItemId=li.id, libraryItem=li)])


# ---- libraries ----

def test_load_libraries_returns_none_when_no_cache(tmp_path):
    cache = BrowseCache(cache_dir=tmp_path)
    assert cache.load_libraries("http://s") is None


def test_save_then_load_libraries_round_trips(tmp_path):
    cache = BrowseCache(cache_dir=tmp_path)
    libs = [_lib("lib1", "Audiobooks"), _lib("lib2", "Podcasts")]
    cache.save_libraries("http://s", libs)

    loaded = cache.load_libraries("http://s")

    assert loaded is not None
    assert [lib.id for lib in loaded] == ["lib1", "lib2"]
    assert [lib.name for lib in loaded] == ["Audiobooks", "Podcasts"]


def test_libraries_are_keyed_by_server_url(tmp_path):
    cache = BrowseCache(cache_dir=tmp_path)
    cache.save_libraries("http://server-a", [_lib("lib1", "A")])
    cache.save_libraries("http://server-b", [_lib("lib2", "B")])

    assert [lib.id for lib in cache.load_libraries("http://server-a")] == ["lib1"]
    assert [lib.id for lib in cache.load_libraries("http://server-b")] == ["lib2"]


def test_load_libraries_returns_none_on_corrupt_cache(tmp_path):
    cache = BrowseCache(cache_dir=tmp_path)
    cache.save_libraries("http://s", [_lib()])
    cache._path("http://s", "libraries").write_text("not valid json{{{")

    assert cache.load_libraries("http://s") is None


# ---- browse content (per-library rows) ----

def test_load_browse_content_returns_none_when_no_cache(tmp_path):
    cache = BrowseCache(cache_dir=tmp_path)
    assert cache.load_browse_content("http://s", "lib1") is None


def test_save_then_load_browse_content_round_trips_all_row_types(tmp_path):
    cache = BrowseCache(cache_dir=tmp_path)
    rows = {
        RowType.CONTINUE_LISTENING: [_item("i1", "CL Book")],
        RowType.RECENTLY_ADDED: [_item("i2", "RA Book")],
        RowType.SERIES: [_series("s1", "A Series")],
        RowType.ALL_BOOKS: [_item("i3", "AB Book")],
        RowType.PLAYLISTS: [_playlist("p1", "A Playlist")],
    }
    cache.save_browse_content("http://s", "lib1", rows)

    loaded = cache.load_browse_content("http://s", "lib1")

    assert loaded is not None
    assert [i.title for i in loaded[RowType.CONTINUE_LISTENING]] == ["CL Book"]
    assert [i.title for i in loaded[RowType.RECENTLY_ADDED]] == ["RA Book"]
    assert [s.name for s in loaded[RowType.SERIES]] == ["A Series"]
    assert [i.title for i in loaded[RowType.ALL_BOOKS]] == ["AB Book"]
    assert [p.name for p in loaded[RowType.PLAYLISTS]] == ["A Playlist"]
    assert isinstance(loaded[RowType.SERIES][0], Series)
    assert isinstance(loaded[RowType.PLAYLISTS][0], Playlist)
    assert isinstance(loaded[RowType.CONTINUE_LISTENING][0], LibraryItem)
    assert isinstance(loaded[RowType.ALL_BOOKS][0], LibraryItem)


def test_browse_content_is_keyed_by_server_and_library(tmp_path):
    cache = BrowseCache(cache_dir=tmp_path)
    cache.save_browse_content(
        "http://s", "lib1", {RowType.RECENTLY_ADDED: [_item("i1", "Lib1 Book")]}
    )
    cache.save_browse_content(
        "http://s", "lib2", {RowType.RECENTLY_ADDED: [_item("i2", "Lib2 Book")]}
    )

    lib1_rows = cache.load_browse_content("http://s", "lib1")
    lib2_rows = cache.load_browse_content("http://s", "lib2")

    assert [i.title for i in lib1_rows[RowType.RECENTLY_ADDED]] == ["Lib1 Book"]
    assert [i.title for i in lib2_rows[RowType.RECENTLY_ADDED]] == ["Lib2 Book"]


def test_load_browse_content_returns_none_on_corrupt_cache(tmp_path):
    cache = BrowseCache(cache_dir=tmp_path)
    cache.save_browse_content("http://s", "lib1", {RowType.RECENTLY_ADDED: [_item()]})
    cache._path("http://s", "lib1").write_text("not valid json{{{")

    assert cache.load_browse_content("http://s", "lib1") is None


def test_missing_row_type_in_cached_payload_defaults_to_empty_list(tmp_path):
    """A cache file saved before a new RowType existed (or a partial write)
    should still load — missing row types default to empty, not a crash."""
    cache = BrowseCache(cache_dir=tmp_path)
    cache.save_browse_content("http://s", "lib1", {RowType.RECENTLY_ADDED: [_item()]})

    loaded = cache.load_browse_content("http://s", "lib1")

    assert loaded[RowType.SERIES] == []
    assert loaded[RowType.PLAYLISTS] == []
