"""Tests for Playlist models and API methods."""
from __future__ import annotations

import pytest
import respx
import httpx

from sixpack.api.models import Playlist, PlaylistItem, LibraryItem, LibraryItemMedia
from sixpack.api.client import ABSClient


def _make_item(library_item_id="li1", title="Test Book", duration=3600.0, library_id="lib1"):
    """Build a PlaylistItem matching the real Audiobookshelf shape.

    Playlist entries embed the full library item under ``libraryItem``; ``media``
    is nested inside that, not on the entry itself.
    """
    library_item = LibraryItem(
        id=library_item_id,
        libraryId=library_id,
        mediaType="book",
        media=LibraryItemMedia(metadata={"title": title}, duration=duration),
    )
    return PlaylistItem(libraryItemId=library_item_id, libraryItem=library_item)


# ---- PlaylistItem ----

def test_playlist_item_fields():
    item = _make_item(library_item_id="li1", title="Test Book", duration=3600.0)
    assert item.library_item_id == "li1"
    assert item.title == "Test Book"
    assert item.duration == 3600.0
    assert item.media.title == "Test Book"


def test_playlist_item_cover_url(server_url, auth_token):
    item = _make_item(library_item_id="li1")
    url = item.cover_url(server_url, auth_token)
    assert url == f"{server_url}/api/items/li1/cover?token={auth_token}"


# ---- Playlist ----

def test_playlist_fields():
    item = _make_item(library_item_id="li1", title="Book 1", duration=1800.0)
    playlist = Playlist(
        id="p1",
        name="My Favorites",
        description="Best audiobooks",
        libraryId="lib1",  # Use alias
        userId="u1",  # Use alias
        items=[item],
    )
    assert playlist.id == "p1"
    assert playlist.name == "My Favorites"
    assert playlist.description == "Best audiobooks"
    assert playlist.item_count == 1


def test_playlist_empty():
    playlist = Playlist(id="p1", name="Empty Playlist")
    assert playlist.item_count == 0
    assert playlist.total_duration == 0.0
    assert playlist.cover_url("http://x", "tok") is None


def test_playlist_total_duration():
    item1 = _make_item(library_item_id="li1", duration=1800.0)
    item2 = _make_item(library_item_id="li2", duration=2400.0)
    playlist = Playlist(id="p1", name="Test", items=[item1, item2])
    assert playlist.total_duration == 4200.0


def test_playlist_cover_url(server_url, auth_token):
    item = _make_item(library_item_id="li1")
    playlist = Playlist(id="p1", name="Test", items=[item])
    url = playlist.cover_url(server_url, auth_token)
    assert url is not None
    assert "li1" in url


def test_playlist_from_api_response():
    """Test parsing a typical Audiobookshelf playlist response."""
    data = {
        "id": "pl_123",
        "name": "Sci-Fi Collection",
        "description": "My favorite sci-fi audiobooks",
        "libraryId": "lib1",
        "userId": "u1",
        "items": [
            {
                "libraryItemId": "li_1",
                "libraryItem": {
                    "id": "li_1",
                    "libraryId": "lib1",
                    "mediaType": "book",
                    "media": {
                        "metadata": {"title": "Dune", "authorName": "Frank Herbert"},
                        "duration": 12600.0,
                        "chapters": [],
                        "audioFiles": [],
                        "tracks": [],
                    },
                },
            },
            {
                "libraryItemId": "li_2",
                "libraryItem": {
                    "id": "li_2",
                    "libraryId": "lib1",
                    "mediaType": "book",
                    "media": {
                        "metadata": {"title": "Neuromancer", "authorName": "William Gibson"},
                        "duration": 8400.0,
                        "chapters": [],
                        "audioFiles": [],
                        "tracks": [],
                    },
                },
            },
        ],
        "createdAt": 1699800000000,
        "lastUpdate": 1699900000000,
    }
    playlist = Playlist.model_validate(data)
    assert playlist.id == "pl_123"
    assert playlist.name == "Sci-Fi Collection"
    assert playlist.item_count == 2
    assert playlist.items[0].title == "Dune"
    assert playlist.items[1].title == "Neuromancer"
    assert playlist.total_duration == 21000.0


# ---- API Client ----

def _playlist_payload(playlist_id="pl1", name="Test Playlist", library_id="lib1"):
    return {
        "id": playlist_id,
        "name": name,
        "description": "A test playlist",
        "libraryId": library_id,
        "userId": "u1",
        "items": [
            {
                "libraryItemId": "li1",
                "libraryItem": {
                    "id": "li1",
                    "libraryId": library_id,
                    "mediaType": "book",
                    "media": {
                        "metadata": {"title": "Book 1"},
                        "duration": 1800.0,
                        "chapters": [],
                        "audioFiles": [],
                        "tracks": [],
                    },
                },
            }
        ],
    }


@pytest.mark.asyncio
async def test_get_playlists(server_url, auth_token):
    async with respx.mock(base_url=server_url) as mock:
        mock.get("/api/playlists").mock(
            return_value=httpx.Response(
                200,
                json={
                    "playlists": [
                        _playlist_payload("pl1", "Favorites"),
                        _playlist_payload("pl2", "To Read"),
                    ]
                },
            )
        )
        async with ABSClient(server_url, token=auth_token) as client:
            playlists = await client.get_playlists()
    assert len(playlists) == 2
    assert playlists[0].name == "Favorites"
    assert playlists[1].name == "To Read"


@pytest.mark.asyncio
async def test_get_playlists_with_library_filter(server_url, auth_token):
    """The server returns all playlists; the client filters by library_id."""
    async with respx.mock(base_url=server_url) as mock:
        route = mock.get("/api/playlists").mock(
            return_value=httpx.Response(
                200,
                json={
                    "playlists": [
                        _playlist_payload("pl1", "In lib1", library_id="lib1"),
                        _playlist_payload("pl2", "In lib2", library_id="lib2"),
                    ]
                },
            )
        )
        async with ABSClient(server_url, token=auth_token) as client:
            playlists = await client.get_playlists(library_id="lib1")
    assert len(playlists) == 1
    assert playlists[0].name == "In lib1"
    assert route.called


@pytest.mark.asyncio
async def test_get_playlists_empty(server_url, auth_token):
    async with respx.mock(base_url=server_url) as mock:
        mock.get("/api/playlists").mock(
            return_value=httpx.Response(200, json={"playlists": []})
        )
        async with ABSClient(server_url, token=auth_token) as client:
            playlists = await client.get_playlists()
    assert playlists == []


@pytest.mark.asyncio
async def test_get_playlist_detail(server_url, auth_token):
    async with respx.mock(base_url=server_url) as mock:
        mock.get("/api/playlists/pl1").mock(
            return_value=httpx.Response(200, json=_playlist_payload("pl1", "Detail Test"))
        )
        async with ABSClient(server_url, token=auth_token) as client:
            playlist = await client.get_playlist_detail("pl1")
    assert playlist.id == "pl1"
    assert playlist.name == "Detail Test"
    assert playlist.item_count == 1
    assert playlist.items[0].title == "Book 1"
