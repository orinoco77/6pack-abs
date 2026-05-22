"""Tests for Pydantic API models."""
from __future__ import annotations

import pytest

from sixpack.api.models import (
    AudioTrack,
    Chapter,
    Library,
    LibraryItem,
    LibraryItemMedia,
    LoginResponse,
    MediaProgress,
    PlaybackSession,
    Series,
    SeriesBook,
    User,
)


# ---- Chapter ----

def test_chapter_fields():
    c = Chapter(id=1, start=0.0, end=120.5, title="Opening")
    assert c.id == 1
    assert c.start == 0.0
    assert c.end == 120.5
    assert c.title == "Opening"


# ---- AudioTrack ----

def test_audio_track_alias():
    data = {
        "index": 0,
        "startOffset": 0.0,
        "duration": 3600.0,
        "contentUrl": "/api/items/x/file/track.mp3",
        "mimeType": "audio/mpeg",
    }
    track = AudioTrack.model_validate(data)
    assert track.index == 0
    assert track.content_url == "/api/items/x/file/track.mp3"
    assert track.mime_type == "audio/mpeg"


def test_audio_track_defaults():
    track = AudioTrack(index=1)
    assert track.start_offset == 0.0
    assert track.duration == 0.0
    assert track.title is None


# ---- LibraryItemMedia ----

def test_media_title():
    media = LibraryItemMedia(metadata={"title": "The Archers"})
    assert media.title == "The Archers"


def test_media_title_default():
    media = LibraryItemMedia()
    assert media.title == "Unknown"


def test_media_author():
    media = LibraryItemMedia(metadata={"authorName": "BBC"})
    assert media.author == "BBC"


def test_media_series_name_list():
    media = LibraryItemMedia(metadata={"series": [{"name": "Doctor Who"}]})
    assert media.series_name == "Doctor Who"


def test_media_series_name_str():
    media = LibraryItemMedia(metadata={"series": "Star Trek"})
    assert media.series_name == "Star Trek"


def test_media_series_name_missing():
    media = LibraryItemMedia()
    assert media.series_name == ""


# ---- LibraryItem ----

def test_library_item_properties():
    media = LibraryItemMedia(
        metadata={"title": "Episode 1", "authorName": "BBC"},
        duration=1800.0,
    )
    item = LibraryItem(id="item1", libraryId="lib1", media=media)
    assert item.title == "Episode 1"
    assert item.author == "BBC"
    assert item.duration == 1800.0


def test_library_item_cover_url(server_url, auth_token):
    media = LibraryItemMedia()
    item = LibraryItem(id="item1", libraryId="lib1", media=media)
    url = item.cover_url(server_url, auth_token)
    assert url == f"{server_url}/api/items/item1/cover?token={auth_token}"


def test_library_item_duration_default():
    media = LibraryItemMedia()
    item = LibraryItem(id="x", libraryId="l", media=media)
    assert item.duration == 0.0


# ---- SeriesBook ----

def test_series_book_sequence_numeric():
    media = LibraryItemMedia(metadata={"title": "Part 1"})
    book = SeriesBook(id="b1", media=media, sequence="3")
    assert book.sequence_number() == 3.0


def test_series_book_sequence_fractional():
    media = LibraryItemMedia()
    book = SeriesBook(id="b2", media=media, sequence="1.5")
    assert book.sequence_number() == 1.5


def test_series_book_sequence_invalid():
    media = LibraryItemMedia()
    book = SeriesBook(id="b3", media=media, sequence="prologue")
    assert book.sequence_number() == 0.0


def test_series_book_sequence_none():
    media = LibraryItemMedia()
    book = SeriesBook(id="b4", media=media)
    assert book.sequence_number() == 0.0


def test_series_book_cover_url(server_url, auth_token):
    media = LibraryItemMedia()
    book = SeriesBook(id="b1", media=media)
    assert book.cover_url(server_url, auth_token) == f"{server_url}/api/items/b1/cover?token={auth_token}"


# ---- Series ----

def test_series_sorted_books():
    media = LibraryItemMedia()
    b1 = SeriesBook(id="a", media=media, sequence="2")
    b2 = SeriesBook(id="b", media=media, sequence="1")
    b3 = SeriesBook(id="c", media=media, sequence="3")
    series = Series(id="s1", name="My Series", books=[b1, b2, b3])
    sorted_books = series.sorted_books
    assert [b.id for b in sorted_books] == ["b", "a", "c"]


def test_series_book_count():
    media = LibraryItemMedia()
    b = SeriesBook(id="x", media=media)
    series = Series(id="s1", name="Test", books=[b, b])
    assert series.book_count == 2


def test_series_cover_url_empty(server_url, auth_token):
    series = Series(id="s1", name="Empty")
    assert series.cover_url(server_url, auth_token) is None


def test_series_cover_url(server_url, auth_token):
    media = LibraryItemMedia()
    b = SeriesBook(id="cover-id", media=media, sequence="1")
    series = Series(id="s1", name="Test", books=[b])
    url = series.cover_url(server_url, auth_token)
    assert url is not None
    assert "cover-id" in url


# ---- Library ----

def test_library_defaults():
    lib = Library(id="lib1", name="Audiobooks")
    assert lib.media_type == "book"
    assert lib.display_order == 0


def test_library_alias():
    data = {"id": "l1", "name": "Drama", "mediaType": "podcast", "displayOrder": 2}
    lib = Library.model_validate(data)
    assert lib.media_type == "podcast"
    assert lib.display_order == 2


# ---- MediaProgress ----

def test_media_progress_defaults():
    prog = MediaProgress(libraryItemId="item1")
    assert prog.current_time == 0.0
    assert prog.is_finished is False
    assert prog.progress == 0.0


def test_media_progress_alias():
    data = {
        "libraryItemId": "item1",
        "currentTime": 300.0,
        "isFinished": True,
        "progress": 0.95,
    }
    prog = MediaProgress.model_validate(data)
    assert prog.current_time == 300.0
    assert prog.is_finished is True


# ---- PlaybackSession ----

def test_playback_session():
    data = {
        "id": "sess1",
        "userId": "user1",
        "libraryItemId": "item1",
        "audioTracks": [],
        "currentTime": 45.0,
        "duration": 3600.0,
    }
    session = PlaybackSession.model_validate(data)
    assert session.id == "sess1"
    assert session.current_time == 45.0
    assert session.audio_tracks == []


# ---- User / LoginResponse ----

def test_user_fields():
    u = User(id="u1", username="adam", token="tok123")
    assert u.username == "adam"
    assert u.token == "tok123"
    assert u.is_active is True


def test_login_response():
    data = {
        "user": {
            "id": "u1",
            "username": "adam",
            "token": "abc",
            "isActive": True,
        }
    }
    resp = LoginResponse.model_validate(data)
    assert resp.user.username == "adam"
    assert resp.user.token == "abc"
