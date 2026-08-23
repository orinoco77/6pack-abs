from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    """Audiobookshelf descriptions are sometimes plain text, sometimes basic
    HTML (e.g. Audible-sourced metadata) -- strip tags so callers always get
    plain text, regardless of which the server sent."""
    return _HTML_TAG_RE.sub("", text).strip()


class Chapter(BaseModel):
    id: int
    start: float
    end: float
    title: str


class AudioTrack(BaseModel):
    index: int
    start_offset: float = Field(0.0, alias="startOffset")
    duration: float = 0.0
    title: str | None = None
    content_url: str = Field("", alias="contentUrl")
    mime_type: str = Field("audio/mpeg", alias="mimeType")

    model_config = {"populate_by_name": True}


class PodcastEpisode(BaseModel):
    id: str
    library_item_id: str = Field("", alias="libraryItemId")
    title: str = ""
    # Raw field name deliberately differs from the exposed `description`
    # property below (stripped of HTML) -- keeps the accessor uniform with
    # LibraryItemMedia.description/etc., which are computed properties too,
    # so PlayerScreen can read `<item>.description` the same way regardless
    # of which item type it's playing.
    raw_description: str | None = Field(None, alias="description")
    audio_file: dict[str, Any] = Field(default_factory=dict, alias="audioFile")
    chapters: list[Chapter] = Field(default_factory=list)

    model_config = {"populate_by_name": True, "extra": "allow"}

    @property
    def duration(self) -> float:
        return float(self.audio_file.get("duration", 0.0) or 0.0)

    @property
    def description(self) -> str:
        return _strip_html(self.raw_description or "")


class LibraryItemMedia(BaseModel):
    metadata: dict[str, Any] = Field(default_factory=dict)
    duration: float | None = None
    chapters: list[Chapter] = Field(default_factory=list)
    audio_files: list[dict[str, Any]] = Field(default_factory=list, alias="audioFiles")
    tracks: list[AudioTrack] = Field(default_factory=list)
    episodes: list[PodcastEpisode] = Field(default_factory=list)

    model_config = {"populate_by_name": True}

    @property
    def title(self) -> str:
        return str(self.metadata.get("title", "Unknown"))

    @property
    def author(self) -> str:
        return str(self.metadata.get("authorName", ""))

    @property
    def description(self) -> str:
        return _strip_html(str(self.metadata.get("description") or ""))

    @property
    def series_name(self) -> str:
        series = self.metadata.get("series")
        if isinstance(series, list) and series:
            return str(series[0].get("name", ""))
        if isinstance(series, str):
            return series
        return ""


class LibraryItem(BaseModel):
    id: str
    library_id: str = Field(alias="libraryId")
    media_type: str = Field("book", alias="mediaType")
    media: LibraryItemMedia
    recent_episode: PodcastEpisode | None = Field(None, alias="recentEpisode")
    updated_at: int | None = Field(None, alias="updatedAt")
    added_at: int | None = Field(None, alias="addedAt")

    model_config = {"populate_by_name": True}

    @property
    def title(self) -> str:
        return self.media.title

    @property
    def subtitle(self) -> str:
        return self.media.author

    @property
    def author(self) -> str:
        return self.media.author

    @property
    def duration(self) -> float:
        return self.media.duration or 0.0

    @property
    def description(self) -> str:
        return self.media.description

    def cover_url(self, server_url: str, token: str) -> str:
        return f"{server_url}/api/items/{self.id}/cover?token={token}"


class SeriesBook(BaseModel):
    """A library item as it appears inside a series response."""

    id: str
    library_id: str = Field("", alias="libraryId")
    media_type: str = Field("book", alias="mediaType")
    media: LibraryItemMedia
    sequence: str | None = None

    model_config = {"populate_by_name": True, "extra": "allow"}

    @property
    def title(self) -> str:
        return self.media.title

    @property
    def duration(self) -> float:
        return self.media.duration or 0.0

    @property
    def description(self) -> str:
        return self.media.description

    def cover_url(self, server_url: str, token: str) -> str:
        return f"{server_url}/api/items/{self.id}/cover?token={token}"

    def sequence_number(self) -> float:
        """Return numeric sequence for sorting (falls back to 0)."""
        try:
            return float(self.sequence or 0)
        except (ValueError, TypeError):
            return 0.0


class Series(BaseModel):
    id: str
    name: str
    name_ignore_prefix: str = Field("", alias="nameIgnorePrefix")
    library_id: str = Field("", alias="libraryId")
    books: list[SeriesBook] = Field(default_factory=list)
    total_duration: float | None = Field(None, alias="totalDuration")

    model_config = {"populate_by_name": True}

    @property
    def title(self) -> str:
        return self.name

    @property
    def subtitle(self) -> str:
        n = len(self.books)
        return f"{n} book" if n == 1 else f"{n} books"

    @property
    def book_count(self) -> int:
        return len(self.books)

    @property
    def sorted_books(self) -> list[SeriesBook]:
        return sorted(self.books, key=lambda b: b.sequence_number())

    def cover_url(self, server_url: str, token: str) -> str | None:
        if not self.books:
            return None
        return self.sorted_books[0].cover_url(server_url, token)


class PlaylistItem(BaseModel):
    """A library item as it appears inside a playlist.

    Audiobookshelf nests the full library item under ``libraryItem`` rather than
    exposing ``media`` directly on the playlist entry, so ``media``/``title``/etc.
    are surfaced here as properties that delegate to the embedded library item.
    """

    library_item_id: str = Field(alias="libraryItemId")
    library_item: LibraryItem = Field(alias="libraryItem")
    id: str = ""
    episode_id: str | None = Field(None, alias="episodeId")
    added_at: int | None = Field(None, alias="addedAt")

    model_config = {"populate_by_name": True, "extra": "allow"}

    @property
    def media(self) -> LibraryItemMedia:
        return self.library_item.media

    @property
    def media_type(self) -> str:
        return self.library_item.media_type

    @property
    def title(self) -> str:
        return self.media.title

    @property
    def duration(self) -> float:
        return self.media.duration or 0.0

    @property
    def description(self) -> str:
        return self.media.description

    def cover_url(self, server_url: str, token: str) -> str:
        return f"{server_url}/api/items/{self.library_item_id}/cover?token={token}"


class Playlist(BaseModel):
    """A user-created playlist of audiobooks/podcasts."""

    id: str
    name: str
    description: str | None = None
    library_id: str = Field("", alias="libraryId")
    user_id: str = Field("", alias="userId")
    items: list[PlaylistItem] = Field(default_factory=list)
    created_at: int | None = Field(None, alias="createdAt")
    updated_at: int | None = Field(None, alias="lastUpdate")

    model_config = {"populate_by_name": True}

    @property
    def title(self) -> str:
        return self.name

    @property
    def subtitle(self) -> str:
        n = len(self.items)
        return f"{n} item" if n == 1 else f"{n} items"

    @property
    def item_count(self) -> int:
        return len(self.items)

    @property
    def total_duration(self) -> float:
        return sum(item.duration for item in self.items)

    def cover_url(self, server_url: str, token: str) -> str | None:
        """Return cover of first item, or None if empty."""
        if not self.items:
            return None
        return self.items[0].cover_url(server_url, token)


class PersonalizedShelf(BaseModel):
    """A shelf returned by /api/libraries/{id}/personalized (e.g. 'Continue Listening')."""

    id: str = ""
    label: str
    type: str = "book"
    entities: list[LibraryItem] = Field(default_factory=list)

    model_config = {"populate_by_name": True, "extra": "ignore"}


class Library(BaseModel):
    id: str
    name: str
    media_type: str = Field("book", alias="mediaType")
    display_order: int = Field(0, alias="displayOrder")
    icon: str = "database"
    settings: dict[str, Any] = Field(default_factory=dict)
    created_at: int | None = Field(None, alias="createdAt")
    last_update: int | None = Field(None, alias="lastUpdate")

    model_config = {"populate_by_name": True}


class LibraryStats(BaseModel):
    total_duration: float = Field(0.0, alias="totalDuration")
    num_audio_tracks: int = Field(0, alias="numAudioTracks")

    model_config = {"populate_by_name": True, "extra": "ignore"}


class MediaProgress(BaseModel):
    id: str | None = None
    user_id: str | None = Field(None, alias="userId")
    library_item_id: str = Field("", alias="libraryItemId")
    episode_id: str | None = Field(None, alias="episodeId")
    duration: float = 0.0
    progress: float = 0.0
    current_time: float = Field(0.0, alias="currentTime")
    is_finished: bool = Field(False, alias="isFinished")
    last_update: int | None = Field(None, alias="lastUpdate")

    model_config = {"populate_by_name": True}


class PlaybackSession(BaseModel):
    id: str
    user_id: str = Field(alias="userId")
    library_item_id: str = Field(alias="libraryItemId")
    media_type: str = Field("book", alias="mediaType")
    audio_tracks: list[AudioTrack] = Field(default_factory=list, alias="audioTracks")
    current_time: float = Field(0.0, alias="currentTime")
    duration: float = 0.0

    model_config = {"populate_by_name": True}


class User(BaseModel):
    id: str
    username: str
    type: str = "user"
    token: str
    is_active: bool = Field(True, alias="isActive")

    model_config = {"populate_by_name": True}


class LoginResponse(BaseModel):
    user: User
