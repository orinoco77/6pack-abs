"""Tests for ABSClient using respx to mock httpx."""
from __future__ import annotations

import json
import pytest
import respx
import httpx

from sixpack.api.client import ABSClient, AuthenticationError, APIError


# ---- Fixtures ----

def _user_payload():
    return {
        "id": "u1",
        "username": "adam",
        "token": "tok-abc",
        "isActive": True,
        "type": "admin",
    }


def _library_payload(lib_id="lib1", name="Audiobooks"):
    return {
        "id": lib_id,
        "name": name,
        "mediaType": "book",
        "displayOrder": 1,
    }


def _series_payload(series_id="s1", name="My Series"):
    return {
        "id": series_id,
        "name": name,
        "nameIgnorePrefix": name,
        "libraryId": "lib1",
        "books": [],
    }


def _book_payload(book_id="b1"):
    return {
        "id": book_id,
        "libraryId": "lib1",
        "mediaType": "book",
        "media": {
            "metadata": {"title": "Episode 1", "authorName": "BBC"},
            "duration": 1800.0,
            "chapters": [],
            "audioFiles": [],
            "tracks": [],
        },
        "sequence": "1",
    }


def _progress_payload():
    return {
        "libraryItemId": "b1",
        "currentTime": 900.0,
        "duration": 1800.0,
        "progress": 0.5,
        "isFinished": False,
    }


def _session_payload():
    return {
        "id": "sess1",
        "userId": "u1",
        "libraryItemId": "b1",
        "mediaType": "book",
        "audioTracks": [
            {
                "index": 0,
                "startOffset": 0.0,
                "duration": 1800.0,
                "contentUrl": "/api/items/b1/file/track.mp3",
                "mimeType": "audio/mpeg",
            }
        ],
        "currentTime": 0.0,
        "duration": 1800.0,
    }


# ---- Login ----

@pytest.mark.asyncio
async def test_login_success(server_url):
    async with respx.mock(base_url=server_url) as mock:
        mock.post("/login").mock(
            return_value=httpx.Response(200, json={"user": _user_payload()})
        )
        async with ABSClient(server_url) as client:
            result = await client.login("adam", "secret")
    assert result.user.token == "tok-abc"
    assert result.user.username == "adam"


@pytest.mark.asyncio
async def test_login_sets_token(server_url):
    async with respx.mock(base_url=server_url) as mock:
        mock.post("/login").mock(
            return_value=httpx.Response(200, json={"user": _user_payload()})
        )
        async with ABSClient(server_url) as client:
            await client.login("adam", "secret")
            assert client.token == "tok-abc"


@pytest.mark.asyncio
async def test_login_401(server_url):
    async with respx.mock(base_url=server_url) as mock:
        mock.post("/login").mock(return_value=httpx.Response(401))
        async with ABSClient(server_url) as client:
            with pytest.raises(AuthenticationError):
                await client.login("adam", "wrong")


@pytest.mark.asyncio
async def test_login_500(server_url):
    async with respx.mock(base_url=server_url) as mock:
        mock.post("/login").mock(return_value=httpx.Response(500, text="Internal Error"))
        async with ABSClient(server_url) as client:
            with pytest.raises(APIError) as exc_info:
                await client.login("adam", "pass")
    assert exc_info.value.status_code == 500


# ---- get_current_user ----

@pytest.mark.asyncio
async def test_get_current_user(server_url, auth_token):
    async with respx.mock(base_url=server_url) as mock:
        mock.get("/api/me").mock(
            return_value=httpx.Response(200, json=_user_payload())
        )
        async with ABSClient(server_url, token=auth_token) as client:
            user = await client.get_current_user()
    assert user.username == "adam"


# ---- Libraries ----

@pytest.mark.asyncio
async def test_get_libraries(server_url, auth_token):
    async with respx.mock(base_url=server_url) as mock:
        mock.get("/api/libraries").mock(
            return_value=httpx.Response(
                200,
                json={"libraries": [_library_payload(), _library_payload("lib2", "Drama")]},
            )
        )
        async with ABSClient(server_url, token=auth_token) as client:
            libs = await client.get_libraries()
    assert len(libs) == 2
    assert libs[0].name == "Audiobooks"
    assert libs[1].name == "Drama"


@pytest.mark.asyncio
async def test_get_libraries_empty(server_url, auth_token):
    async with respx.mock(base_url=server_url) as mock:
        mock.get("/api/libraries").mock(
            return_value=httpx.Response(200, json={"libraries": []})
        )
        async with ABSClient(server_url, token=auth_token) as client:
            libs = await client.get_libraries()
    assert libs == []


# ---- Series ----

@pytest.mark.asyncio
async def test_get_series(server_url, auth_token):
    async with respx.mock(base_url=server_url) as mock:
        mock.get("/api/libraries/lib1/series").mock(
            return_value=httpx.Response(
                200,
                json={"results": [_series_payload(), _series_payload("s2", "Another")]},
            )
        )
        async with ABSClient(server_url, token=auth_token) as client:
            series = await client.get_series("lib1")
    assert len(series) == 2
    assert series[0].name == "My Series"


@pytest.mark.asyncio
async def test_get_series_detail(server_url, auth_token):
    payload = _series_payload("s1")
    payload["books"] = [_book_payload()]
    async with respx.mock(base_url=server_url) as mock:
        mock.get("/api/series/s1").mock(
            return_value=httpx.Response(200, json=payload)
        )
        async with ABSClient(server_url, token=auth_token) as client:
            series = await client.get_series_detail("s1")
    assert series.id == "s1"
    assert len(series.books) == 1
    assert series.books[0].title == "Episode 1"


# ---- Library Items ----

@pytest.mark.asyncio
async def test_get_library_items(server_url, auth_token):
    async with respx.mock(base_url=server_url) as mock:
        mock.get("/api/libraries/lib1/items").mock(
            return_value=httpx.Response(200, json={"results": [
                {
                    "id": "item1",
                    "libraryId": "lib1",
                    "mediaType": "book",
                    "media": {"metadata": {"title": "Book 1"}, "chapters": [], "audioFiles": [], "tracks": []},
                }
            ]})
        )
        async with ABSClient(server_url, token=auth_token) as client:
            items = await client.get_library_items("lib1")
    assert len(items) == 1
    assert items[0].title == "Book 1"


@pytest.mark.asyncio
async def test_get_library_item(server_url, auth_token):
    payload = {
        "id": "item1",
        "libraryId": "lib1",
        "mediaType": "book",
        "media": {"metadata": {"title": "Solo Book"}, "chapters": [], "audioFiles": [], "tracks": []},
    }
    async with respx.mock(base_url=server_url) as mock:
        mock.get("/api/items/item1").mock(return_value=httpx.Response(200, json=payload))
        async with ABSClient(server_url, token=auth_token) as client:
            item = await client.get_library_item("item1")
    assert item.title == "Solo Book"


# ---- Progress ----

@pytest.mark.asyncio
async def test_get_progress(server_url, auth_token):
    async with respx.mock(base_url=server_url) as mock:
        mock.get("/api/me/progress/b1").mock(
            return_value=httpx.Response(200, json=_progress_payload())
        )
        async with ABSClient(server_url, token=auth_token) as client:
            prog = await client.get_progress("b1")
    assert prog is not None
    assert prog.current_time == 900.0


@pytest.mark.asyncio
async def test_get_progress_not_found(server_url, auth_token):
    async with respx.mock(base_url=server_url) as mock:
        mock.get("/api/me/progress/b99").mock(return_value=httpx.Response(404))
        async with ABSClient(server_url, token=auth_token) as client:
            prog = await client.get_progress("b99")
    assert prog is None


@pytest.mark.asyncio
async def test_update_progress(server_url, auth_token):
    async with respx.mock(base_url=server_url) as mock:
        route = mock.patch("/api/me/progress/b1").mock(return_value=httpx.Response(200, json={}))
        async with ABSClient(server_url, token=auth_token) as client:
            await client.update_progress("b1", 300.0, 1800.0, False)
    assert route.called
    body = json.loads(route.calls[0].request.content)
    assert body["currentTime"] == 300.0
    assert abs(body["progress"] - 300.0 / 1800.0) < 0.001


@pytest.mark.asyncio
async def test_update_progress_zero_duration(server_url, auth_token):
    async with respx.mock(base_url=server_url) as mock:
        route = mock.patch("/api/me/progress/b1").mock(return_value=httpx.Response(200, json={}))
        async with ABSClient(server_url, token=auth_token) as client:
            await client.update_progress("b1", 0.0, 0.0, False)
    body = json.loads(route.calls[0].request.content)
    assert body["progress"] == 0.0


# ---- Playback session ----

@pytest.mark.asyncio
async def test_start_playback_session(server_url, auth_token):
    async with respx.mock(base_url=server_url) as mock:
        mock.post("/api/items/b1/play").mock(
            return_value=httpx.Response(200, json=_session_payload())
        )
        async with ABSClient(server_url, token=auth_token) as client:
            session = await client.start_playback_session("b1")
    assert session.id == "sess1"
    assert len(session.audio_tracks) == 1
    assert session.audio_tracks[0].content_url == "/api/items/b1/file/track.mp3"


@pytest.mark.asyncio
async def test_start_playback_session_with_start_time(server_url, auth_token):
    async with respx.mock(base_url=server_url) as mock:
        mock.post("/api/items/b1/play").mock(
            return_value=httpx.Response(200, json=_session_payload())
        )
        async with ABSClient(server_url, token=auth_token) as client:
            session = await client.start_playback_session("b1", start_time=300.0)
    assert session.current_time == 300.0


@pytest.mark.asyncio
async def test_close_playback_session(server_url, auth_token):
    async with respx.mock(base_url=server_url) as mock:
        route = mock.post("/api/session/sess1/close").mock(return_value=httpx.Response(200))
        async with ABSClient(server_url, token=auth_token) as client:
            await client.close_playback_session("sess1")
    assert route.called


@pytest.mark.asyncio
async def test_close_playback_session_404_ignored(server_url, auth_token):
    async with respx.mock(base_url=server_url) as mock:
        mock.post("/api/session/sess1/close").mock(return_value=httpx.Response(404))
        async with ABSClient(server_url, token=auth_token) as client:
            await client.close_playback_session("sess1")  # should not raise


# ---- stream_url ----

def test_stream_url_relative(server_url):
    client = ABSClient(server_url)
    assert client.stream_url("/api/items/x/file/a.mp3") == f"{server_url}/api/items/x/file/a.mp3"


def test_stream_url_absolute(server_url):
    client = ABSClient(server_url)
    full = "http://other.host/file.mp3"
    assert client.stream_url(full) == full


# ---- Context manager guard ----

@pytest.mark.asyncio
async def test_http_property_raises_outside_context(server_url):
    client = ABSClient(server_url)
    with pytest.raises(RuntimeError):
        _ = client._http


# ---- Auth header ----

def test_auth_header_with_token():
    client = ABSClient("http://x", token="mytoken")
    headers = client._auth_headers()
    assert headers == {"Authorization": "Bearer mytoken"}


def test_auth_header_empty():
    client = ABSClient("http://x")
    assert client._auth_headers() == {}
