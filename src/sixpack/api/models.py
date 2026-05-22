from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


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


class LibraryItemMedia(BaseModel):
    metadata: dict[str, Any] = Field(default_factory=dict)
    duration: float | None = None
    chapters: list[Chapter] = Field(default_factory=list)
    audio_files: list[dict[str, Any]] = Field(default_factory=list, alias="audioFiles")
    tracks: list[AudioTrack] = Field(default_factory=list)

    model_config = {"populate_by_name": True}

    @property
    def title(self) -> str:
        return str(self.metadata.get("title", "Unknown"))

    @property
    def author(self) -> str:
        return str(self.metadata.get("authorName", ""))

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
    updated_at: int | None = Field(None, alias="updatedAt")
    added_at: int | None = Field(None, alias="addedAt")

    model_config = {"populate_by_name": True}

    @property
    def title(self) -> str:
        return self.media.title

    @property
    def author(self) -> str:
        return self.media.author

    @property
    def duration(self) -> float:
        return self.media.duration or 0.0

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
    def book_count(self) -> int:
        return len(self.books)

    @property
    def sorted_books(self) -> list[SeriesBook]:
        return sorted(self.books, key=lambda b: b.sequence_number())

    def cover_url(self, server_url: str, token: str) -> str | None:
        if not self.books:
            return None
        return self.sorted_books[0].cover_url(server_url, token)


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
