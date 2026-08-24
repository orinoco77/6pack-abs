"""Audiobookshelf REST API client."""
from __future__ import annotations

import logging
from typing import Any

import httpx

from .models import (
    Library,
    LibraryItem,
    LibraryStats,
    LoginResponse,
    MediaProgress,
    PersonalizedShelf,
    PlaybackSession,
    Playlist,
    Series,
    User,
)

logger = logging.getLogger(__name__)


class AuthenticationError(Exception):
    pass


class APIError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


class ABSClient:
    """Async client for the Audiobookshelf API."""

    def __init__(self, base_url: str, token: str = "") -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        # Constructed eagerly, not deferred to __aenter__: httpx.AsyncClient
        # doesn't need a running event loop to be constructed (only actual
        # requests do), and this lets ABSClient double as a long-lived,
        # connection-pooling client held for a whole login session -- not
        # just a short-lived `async with` scope -- without changing its
        # public shape. `async with` still works unchanged for one-shot
        # uses (e.g. the pre-auth login request in app.py).
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=self._auth_headers(),
            timeout=30.0,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def __aenter__(self) -> ABSClient:
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the underlying connection pool. Callers that hold an
        ABSClient for a whole session (rather than via `async with`) must
        call this explicitly when done with it -- e.g. before replacing
        MainWindow._client with a new one on re-login/server switch."""
        await self._client.aclose()

    def _auth_headers(self) -> dict[str, str]:
        if self.token:
            return {"Authorization": f"Bearer {self.token}"}
        return {}

    @property
    def _http(self) -> httpx.AsyncClient:
        return self._client

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code == 401:
            raise AuthenticationError("Invalid or expired token")
        if response.is_error:
            raise APIError(
                response.status_code,
                f"API error {response.status_code}: {response.text[:200]}",
            )

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    async def login(self, username: str, password: str) -> LoginResponse:
        response = await self._http.post(
            "/login",
            json={"username": username, "password": password},
        )
        self._raise_for_status(response)
        data = response.json()
        result = LoginResponse.model_validate(data)
        self.token = result.user.token
        self._http.headers.update(self._auth_headers())
        return result

    async def get_current_user(self) -> User:
        response = await self._http.get("/api/me")
        self._raise_for_status(response)
        return User.model_validate(response.json())

    # ------------------------------------------------------------------
    # Libraries
    # ------------------------------------------------------------------

    async def get_libraries(self) -> list[Library]:
        response = await self._http.get("/api/libraries")
        self._raise_for_status(response)
        data = response.json()
        return [Library.model_validate(lib) for lib in data.get("libraries", [])]

    async def get_library_stats(self, library_id: str) -> LibraryStats:
        response = await self._http.get(f"/api/libraries/{library_id}/stats")
        self._raise_for_status(response)
        return LibraryStats.model_validate(response.json())

    # ------------------------------------------------------------------
    # Series
    # ------------------------------------------------------------------

    async def get_series(
        self,
        library_id: str,
        limit: int = 100,
        page: int = 0,
    ) -> list[Series]:
        response = await self._http.get(
            f"/api/libraries/{library_id}/series",
            params={"limit": limit, "page": page, "sort": "name"},
        )
        self._raise_for_status(response)
        data = response.json()
        series_list = [Series.model_validate(s) for s in data.get("results", [])]
        if series_list:
            logger.debug(
                "get_series: %d series returned; first series '%s' has %d books",
                len(series_list), series_list[0].name, len(series_list[0].books),
            )
        return series_list

    async def get_series_detail(self, series_id: str) -> Series:
        response = await self._http.get(
            f"/api/series/{series_id}",
            params={"include": "progress"},
        )
        self._raise_for_status(response)
        return Series.model_validate(response.json())

    # ------------------------------------------------------------------
    # Playlists
    # ------------------------------------------------------------------

    async def get_playlists(
        self,
        library_id: str | None = None,
        limit: int = 100,
        page: int = 0,
    ) -> list[Playlist]:
        """Fetch playlists. If library_id is provided, filters to that library.

        ``GET /api/playlists`` returns every playlist for the authenticated user
        across all libraries under a ``playlists`` key (it does not filter by
        library server-side), so we filter by ``library_id`` here.
        """
        params: dict[str, Any] = {"limit": limit, "page": page}
        response = await self._http.get("/api/playlists", params=params)
        self._raise_for_status(response)
        data = response.json()
        playlists = [Playlist.model_validate(p) for p in data.get("playlists", [])]
        if library_id:
            playlists = [p for p in playlists if p.library_id == library_id]
        if playlists:
            logger.debug(
                "get_playlists: %d playlists returned; first playlist '%s' has %d items",
                len(playlists), playlists[0].name, len(playlists[0].items),
            )
        return playlists

    async def get_playlist_detail(self, playlist_id: str) -> Playlist:
        """Fetch full playlist details including all items."""
        response = await self._http.get(f"/api/playlists/{playlist_id}")
        self._raise_for_status(response)
        return Playlist.model_validate(response.json())

    # ------------------------------------------------------------------
    # Library Items
    # ------------------------------------------------------------------

    async def get_library_items(
        self,
        library_id: str,
        limit: int = 100,
        page: int = 0,
    ) -> list[LibraryItem]:
        response = await self._http.get(
            f"/api/libraries/{library_id}/items",
            params={"limit": limit, "page": page},
        )
        self._raise_for_status(response)
        data = response.json()
        return [LibraryItem.model_validate(item) for item in data.get("results", [])]

    async def get_personalized_shelves(self, library_id: str) -> list[PersonalizedShelf]:
        """Fetch personalized shelves for a library (Continue Listening, Recently Added, etc.)."""
        response = await self._http.get(f"/api/libraries/{library_id}/personalized")
        self._raise_for_status(response)
        data = response.json()
        shelves = []
        for item in data:
            try:
                shelves.append(PersonalizedShelf.model_validate(item))
            except Exception as exc:
                logger.warning("Skipping malformed personalized shelf: %s", exc)
        return shelves

    async def get_library_items_recent(self, library_id: str, limit: int = 20) -> list[LibraryItem]:
        """Fetch recently added items for a library, sorted by addedAt descending."""
        response = await self._http.get(
            f"/api/libraries/{library_id}/items",
            params={"limit": limit, "sort": "addedAt", "desc": 1},
        )
        self._raise_for_status(response)
        data = response.json()
        return [LibraryItem.model_validate(item) for item in data.get("results", [])]

    async def get_library_item(self, item_id: str) -> LibraryItem:
        response = await self._http.get(f"/api/items/{item_id}")
        self._raise_for_status(response)
        return LibraryItem.model_validate(response.json())

    # ------------------------------------------------------------------
    # Progress
    # ------------------------------------------------------------------

    async def get_progress(
        self, item_id: str, episode_id: str | None = None
    ) -> MediaProgress | None:
        path = f"/api/me/progress/{item_id}"
        if episode_id:
            path = f"{path}/{episode_id}"
        response = await self._http.get(path)
        if response.status_code == 404:
            return None
        self._raise_for_status(response)
        data = response.json()
        if not data:
            return None
        return MediaProgress.model_validate(data)

    async def update_progress(
        self,
        item_id: str,
        current_time: float,
        duration: float,
        is_finished: bool = False,
        episode_id: str | None = None,
    ) -> None:
        progress = 0.0 if duration <= 0 else min(current_time / duration, 1.0)
        payload: dict[str, Any] = {
            "currentTime": current_time,
            "duration": duration,
            "progress": progress,
            "isFinished": is_finished,
        }
        path = f"/api/me/progress/{item_id}"
        if episode_id:
            path = f"{path}/{episode_id}"
        response = await self._http.patch(path, json=payload)
        self._raise_for_status(response)

    # ------------------------------------------------------------------
    # Playback
    # ------------------------------------------------------------------

    async def start_playback_session(
        self,
        item_id: str,
        start_time: float = 0.0,
        episode_id: str | None = None,
    ) -> PlaybackSession:
        payload = {
            "deviceInfo": {"deviceId": "sixpack-linux", "clientName": "SixPack"},
            "forceDirectPlay": True,
            "forceTranscode": False,
            "supportedMimeTypes": [
                "audio/flac",
                "audio/mpeg",
                "audio/mp4",
                "audio/ogg",
                "audio/aac",
                "audio/x-m4b",
            ],
            "mediaPlayer": "SixPack",
        }
        path = f"/api/items/{item_id}/play"
        if episode_id:
            path = f"{path}/{episode_id}"
        response = await self._http.post(path, json=payload)
        self._raise_for_status(response)
        data = response.json()
        if start_time > 0:
            data = {**data, "currentTime": start_time}
        return PlaybackSession.model_validate(data)

    async def close_playback_session(self, session_id: str) -> None:
        response = await self._http.post(f"/api/session/{session_id}/close")
        # Best-effort — don't raise if the session already expired
        if response.status_code not in (200, 404):
            self._raise_for_status(response)

    def stream_url(self, content_url: str) -> str:
        """Build a full streaming URL from a relative contentUrl."""
        if content_url.startswith("http"):
            return content_url
        return f"{self.base_url}{content_url}"
