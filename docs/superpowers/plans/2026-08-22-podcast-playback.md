# Podcast Playback Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make podcasts playable. Browsing a podcast show, picking an episode (from its episode list or directly from Continue Listening), playing it, and tracking progress per-episode — all currently broken because SixPack treats podcast shows as if they were directly-playable books.

**Architecture:** A podcast library item is a *show* (container), not directly playable — Audiobookshelf's data model, playback endpoint, and progress endpoint are genuinely different from the audiobook shape. This plan adds a `PodcastEpisode` model, threads an optional `episode_id` through the 3 API client methods that need it, adds a `PodcastDetailScreen` (episode grid, subclassing the existing `DetailGridScreen` base — the same base `SeriesDetailScreen`/`PlaylistDetailScreen` already use), extends `ChapterSelectScreen` and `PlayerScreen` with a 4th "kind" of playable thing alongside book/series-book/playlist-item, and wires it all into `app.py` following the **book** direct-play pattern (`_on_browse_book_selected`/`_on_browse_item_play_requested`) — not the playlist pattern, which was found during this plan's research to have a real back-navigation bug (see Task 6's note).

**Tech Stack:** Python 3.12, PyQt6, Pydantic v2, `httpx` (already project dependencies), pytest + pytest-qt + `respx` (headless via `QT_QPA_PLATFORM=offscreen`).

**Spec:** `docs/superpowers/specs/2026-08-22-podcast-playback-design.md` — read it in full before starting; it has the live-server research findings (real JSON shapes, real endpoint behavior) this plan's code is built from.

## Global Constraints

- Python ≥ 3.10 (dev/target 3.12). Line length 100 (ruff, `select = ["E","F","I","UP"]`).
- Coverage gate: `--cov-fail-under=80`.
- All Qt tests run under `QT_QPA_PLATFORM=offscreen`.
- No `QGraphicsEffect` subclass anywhere, ever.
- Screen-owns-focus: `PodcastDetailScreen` subclasses `DetailGridScreen`, which already does this correctly — inherit it, don't reinvent it.
- Async fetch callbacks that can resolve after focus/selection moved on must use the established key-guard pattern (`set_expected_key` + `sip.isdeleted()`) already used throughout `DetailGridScreen`/`PlaylistDetailScreen`/`ChapterSelectScreen` — `PodcastDetailScreen` gets this for free by subclassing; nothing new to invent.
- Navigation tests must drive real key events (`qtbot.keyClick`) against whatever actually holds focus — not call internal handler methods directly for what's under test. Direct calls are fine for test *setup* (seeding state) only.
- Model fields: snake_case Python names with `Field(..., alias="camelCase")`, `model_config = {"populate_by_name": True}`.
- **Scope, explicit:** single-episode playback only — no next/prev-episode navigation or auto-advance. Don't build it "for consistency" with series/playlists; this was an explicit user decision.
- Commit after each task. Branch: `feature/exclude-non-audio-libraries` (confirm this is still the current branch before starting — check `git branch --show-current`; if a different branch is checked out, that's the one to use instead).

---

## File Structure

| File | Change |
|------|--------|
| `src/sixpack/api/models.py` (edit) | New `PodcastEpisode` model; `LibraryItemMedia.episodes`; `LibraryItem.recent_episode` |
| `src/sixpack/api/client.py` (edit) | `start_playback_session`/`get_progress`/`update_progress` gain optional `episode_id` |
| `src/sixpack/ui/screens/podcast_detail.py` (new) | `PodcastDetailScreen` — episode grid for one show |
| `src/sixpack/ui/screens/browse.py` (edit) | `podcast_selected`/`podcast_episode_selected` signals; `_emit_item` shape-based dispatch |
| `src/sixpack/ui/screens/player.py` (edit) | `play_podcast_episode`; `progress_update` signal gains an episode-id field |
| `src/sixpack/ui/screens/chapter_select.py` (edit) | `podcast_episode_play_requested` signal; `load_from_podcast_episode` |
| `src/sixpack/ui/app.py` (edit) | `PodcastDetailScreen` wired in; podcast selection/activation/play/progress handlers; new `"podcast_detail"` back-target |
| `tests/test_api/test_models.py` or nearest equivalent (edit) | `PodcastEpisode`/`recent_episode`/`episodes` parsing tests |
| `tests/test_api/test_client.py` (edit) | episode-id-aware endpoint tests |
| `tests/test_ui/test_podcast_detail.py` (new) | `PodcastDetailScreen` tests |
| `tests/test_ui/test_browse_screen.py` (edit) | dispatch tests |
| `tests/test_ui/test_screens.py` (edit) | `player.py`/`chapter_select.py` tests |
| `tests/test_ui/test_app.py` (edit) | wiring tests |

Find the exact existing model-test file with `ls tests/test_api/` before Task 1 — this plan assumes one exists (`LibraryItem`/`LibraryItemMedia` are already tested somewhere); add to it rather than guessing a new filename.

---

## Task 1: Data model — `PodcastEpisode` + `LibraryItem.episodes`/`recent_episode`

**Files:**
- Modify: `src/sixpack/api/models.py`
- Test: whichever existing file under `tests/test_api/` already tests `LibraryItem`/`LibraryItemMedia` (find it first: `grep -rl "class TestLibraryItem\|def test_library_item" tests/test_api/` or similar — if genuinely nothing tests these models directly today, create `tests/test_api/test_models.py`)

**Interfaces:**
- Produces: `PodcastEpisode(BaseModel)` with `id: str`, `library_item_id: str`, `title: str`, `duration: float` (computed property), `chapters: list[Chapter]`. `LibraryItemMedia.episodes: list[PodcastEpisode]`. `LibraryItem.recent_episode: PodcastEpisode | None`.

- [ ] **Step 1: Read `src/sixpack/api/models.py` in full** — you're extending `LibraryItemMedia`/`LibraryItem`, not replacing them. Note `Chapter`'s existing definition (you'll reuse it verbatim) and `LibraryItemMedia.audio_files: list[dict[str, Any]]`'s pattern (raw-dict storage for a nested shape not worth fully typing) — `PodcastEpisode.audio_file` follows the same precedent, singular not plural.

- [ ] **Step 2: Write the failing tests**

```python
from sixpack.api.models import LibraryItem, LibraryItemMedia, PodcastEpisode


def _episode_payload(episode_id="ep1", title="Episode One", duration=1797.376):
    return {
        "id": episode_id,
        "libraryItemId": "show1",
        "title": title,
        "chapters": [],
        "audioFile": {"duration": duration, "index": 1},
    }


def test_podcast_episode_parses_duration_from_nested_audio_file():
    ep = PodcastEpisode.model_validate(_episode_payload())
    assert ep.id == "ep1"
    assert ep.title == "Episode One"
    assert ep.duration == 1797.376


def test_podcast_episode_duration_defaults_to_zero_without_audio_file():
    payload = _episode_payload()
    del payload["audioFile"]
    ep = PodcastEpisode.model_validate(payload)
    assert ep.duration == 0.0


def test_library_item_media_parses_episodes():
    media = LibraryItemMedia.model_validate({
        "metadata": {"title": "My Show"},
        "episodes": [_episode_payload("ep1"), _episode_payload("ep2")],
    })
    assert len(media.episodes) == 2
    assert media.episodes[0].id == "ep1"
    assert media.episodes[1].id == "ep2"


def test_library_item_media_episodes_defaults_empty():
    media = LibraryItemMedia.model_validate({"metadata": {"title": "A Book"}})
    assert media.episodes == []


def test_library_item_parses_recent_episode():
    item = LibraryItem.model_validate({
        "id": "show1",
        "libraryId": "lib1",
        "mediaType": "podcast",
        "media": {"metadata": {"title": "A Show"}},
        "recentEpisode": _episode_payload("ep-recent"),
    })
    assert item.recent_episode is not None
    assert item.recent_episode.id == "ep-recent"


def test_library_item_recent_episode_defaults_none():
    item = LibraryItem.model_validate({
        "id": "book1",
        "libraryId": "lib1",
        "mediaType": "book",
        "media": {"metadata": {"title": "A Book"}},
    })
    assert item.recent_episode is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest <the test file> -v -k "podcast_episode or episodes or recent_episode"`
Expected: FAIL — `ImportError: cannot import name 'PodcastEpisode'`.

- [ ] **Step 4: Implement**

Add to `src/sixpack/api/models.py`, near `LibraryItemMedia`/`LibraryItem` (before `LibraryItem`, since it's referenced there):

```python
class PodcastEpisode(BaseModel):
    id: str
    library_item_id: str = Field("", alias="libraryItemId")
    title: str = ""
    audio_file: dict[str, Any] = Field(default_factory=dict, alias="audioFile")
    chapters: list[Chapter] = Field(default_factory=list)

    model_config = {"populate_by_name": True, "extra": "allow"}

    @property
    def duration(self) -> float:
        return float(self.audio_file.get("duration", 0.0) or 0.0)
```

In `LibraryItemMedia`, add one field:

```python
    episodes: list[PodcastEpisode] = Field(default_factory=list)
```

In `LibraryItem`, add one field:

```python
    recent_episode: PodcastEpisode | None = Field(None, alias="recentEpisode")
```

(`recent_episode` goes on `LibraryItem` directly, alongside `media`/`media_type` — NOT nested inside `LibraryItemMedia`. Confirmed against the real API: `recentEpisode` is a sibling of `media` in the shelf entity JSON, not nested inside it.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest <the test file> -v -k "podcast_episode or episodes or recent_episode"`
Expected: PASS.

- [ ] **Step 6: Run the full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` (twice)
Expected: all passing, coverage ≥80%.

- [ ] **Step 7: Commit**

```bash
git add src/sixpack/api/models.py <the test file>
git commit -m "Add PodcastEpisode model and LibraryItem.episodes/recent_episode fields"
```

---

## Task 2: API client — episode-aware playback and progress

**Files:**
- Modify: `src/sixpack/api/client.py`
- Test: `tests/test_api/test_client.py`

**Interfaces:**
- Consumes: nothing new from Task 1 (this task only threads a string `episode_id` through URL paths — doesn't touch `PodcastEpisode` itself).
- Produces: `start_playback_session(item_id, start_time=0.0, episode_id=None)`, `get_progress(item_id, episode_id=None)`, `update_progress(item_id, current_time, duration, is_finished=False, episode_id=None)` — all backward compatible, `episode_id=None` behaves exactly as today.

- [ ] **Step 1: Read `src/sixpack/api/client.py`'s current `start_playback_session`/`get_progress`/`update_progress` in full** (find them — `get_progress` and `update_progress` are under a `# Progress` section comment, `start_playback_session` under `# Playback`).

- [ ] **Step 2: Write the failing tests**

Add to `tests/test_api/test_client.py`, near the existing `test_get_progress`/`test_update_progress`/`test_start_playback_session*` tests (reuse the existing `_progress_payload()`/`_session_payload()` fixture helpers already in this file):

```python
@pytest.mark.asyncio
async def test_get_progress_with_episode_id(server_url, auth_token):
    async with respx.mock(base_url=server_url) as mock:
        mock.get("/api/me/progress/show1/ep1").mock(
            return_value=httpx.Response(200, json=_progress_payload())
        )
        async with ABSClient(server_url, token=auth_token) as client:
            prog = await client.get_progress("show1", episode_id="ep1")
    assert prog is not None


@pytest.mark.asyncio
async def test_update_progress_with_episode_id(server_url, auth_token):
    async with respx.mock(base_url=server_url) as mock:
        route = mock.patch("/api/me/progress/show1/ep1").mock(
            return_value=httpx.Response(200, json={})
        )
        async with ABSClient(server_url, token=auth_token) as client:
            await client.update_progress("show1", 300.0, 1800.0, False, episode_id="ep1")
    assert route.called


@pytest.mark.asyncio
async def test_start_playback_session_with_episode_id(server_url, auth_token):
    async with respx.mock(base_url=server_url) as mock:
        mock.post("/api/items/show1/play/ep1").mock(
            return_value=httpx.Response(200, json=_session_payload())
        )
        async with ABSClient(server_url, token=auth_token) as client:
            session = await client.start_playback_session("show1", episode_id="ep1")
    assert session.id == "sess1"


@pytest.mark.asyncio
async def test_start_playback_session_without_episode_id_unchanged(server_url, auth_token):
    """Regression guard: books must keep hitting the plain /play path."""
    async with respx.mock(base_url=server_url) as mock:
        route = mock.post("/api/items/b1/play").mock(
            return_value=httpx.Response(200, json=_session_payload())
        )
        async with ABSClient(server_url, token=auth_token) as client:
            await client.start_playback_session("b1")
    assert route.called
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_api/test_client.py -v -k episode_id`
Expected: FAIL.

- [ ] **Step 4: Implement**

Change `start_playback_session`'s signature and path construction (keep the existing body/response handling — only the path and signature change):

```python
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
        session = PlaybackSession.model_validate(response.json())
        if start_time > 0:
            session = PlaybackSession.model_validate(
                {**response.json(), "currentTime": start_time}
            )
        return session
```

Change `get_progress`:

```python
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
```

Change `update_progress`:

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_api/test_client.py -v`
Expected: PASS — including every pre-existing test in this file (books never pass `episode_id`, must be byte-for-byte unaffected).

- [ ] **Step 6: Run the full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` (twice)
Expected: all passing, coverage ≥80%.

- [ ] **Step 7: Commit**

```bash
git add src/sixpack/api/client.py tests/test_api/test_client.py
git commit -m "Thread optional episode_id through playback session and progress endpoints"
```

---

## Task 3: `PodcastDetailScreen`

**Files:**
- Create: `src/sixpack/ui/screens/podcast_detail.py`
- Test: `tests/test_ui/test_podcast_detail.py`

**Interfaces:**
- Consumes: `PodcastEpisode`, `LibraryItem` (Task 1). `DetailGridScreen` (existing base class, unmodified).
- Produces: `PodcastDetailScreen(cover_cache=None, parent=None)`, `.show_loading(show: LibraryItem, server_url="", token="")`, `.load(show: LibraryItem, progress: dict[str, MediaProgress], server_url="", token="")`, `.update_progress(progress: dict[str, MediaProgress])`. Inherits `item_activated = pyqtSignal(object)` (fires with a `PodcastEpisode`) and `back_requested = pyqtSignal()` from `DetailGridScreen`.

- [ ] **Step 1: Read `src/sixpack/ui/screens/playlist_detail.py` in full** (55 lines — this is your template, follow it almost verbatim) and `src/sixpack/ui/screens/detail_grid.py`'s `_populate`/`_refresh_progress`/`_item_*` abstract-method contract (its class docstring lists exactly what a subclass must override).

- [ ] **Step 2: Write the failing tests**

Create `tests/test_ui/test_podcast_detail.py`:

```python
"""Tests for PodcastDetailScreen."""
from __future__ import annotations

from sixpack.api.models import LibraryItem, LibraryItemMedia, MediaProgress, PodcastEpisode
from sixpack.ui.screens.podcast_detail import PodcastDetailScreen


def _episode(episode_id, title, duration=1800.0):
    return PodcastEpisode(
        id=episode_id, libraryItemId="show1", title=title,
        audioFile={"duration": duration},
    )


def _show(episodes):
    return LibraryItem(
        id="show1", libraryId="lib1", mediaType="podcast",
        media=LibraryItemMedia(metadata={"title": "My Show"}, episodes=episodes),
    )


def test_podcast_detail_screen_creates(qtbot):
    screen = PodcastDetailScreen()
    qtbot.addWidget(screen)
    assert screen._grid is not None


def test_podcast_detail_screen_load(qtbot):
    screen = PodcastDetailScreen()
    qtbot.addWidget(screen)
    show = _show([_episode("ep1", "Episode One"), _episode("ep2", "Episode Two")])
    screen.load(show, {}, "http://abs.test:13378", "tok")
    assert screen._hero_backdrop._hero_title.text() == "My Show"
    assert screen._grid.item_count == 2


def test_podcast_detail_screen_show_loading(qtbot):
    screen = PodcastDetailScreen()
    qtbot.addWidget(screen)
    show = _show([_episode("ep1", "Episode One")])
    screen.show_loading(show, "http://abs.test:13378", "tok")
    assert screen._grid.item_count == 1


def test_podcast_detail_screen_item_activated_emits_episode(qtbot):
    screen = PodcastDetailScreen()
    qtbot.addWidget(screen)
    show = _show([_episode("ep1", "Episode One")])
    screen.load(show, {}, "http://abs.test:13378", "tok")

    received = []
    screen.item_activated.connect(received.append)
    screen._on_item_activated(0)

    assert len(received) == 1
    assert received[0].id == "ep1"


def test_podcast_detail_screen_progress_keyed_by_episode_id(qtbot):
    screen = PodcastDetailScreen()
    qtbot.addWidget(screen)
    show = _show([_episode("ep1", "Episode One", duration=1000.0)])
    progress = {"ep1": MediaProgress(libraryItemId="show1", episodeId="ep1", currentTime=500.0, duration=1000.0)}
    screen.load(show, progress, "http://abs.test:13378", "tok")
    fraction, finished = screen._item_progress(show.media.episodes[0], progress)
    assert fraction == 0.5
    assert finished is False


def test_podcast_detail_screen_episode_cover_uses_show_cover(qtbot):
    """Episodes have no cover art of their own — every card in this grid
    uses the parent show's cover."""
    screen = PodcastDetailScreen()
    qtbot.addWidget(screen)
    show = _show([_episode("ep1", "Episode One")])
    screen.load(show, {}, "http://abs.test:13378", "tok")
    url = screen._item_cover_url(show.media.episodes[0], "http://abs.test:13378", "tok")
    assert url == show.cover_url("http://abs.test:13378", "tok")


def test_podcast_detail_screen_back_signal(qtbot):
    screen = PodcastDetailScreen()
    qtbot.addWidget(screen)
    received = []
    screen.back_requested.connect(lambda: received.append(True))
    screen.back_requested.emit()
    assert received == [True]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_podcast_detail.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 4: Implement**

Create `src/sixpack/ui/screens/podcast_detail.py`:

```python
"""Podcast detail screen — episode grid with progress indicators."""
from __future__ import annotations

from sixpack.api.models import LibraryItem, MediaProgress, PodcastEpisode
from sixpack.ui.cover_cache import CoverCache
from sixpack.ui.screens.detail_grid import DetailGridScreen


class PodcastDetailScreen(DetailGridScreen):
    """
    Shows the episode grid for a podcast show. Emits item_activated(episode)
    — the caller (app.py) decides whether to route through chapter
    selection or play directly. Emits back_requested() on Back.
    """

    def __init__(self, cover_cache: CoverCache | None = None, parent=None) -> None:
        super().__init__(cover_cache=cover_cache, parent=parent)
        self._show: LibraryItem | None = None

    def _item_key(self, item: PodcastEpisode) -> str:
        return item.id

    def _item_progress(self, item: PodcastEpisode, progress: dict) -> tuple[float, bool]:
        prog: MediaProgress | None = progress.get(item.id)
        if prog is None or not item.duration:
            return 0.0, False
        finished = bool(prog.is_finished)
        fraction = 0.0 if finished else max(0.0, min(1.0, prog.current_time / item.duration))
        return fraction, finished

    def _item_title(self, item: PodcastEpisode) -> str:
        return item.title

    def _item_subtitle(self, item: PodcastEpisode) -> str:
        return ""

    def _item_cover_url(self, item: PodcastEpisode, server_url: str, token: str) -> str | None:
        # Episodes have no cover of their own — every card uses the show's.
        if self._show is None:
            return None
        return self._show.cover_url(server_url, token)

    def _item_media_type(self, item: PodcastEpisode) -> str:
        return "podcast"

    def show_loading(self, show: LibraryItem, server_url: str = "", token: str = "") -> None:
        self._show = show
        self._populate(show.title, show.media.episodes, {}, server_url, token)

    def load(
        self,
        show: LibraryItem,
        progress: dict[str, MediaProgress],
        server_url: str = "",
        token: str = "",
    ) -> None:
        self._show = show
        self._populate(show.title, show.media.episodes, progress, server_url, token)

    def update_progress(self, progress: dict[str, MediaProgress]) -> None:
        self._refresh_progress(progress)
```

Check `LibraryItem` has a `.title` property that resolves to `media.title` (confirmed in Task 1's model read — it does, via `LibraryItemMedia.title`) — `show.title` above relies on that.

- [ ] **Step 5: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_podcast_detail.py -v`
Expected: PASS.

- [ ] **Step 6: Run the full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` (twice)
Expected: all passing, coverage ≥80%.

- [ ] **Step 7: Commit**

```bash
git add src/sixpack/ui/screens/podcast_detail.py tests/test_ui/test_podcast_detail.py
git commit -m "Add PodcastDetailScreen (episode grid for one podcast show)"
```

---

## Task 4: Browse dispatch — podcast signals + shape-based `_emit_item` routing

**Files:**
- Modify: `src/sixpack/ui/screens/browse.py`
- Test: `tests/test_ui/test_browse_screen.py`

**Interfaces:**
- Consumes: `LibraryItem.media_type`/`.recent_episode` (Task 1).
- Produces: `BrowseScreen.podcast_selected = pyqtSignal(object)` (fires with a `LibraryItem` show, no `recent_episode`), `BrowseScreen.podcast_episode_selected = pyqtSignal(object, object)` (fires with `(LibraryItem show, PodcastEpisode episode)`).

- [ ] **Step 1: Read `browse.py`'s current `_emit_item` and the `pyqtSignal` declarations at the top of `BrowseScreen`** (near `series_selected`/`playlist_selected`/`book_selected`).

- [ ] **Step 2: Write the failing tests**

Find the existing `_lib`/`_li`/`_series`/`_playlist` test helpers near the top of `tests/test_ui/test_browse_screen.py` and reuse them. Add:

```python
def _podcast_show(item_id="show1", name="My Show"):
    return LibraryItem(
        id=item_id, libraryId="lib1", mediaType="podcast",
        media=LibraryItemMedia(metadata={"title": name}),
    )


def _podcast_show_with_recent_episode(item_id="show1", name="My Show"):
    episode = PodcastEpisode(id="ep1", libraryItemId=item_id, title="Recent Episode")
    return LibraryItem(
        id=item_id, libraryId="lib1", mediaType="podcast",
        media=LibraryItemMedia(metadata={"title": name}),
        recentEpisode=episode,
    )


def test_emit_item_podcast_show_without_recent_episode_emits_podcast_selected(qtbot):
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    show = _podcast_show()
    received = []
    screen.podcast_selected.connect(received.append)
    screen._emit_item(RowType.RECENTLY_ADDED, show)
    assert received == [show]


def test_emit_item_podcast_show_with_recent_episode_emits_podcast_episode_selected(qtbot):
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    show = _podcast_show_with_recent_episode()
    received = []
    screen.podcast_episode_selected.connect(lambda s, e: received.append((s, e)))
    screen._emit_item(RowType.CONTINUE_LISTENING, show)
    assert len(received) == 1
    assert received[0][0] is show
    assert received[0][1] is show.recent_episode


def test_emit_item_plain_book_still_emits_book_selected(qtbot):
    """Regression guard: podcast dispatch must not affect books."""
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    item = _li("i1", "A Book")
    received = []
    screen.book_selected.connect(received.append)
    screen._emit_item(RowType.RECENTLY_ADDED, item)
    assert received == [item]
```

Add `PodcastEpisode` to this test file's existing `from sixpack.api.models import (...)` import block.

- [ ] **Step 3: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_browse_screen.py -v -k podcast`
Expected: FAIL — `AttributeError: 'BrowseScreen' object has no attribute 'podcast_selected'`.

- [ ] **Step 4: Implement**

Add two signals to `BrowseScreen`, next to the existing `book_selected`/`series_selected`/`playlist_selected`:

```python
    podcast_selected = pyqtSignal(object)                  # LibraryItem (a podcast show)
    podcast_episode_selected = pyqtSignal(object, object)  # (LibraryItem show, PodcastEpisode)
```

Change `_emit_item`'s final `else` branch:

```python
    def _emit_item(self, row_type: RowType, item: Any) -> None:
        if row_type == RowType.SERIES:
            self.series_selected.emit(item)
        elif row_type == RowType.PLAYLISTS:
            self.playlist_selected.emit(item)
        elif getattr(item, "media_type", "") == "podcast":
            if item.recent_episode is not None:
                self.podcast_episode_selected.emit(item, item.recent_episode)
            else:
                self.podcast_selected.emit(item)
        else:
            self.book_selected.emit(item)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_browse_screen.py -v`
Expected: PASS — every pre-existing test in this file too (86+ tests as of this writing — the exact count will have grown since; the point is zero regressions).

- [ ] **Step 6: Run the full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` (twice)
Expected: all passing, coverage ≥80%.

- [ ] **Step 7: Commit**

```bash
git add src/sixpack/ui/screens/browse.py tests/test_ui/test_browse_screen.py
git commit -m "Dispatch podcast shows/episodes to their own signals in BrowseScreen"
```

---

## Task 5: Player — `play_podcast_episode` + episode-aware progress signal

**Files:**
- Modify: `src/sixpack/ui/screens/player.py`
- Test: `tests/test_ui/test_screens.py`

**Interfaces:**
- Consumes: `PodcastEpisode`, `LibraryItem` (Task 1).
- Produces: `PlayerScreen.play_podcast_episode(episode, show, start_time, server_url, token)`. `PlayerScreen.progress_update` signal changes shape from `(str, float, float, bool)` to `(str, float, float, bool, str)` — 5th field is the episode id, `""` for every non-podcast play method.

- [ ] **Step 1: Read `src/sixpack/ui/screens/player.py`'s `play_library_item` (your template — standalone, no series/playlist index tracking, matching this feature's single-episode scope) and `_reset_per_item_state` in full.** Find the `progress_update` signal declaration and its one `emit(...)` call site (search for `progress_update.emit` — there's exactly one, inside the position-sync timer callback).

- [ ] **Step 2: Write the failing tests**

Find this file's existing `PlayerScreen` test fixtures/helpers in `tests/test_ui/test_screens.py` (search for `def test_play_library_item` or similar to find the established construction pattern — likely a `_make_player_screen(qtbot)`-style helper or direct `PlayerScreen(...)` construction with a fake player). Add, following whatever pattern you find:

```python
def test_play_podcast_episode_sets_item_and_episode_ids(qtbot):
    from sixpack.api.models import LibraryItem, LibraryItemMedia, PodcastEpisode

    screen = _make_player_screen(qtbot)  # use this file's real existing helper name
    show = LibraryItem(
        id="show1", libraryId="lib1", mediaType="podcast",
        media=LibraryItemMedia(metadata={"title": "My Show"}),
    )
    episode = PodcastEpisode(id="ep1", libraryItemId="show1", title="Episode One")

    screen.play_podcast_episode(episode, show, 0.0, "http://abs.test", "tok")

    assert screen._item_id == "show1"
    assert screen._episode_id == "ep1"
    assert screen._title_label.text() == "Episode One"
    assert screen._series_label.text() == "My Show"


def test_progress_update_carries_podcast_episode_id(qtbot):
    from sixpack.api.models import LibraryItem, LibraryItemMedia, PodcastEpisode

    screen = _make_player_screen(qtbot)
    show = LibraryItem(
        id="show1", libraryId="lib1", mediaType="podcast",
        media=LibraryItemMedia(metadata={"title": "My Show"}),
    )
    episode = PodcastEpisode(id="ep1", libraryItemId="show1", title="Episode One")
    screen.play_podcast_episode(episode, show, 0.0, "http://abs.test", "tok")
    screen._duration = 1000.0
    screen._position = 100.0

    received = []
    screen.progress_update.connect(lambda *args: received.append(args))
    screen._on_position(100.0)  # or whatever the real sync-timer callback is named — confirm from Step 1's read

    assert len(received) == 1
    assert received[0][0] == "show1"
    assert received[0][4] == "ep1"


def test_progress_update_episode_id_empty_for_library_item_playback(qtbot):
    """Regression guard: play_library_item (a book, not a podcast) must
    emit an empty episode id — _reset_per_item_state clearing _episode_id
    is what keeps book/playlist progress updates unaffected by this task."""
    from sixpack.api.models import LibraryItem, LibraryItemMedia

    screen = _make_player_screen(qtbot)
    item = LibraryItem(
        id="book1", libraryId="lib1", mediaType="book",
        media=LibraryItemMedia(metadata={"title": "A Book"}),
    )
    screen.play_library_item(item, 0.0, "http://abs.test", "tok")
    screen._duration = 1000.0
    screen._position = 100.0

    received = []
    screen.progress_update.connect(lambda *args: received.append(args))
    screen._on_position(100.0)

    assert len(received) == 1
    assert received[0][4] == ""
```

Read Step 1's findings before finalizing this test file — the exact sync-callback method name and existing `PlayerScreen` construction helper must come from the real file, not be guessed. If no `_make_player_screen`-style helper exists yet, write `PlayerScreen` construction inline matching however the existing `play_library_item`/`play_book` tests in this file already do it.

- [ ] **Step 3: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_screens.py -v -k podcast_episode`
Expected: FAIL — `AttributeError: 'PlayerScreen' object has no attribute 'play_podcast_episode'`.

- [ ] **Step 4: Implement**

Add `self._episode_id = ""` to `__init__` alongside `self._item_id = ""`.

Find `_reset_per_item_state` and add `self._episode_id = ""` to whatever it already resets (read its current body first — it resets several book/series/playlist fields together; add this one line to that same list, don't create a second reset path).

Add `PodcastEpisode` to this file's `sixpack.api.models` import line.

Add the new method, modeled on `play_library_item`:

```python
    def play_podcast_episode(
        self,
        episode: PodcastEpisode,
        show: LibraryItem,
        start_time: float,
        server_url: str,
        token: str,
    ) -> None:
        """Play a podcast episode. Cover/backdrop use the show's own art
        (episodes have none of their own); progress/session calls need the
        episode id too, tracked separately from _item_id."""
        self._reset_per_item_state()
        self._current_index = 0
        self._item_id = show.id
        self._episode_id = episode.id

        self._title_label.setText(episode.title)
        self._series_label.setText(show.title)
        self._episode_label.setText("")

        cover_url = show.cover_url(server_url, token)
        if self._cover_cache is not None:
            self._cover_cache.fetch(cover_url, token, self._set_cover_pixmap)
            self._backdrop.set_expected_key(self._item_id)
            self._cover_cache.fetch_backdrop(
                cover_url, token,
                lambda pix, key=self._item_id: self._set_backdrop_pixmap(pix, key),
            )

        self._server_url = server_url
        self._token = token
        self._sync_timer.start()
```

Change the `progress_update` signal declaration:

```python
    progress_update = pyqtSignal(str, float, float, bool, str)  # item_id, current_time, duration, is_finished, episode_id
```

Find the one `self.progress_update.emit(...)` call site and add `self._episode_id` as the 5th argument:

```python
            self.progress_update.emit(
                self._item_id, self._position, self._duration, is_finished, self._episode_id
            )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_screens.py -v`
Expected: PASS — including every pre-existing `PlayerScreen` test (the signal signature change is the highest-risk part of this task; if any existing test connects to `progress_update` with a 4-arg lambda/slot, it will now fail loudly — fix those call sites to accept 5 args, don't work around it).

- [ ] **Step 6: Run the full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` (twice)
Expected: all passing, coverage ≥80%. **This task alone will NOT make the suite pass** — `app.py`'s `_on_progress_update` slot still has the old 4-arg signature and Task 6 hasn't run yet. Confirm the FAILURE at this point is specifically a slot/signal arity mismatch in `app.py` (i.e. `TypeError` connecting a 5-arg signal to a `@pyqtSlot(str, float, float, bool)`-decorated 4-arg method) and nothing else — if it's some other failure, that's a real regression to fix before moving on. This expected-failure state is resolved by Task 6.

- [ ] **Step 7: Commit**

```bash
git add src/sixpack/ui/screens/player.py tests/test_ui/test_screens.py
git commit -m "Add PlayerScreen.play_podcast_episode; progress_update signal carries episode id"
```

---

## Task 6: `ChapterSelectScreen` podcast support + `app.py` wiring

**Files:**
- Modify: `src/sixpack/ui/screens/chapter_select.py`
- Modify: `src/sixpack/ui/app.py`
- Test: `tests/test_ui/test_screens.py`, `tests/test_ui/test_app.py`

**Interfaces:**
- Consumes: everything from Tasks 1-5 — `PodcastEpisode`/`LibraryItem.recent_episode` (1), episode-aware client methods (2), `PodcastDetailScreen` (3), `podcast_selected`/`podcast_episode_selected` signals (4), `play_podcast_episode`/5-arg `progress_update` (5).
- Produces: a fully working podcast playback flow, end to end.

### Before writing any code: read the real back-navigation pattern, don't trust a paraphrase

This plan's design research found that `_on_playlist_item_activated`/`_on_playlist_item_play_requested`'s back-target handling has a real bug: `_player_back_target` gets set via `"chapter" if self._chapter_back_target == "playlist_detail" else "playlist_detail"`, but `_chapter_back_target` is unconditionally set to `"playlist_detail"` at activation regardless of whether the chapter screen ends up being shown — so for a single-chapter playlist item, pressing Back from the player incorrectly navigates to the (unpopulated) chapter screen instead of straight back to the playlist detail screen. **Do not copy this pattern.**

The **book** direct-play pattern (`_on_browse_book_selected` / the `tag == "browse_book"` block in `_on_result` / `_on_browse_item_play_requested`) does NOT have this bug — it eagerly sets `_player_back_target` to the same non-chapter default as `_chapter_back_target`, then the chapters-handler EXPLICITLY overrides `_player_back_target = "chapter"` only in the branch that actually shows the chapter screen, and the play-requested handler never re-derives it via a ternary. **This is the pattern to mirror.** Read all three pieces in full (`_on_browse_book_selected`, the `tag == "browse_book"` block, `_on_browse_item_play_requested`) before writing the podcast equivalents below — the code given below already follows this verified-correct pattern; your job is to confirm it against the current file (line numbers will have shifted) before pasting it in, not to re-derive it.

(You'll also notice two `elif tag == "playlist_item_chapters":` blocks in `_on_result` — this is a genuine pre-existing dead-code duplicate, unrelated to this task. Do not fix it as part of this task; it's out of scope. Just don't copy structure from it.)

### Part A: `ChapterSelectScreen`

- [ ] **Step 1: Read `src/sixpack/ui/screens/chapter_select.py`'s `load_from_playlist_item`, `_populate_chapters`, and `_on_item_activated` in full.**

- [ ] **Step 2: Write the failing tests**

Add to `tests/test_ui/test_screens.py`, near the existing `ChapterSelectScreen` tests (find the existing `_make_box_set_book`/`_make_chapters` helpers and reuse them):

```python
def test_chapter_screen_load_from_podcast_episode(qtbot):
    from sixpack.api.models import LibraryItem, LibraryItemMedia, PodcastEpisode
    from sixpack.ui.screens.chapter_select import ChapterSelectScreen

    screen = ChapterSelectScreen()
    qtbot.addWidget(screen)
    show = LibraryItem(
        id="show1", libraryId="lib1", mediaType="podcast",
        media=LibraryItemMedia(metadata={"title": "My Show"}),
    )
    episode = PodcastEpisode(id="ep1", libraryItemId="show1", title="Episode One")
    chapters = _make_chapters()

    screen.load_from_podcast_episode(show, episode, chapters, None, "http://localhost", "tok")

    assert screen._hero_backdrop._hero_title.text() == "Episode One"
    assert screen._list.count() == len(chapters)


def test_chapter_screen_podcast_episode_activation_emits_signal(qtbot):
    from sixpack.api.models import LibraryItem, LibraryItemMedia, PodcastEpisode
    from sixpack.ui.screens.chapter_select import ChapterSelectScreen

    screen = ChapterSelectScreen()
    qtbot.addWidget(screen)
    show = LibraryItem(
        id="show1", libraryId="lib1", mediaType="podcast",
        media=LibraryItemMedia(metadata={"title": "My Show"}),
    )
    episode = PodcastEpisode(id="ep1", libraryItemId="show1", title="Episode One")
    chapters = _make_chapters()
    screen.load_from_podcast_episode(show, episode, chapters, None, "http://localhost", "tok")

    received = []
    screen.podcast_episode_play_requested.connect(lambda s, e, t: received.append((s, e, t)))
    item = screen._list.item(0)
    screen._on_item_activated(item)

    assert len(received) == 1
    assert received[0][0] is show
    assert received[0][1] is episode
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_screens.py -v -k podcast_episode`
Expected: FAIL — `AttributeError: 'ChapterSelectScreen' object has no attribute 'load_from_podcast_episode'`.

- [ ] **Step 4: Implement**

Add `PodcastEpisode` to this file's `sixpack.api.models` import line.

Add a new signal next to `play_requested`/`playlist_item_play_requested`/`library_item_play_requested`:

```python
    podcast_episode_play_requested = pyqtSignal(object, object, float)  # LibraryItem show, PodcastEpisode, start_time
```

Add `self._podcast_show: LibraryItem | None = None` and `self._podcast_episode: PodcastEpisode | None = None` wherever `self._book`/`self._playlist_item`/`self._library_item` are initialized in `__init__`.

Add the loader, mirroring `load_from_playlist_item`:

```python
    def load_from_podcast_episode(
        self,
        show: LibraryItem,
        episode: PodcastEpisode,
        chapters: list[Chapter],
        progress: MediaProgress | None,
        server_url: str = "",
        token: str = "",
    ) -> None:
        """Load chapters for a podcast episode. Cover art is the show's own
        (episodes have none of their own)."""
        self._podcast_show = show
        self._podcast_episode = episode
        self._book = None
        self._playlist_item = None
        self._library_item = None
        self._populate_chapters(
            episode.title, chapters, progress,
            show.cover_url(server_url, token), show.id, token,
        )
```

In `_on_item_activated`, add a branch:

```python
    def _on_item_activated(self, item: QListWidgetItem) -> None:
        chapter: Chapter = item.data(Qt.ItemDataRole.UserRole)
        if self._library_item:
            self.library_item_play_requested.emit(self._library_item, chapter.start)
        elif self._book:
            self.play_requested.emit(self._book, chapter.start)
        elif self._playlist_item:
            self.playlist_item_play_requested.emit(self._playlist_item, chapter.start)
        elif self._podcast_episode:
            self.podcast_episode_play_requested.emit(self._podcast_show, self._podcast_episode, chapter.start)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_screens.py -v -k podcast_episode`
Expected: PASS.

### Part B: `app.py` wiring

- [ ] **Step 6: Write the failing tests**

Add to `tests/test_ui/test_app.py`, following this file's existing playlist-wiring tests' style (direct state-poking + real signal emission — see `test_pairing_login_succeeded_saves_token_and_proceeds` for the shape; use the `window` fixture already defined in this file):

```python
def test_podcast_selected_shows_detail_screen(window):
    from sixpack.api.models import LibraryItem, LibraryItemMedia

    show = LibraryItem(
        id="show1", libraryId="lib1", mediaType="podcast",
        media=LibraryItemMedia(metadata={"title": "My Show"}),
    )
    window._server_url = "http://abs.test"
    window._token = "tok"

    window._browse_screen.podcast_selected.emit(show)

    assert window._stack.currentWidget() is window._podcast_detail_screen
    assert window._current_podcast_show is show


def test_podcast_episode_activated_single_chapter_plays_directly(window, monkeypatch):
    from sixpack.api.models import LibraryItem, LibraryItemMedia, PodcastEpisode

    show = LibraryItem(
        id="show1", libraryId="lib1", mediaType="podcast",
        media=LibraryItemMedia(metadata={"title": "My Show"}),
    )
    episode = PodcastEpisode(id="ep1", libraryItemId="show1", title="Episode One")  # no chapters
    window._current_podcast_show = show
    window._server_url = "http://abs.test"
    window._token = "tok"

    played = []
    monkeypatch.setattr(
        window, "_on_podcast_episode_play_requested",
        lambda ep, start_time: played.append((ep, start_time)),
    )

    window._podcast_detail_screen.item_activated.emit(episode)

    assert played == [(episode, 0.0)]
    assert window._player_back_target == "podcast_detail"


def test_podcast_episode_activated_multi_chapter_shows_chapter_screen(window):
    from sixpack.api.models import Chapter, LibraryItem, LibraryItemMedia, PodcastEpisode

    show = LibraryItem(
        id="show1", libraryId="lib1", mediaType="podcast",
        media=LibraryItemMedia(metadata={"title": "My Show"}),
    )
    chapters = [
        Chapter(id=0, start=0.0, end=100.0, title="Part 1"),
        Chapter(id=1, start=100.0, end=200.0, title="Part 2"),
    ]
    episode = PodcastEpisode(id="ep1", libraryItemId="show1", title="Episode One", chapters=chapters)
    window._current_podcast_show = show
    window._server_url = "http://abs.test"
    window._token = "tok"

    window._podcast_detail_screen.item_activated.emit(episode)

    assert window._stack.currentWidget() is window._chapter_screen
    assert window._player_back_target == "chapter"
    assert window._chapter_back_target == "podcast_detail"


def test_podcast_episode_selected_from_continue_listening_sets_browse_back_target(window):
    """Continue-listening entries have no intermediate detail screen —
    mirrors _on_browse_book_selected's direct-from-browse book path."""
    from sixpack.api.models import LibraryItem, LibraryItemMedia, PodcastEpisode

    show = LibraryItem(
        id="show1", libraryId="lib1", mediaType="podcast",
        media=LibraryItemMedia(metadata={"title": "My Show"}),
    )
    episode = PodcastEpisode(id="ep1", libraryItemId="show1", title="Episode One")
    window._server_url = "http://abs.test"
    window._token = "tok"

    window._browse_screen.podcast_episode_selected.emit(show, episode)

    assert window._current_podcast_show is show
    assert window._pending_podcast_episode is episode
    assert window._chapter_back_target == "browse"
    assert window._player_back_target == "browse"


def test_on_player_back_podcast_detail_target_shows_podcast_detail(window):
    window._player_back_target = "podcast_detail"
    window._on_player_back()
    assert window._stack.currentWidget() is window._podcast_detail_screen


def test_on_chapter_back_podcast_detail_target_shows_podcast_detail(window):
    window._chapter_back_target = "podcast_detail"
    window._on_chapter_back()
    assert window._stack.currentWidget() is window._podcast_detail_screen


def test_on_progress_update_forwards_episode_id(window, monkeypatch):
    calls = []
    monkeypatch.setattr(
        window, "_async_update_progress",
        lambda *args, **kwargs: calls.append((args, kwargs)) or _noop_coro(),
    )
    window._server_url = "http://abs.test"
    window._token = "tok"

    window._on_progress_update("show1", 100.0, 1000.0, False, "ep1")

    # Confirm the worker was asked to run something — the exact assertion
    # depends on how _on_progress_update dispatches to the worker in the
    # real current code (read it in Step 1 below before finalizing this
    # test); the key behavior under test is that "ep1" reaches
    # _async_update_progress as the episode_id argument.
    assert calls
    assert "ep1" in calls[0][0] or calls[0][1].get("episode_id") == "ep1"


async def _noop_coro():
    return None
```

Note on the last test: `_on_progress_update`'s exact dispatch mechanism (likely `self._worker.run("progress", self._async_update_progress(...))`) must be confirmed against the real current code before finalizing this test — adjust the monkeypatch/assertion shape to match whatever you find, the requirement being tested (episode id reaches `_async_update_progress`) does not change.

- [ ] **Step 7: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_app.py -v -k podcast`
Expected: FAIL.

- [ ] **Step 8: Implement**

Add imports: `PodcastEpisode` to the `sixpack.api.models` import line; `from sixpack.ui.screens.podcast_detail import PodcastDetailScreen`.

In `_build_ui` (or wherever `self._playlist_detail_screen = PlaylistDetailScreen(...)` is constructed), add alongside it:

```python
        self._podcast_detail_screen = PodcastDetailScreen(cover_cache=self._cover_cache)
```

and add it to the stack: `self._stack.addWidget(self._podcast_detail_screen)`.

Near the other `__init__` state fields (alongside `self._current_playlist`/`self._pending_playlist_item`), add:

```python
        self._current_podcast_show: LibraryItem | None = None
        self._pending_podcast_episode: PodcastEpisode | None = None
```

Wire the signals, alongside the existing `playlist_selected`/`playlist_detail_screen.item_activated` connections:

```python
        self._browse_screen.podcast_selected.connect(self._on_podcast_selected)
        self._browse_screen.podcast_episode_selected.connect(self._on_podcast_episode_selected)
        self._podcast_detail_screen.item_activated.connect(self._on_podcast_episode_activated)
        self._podcast_detail_screen.back_requested.connect(self._show_browse)
        self._chapter_screen.podcast_episode_play_requested.connect(self._on_podcast_episode_play_requested_from_chapter)
        self._chapter_screen.podcast_episode_play_requested.connect(self._forward_chapters_to_player)
```

(Two connections on the same signal, matching the existing `play_requested`/`playlist_item_play_requested`/`library_item_play_requested` pattern where `_forward_chapters_to_player` is connected SECOND, after the play-handler — see that method's own docstring for why the ordering matters: it must run after the play handler resets `PlayerScreen._chapters` via `_reset_per_item_state`, or the forwarded chapter list gets wiped immediately after being set.)

`_on_podcast_episode_play_requested_from_chapter` is a tiny adapter — `ChapterSelectScreen.podcast_episode_play_requested` emits `(show, episode, start_time)`, but `_on_podcast_episode_play_requested` (below) only takes `(episode, start_time)` since it reads `self._current_podcast_show` itself:

```python
    def _on_podcast_episode_play_requested_from_chapter(
        self, show: LibraryItem, episode: PodcastEpisode, start_time: float
    ) -> None:
        self._current_podcast_show = show
        self._on_podcast_episode_play_requested(episode, start_time)
```

Add `_show_podcast_detail`, next to `_show_playlist_detail`:

```python
    def _show_podcast_detail(self) -> None:
        self._stack.setCurrentWidget(self._podcast_detail_screen)
```

Extend `_on_player_back` and `_on_chapter_back` with a new branch each (read their current bodies from earlier in this file — they're small `if`/`elif` chains):

```python
        elif target == "podcast_detail":
            self._show_podcast_detail()
```

(Add this as one more `elif` branch in both methods, in whatever position — order among `elif` branches doesn't matter here since each checks a distinct string.)

Add the podcast-selected (drill into episode list) handler, mirroring `_on_playlist_selected`:

```python
    def _on_podcast_selected(self, show: LibraryItem) -> None:
        self._current_podcast_show = show
        self._podcast_detail_screen.show_loading(show, self._server_url, self._token)
        self._show_podcast_detail()
        self._worker.run("podcast_detail", self._async_fetch_podcast_progress(show))

    async def _async_fetch_podcast_progress(self, show: LibraryItem):
        sem = asyncio.Semaphore(10)

        async def _fetch_one(client: ABSClient, episode_id: str) -> tuple[str, MediaProgress | None]:
            async with sem:
                try:
                    return episode_id, await client.get_progress(show.id, episode_id)
                except Exception as exc:
                    logger.warning("Progress fetch failed for %s/%s: %s", show.id, episode_id, exc)
                    return episode_id, None

        async with ABSClient(self._server_url, token=self._token) as client:
            pairs = await asyncio.gather(
                *(_fetch_one(client, ep.id) for ep in show.media.episodes)
            )
        return dict(pairs)
```

Add the episode-activated handler (from the detail screen's grid — chapters already known synchronously, no worker round-trip needed for this step), following the verified-correct book pattern from the note above:

```python
    def _on_podcast_episode_activated(self, episode: PodcastEpisode) -> None:
        self._pending_podcast_episode = episode
        self._chapter_back_target = "podcast_detail"
        self._player_back_target = "podcast_detail"
        prog = self._podcast_detail_screen._progress.get(episode.id)
        start_time = prog.current_time if prog and not prog.is_finished else 0.0
        if len(episode.chapters) > 1:
            self._player_back_target = "chapter"
            self._chapter_screen.load_from_podcast_episode(
                self._current_podcast_show, episode, episode.chapters, prog,
                self._server_url, self._token,
            )
            self._stack.setCurrentWidget(self._chapter_screen)
        else:
            self._on_podcast_episode_play_requested(episode, start_time)
```

Add the play-requested handler (does NOT touch `_player_back_target` — trusts whichever caller already set it, exactly like `_on_browse_item_play_requested`):

```python
    def _on_podcast_episode_play_requested(self, episode: PodcastEpisode, start_time: float) -> None:
        if not self._player or not self._player_screen:
            return
        show = self._current_podcast_show
        if show is None:
            return
        self._pending_podcast_episode = episode
        self._player_screen.play_podcast_episode(episode, show, start_time, self._server_url, self._token)
        self._worker.run(
            "start_session",
            self._async_start_session(show.id, start_time, episode_id=episode.id),
        )
        self._stack.setCurrentWidget(self._player_screen)
        self._player_screen.setFocus()
```

Add the continue-listening direct-selection handler, mirroring `_on_browse_book_selected` exactly:

```python
    def _on_podcast_episode_selected(self, show: LibraryItem, episode: PodcastEpisode) -> None:
        self._current_podcast_show = show
        self._pending_podcast_episode = episode
        self._chapter_back_target = "browse"
        self._player_back_target = "browse"
        self._worker.run(
            "podcast_continue_progress",
            self._async_get_podcast_progress(show.id, episode.id),
        )

    async def _async_get_podcast_progress(self, item_id: str, episode_id: str):
        async with ABSClient(self._server_url, token=self._token) as client:
            return await client.get_progress(item_id, episode_id)
```

Extend `_async_start_session` with an optional `episode_id` (find its current 2-arg body — `item_id`, `start_time` — and add one parameter, passed through):

```python
    async def _async_start_session(self, item_id: str, start_time: float, episode_id: str | None = None):
        async with ABSClient(self._server_url, token=self._token) as client:
            return await client.start_playback_session(item_id, start_time, episode_id=episode_id)
```

(The 3 existing call sites — book, library item, playlist item — are unaffected, since `episode_id` defaults to `None`.)

In `_on_result`, add two new `elif` branches (position doesn't matter — alongside the existing `browse_book`/`playlist_item_chapters`/etc. branches):

```python
        elif tag == "podcast_detail":
            if self._current_podcast_show:
                self._podcast_detail_screen.update_progress(result)

        elif tag == "podcast_continue_progress":
            episode = self._pending_podcast_episode
            if episode is None:
                return
            progress = result
            if len(episode.chapters) > 1:
                self._player_back_target = "chapter"
                self._chapter_screen.load_from_podcast_episode(
                    self._current_podcast_show, episode, episode.chapters, progress,
                    self._server_url, self._token,
                )
                self._stack.setCurrentWidget(self._chapter_screen)
            else:
                start_time = progress.current_time if progress and not progress.is_finished else 0.0
                self._on_podcast_episode_play_requested(episode, start_time)
```

Update `_on_progress_update`'s slot signature and body (find its current 4-arg version, decorated `@pyqtSlot(str, float, float, bool)`):

```python
    @pyqtSlot(str, float, float, bool, str)
    def _on_progress_update(
        self, item_id: str, current_time: float, duration: float, is_finished: bool, episode_id: str,
    ) -> None:
        self._worker.run(
            "progress",
            self._async_update_progress(item_id, current_time, duration, is_finished, episode_id or None),
        )
```

(Confirm this against the REAL current body — it may do something slightly different before dispatching to the worker; keep whatever else it already does, just add the parameter and thread it through.)

Update `_async_update_progress` similarly (find its current 4-arg version):

```python
    async def _async_update_progress(
        self, item_id: str, current_time: float, duration: float, is_finished: bool,
        episode_id: str | None = None,
    ):
        async with ABSClient(self._server_url, token=self._token) as client:
            await client.update_progress(item_id, current_time, duration, is_finished, episode_id=episode_id)
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_app.py tests/test_ui/test_screens.py -v -k podcast`
Expected: PASS.

- [ ] **Step 10: Run the full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` (three times — this task touches the most shared state of any task in this plan, run it enough times to be confident there's no flakiness)
Expected: all passing, coverage ≥80%. This is the task where Task 5's expected interim failure (the `progress_update` signal/slot arity mismatch) gets resolved — confirm it's actually gone, not just masked.

- [ ] **Step 11: Live verification against a real podcast library**

This plan's design was researched against a real Audiobookshelf server with a real "Podcasts" library. Launch the real app (`nohup .venv/bin/python -m sixpack.main > /tmp/sixpack_run.log 2>&1 &`, screenshot via `screencapture` — see this project's established live-testing pattern from its git history if unfamiliar with the exact commands), navigate into a podcast library, drill into a show, play an episode, and confirm:
- Audio actually plays (not silence/an empty session).
- The player shows the episode title and the show as a subtitle.
- Pressing Back from the player returns to the episode list (or the chapter screen, if this episode had multiple chapters) — not a dead end or the wrong screen.
- A progress record appears server-side keyed by episode id: `curl -H "Authorization: Bearer $TOKEN" "$SERVER/api/me/progress/$SHOW_ID/$EPISODE_ID"` before and after playing for a few seconds, confirming `currentTime` advanced.
- If reachable, try a Continue Listening podcast entry too (plays directly, no intermediate episode-list screen) and confirm Back returns to Browse.

State exactly what you did and observed in your report — this is the step that catches anything the unit tests structurally can't (real audio codec/streaming behavior, real navigation feel).

- [ ] **Step 12: Commit**

```bash
git add src/sixpack/ui/screens/chapter_select.py src/sixpack/ui/app.py tests/test_ui/test_screens.py tests/test_ui/test_app.py
git commit -m "Wire podcast episode playback end-to-end: chapter screen, app.py, live-verified"
```

---

## Self-Review

**Spec coverage:** All in-scope items from the spec are covered — data model (Task 1), API client (Task 2), `PodcastDetailScreen` (Task 3), browse dispatch (Task 4), player (Task 5), chapter screen + app wiring including the corrected (not copied-buggy) back-target state machine and live verification (Task 6). Explicitly out-of-scope items (next/prev episode, extra shelves, podcast-in-playlists) are not implemented anywhere in this plan, matching the spec. ✓

**Placeholder scan:** Task 6's Step 6 test (`test_on_progress_update_forwards_episode_id`) is deliberately flagged as needing a live-code check before finalizing its exact assertion shape — this is an explicit, bounded verification step with a clear fallback, not vague hand-waving; the requirement under test never changes. No other placeholders found.

**Type consistency:** `PodcastEpisode(id, library_item_id, title, audio_file, chapters)` (Task 1) is constructed identically in Tasks 3/4/5/6's test and implementation code. `PodcastDetailScreen.show_loading/load(show: LibraryItem, ...)` (Task 3) matches how Task 6 calls it. `play_podcast_episode(episode, show, start_time, server_url, token)` (Task 5) parameter order matches Task 6's one call site. `ChapterSelectScreen.podcast_episode_play_requested` emits `(show, episode, start_time)` (Task 6 Part A) matching Task 6 Part B's connected adapter signature. `_async_start_session(item_id, start_time, episode_id=None)` (Task 6) is called with the new 3rd arg only at the new podcast call site — the 3 pre-existing call sites are left as 2-arg calls, correctly relying on the new parameter's default.
