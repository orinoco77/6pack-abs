# Podcast Playback Support — Design

## Problem

Podcasts are currently unplayable in SixPack. Selecting a podcast item behaves
like selecting a book — it works enough to not crash, but produces a
playback session with no audio and no error. Root cause (confirmed live
against a real Audiobookshelf 2.31.0 server): a podcast library item is a
**show** (a container), not a directly-playable item — Audiobookshelf's data
model, playback endpoint, and progress-tracking endpoint are all genuinely
different from the audiobook shape SixPack currently assumes everywhere.

## Audiobookshelf's podcast data model (confirmed against a real server)

- `GET /api/libraries/{id}/items` (used for the "Recently Added" row) returns
  podcast **shows**. Each item's `media` has `numEpisodes`, `autoDownloadEpisodes`,
  etc. — no `duration`, `audioFiles`, or `tracks` the way a book's `media` does.
  Not playable directly.
- `GET /api/items/{id}` (the existing single-item detail endpoint, already used
  by SixPack for book chapter fetches) returns the SAME show, but with a full
  `media.episodes[]` array. Each episode has its own `id`, `title`, `chapters`,
  and `audioFile` (singular — one audio file per episode, with its own
  `duration`).
- `GET /api/libraries/{id}/personalized`'s `continue-listening` shelf (used for
  the "Continue Listening" row) returns shows too, but each entity carries an
  extra `recentEpisode` object — the specific in-progress episode. This is the
  one case where a podcast row entry IS meant to be played directly, matching
  how a book's Continue Listening entry plays directly.
- Playing a specific episode requires `POST /api/items/{libraryItemId}/play/{episodeId}`
  — confirmed live: the plain `/play` endpoint (what SixPack currently always
  uses) returns HTTP 200 but with `episodeId: null, duration: 0, audioTracks: []`
  — an empty, silently-useless session. This is the exact mechanism of today's
  bug.
- Progress is tracked per-episode: `GET/PATCH /api/me/progress/{libraryItemId}/{episodeId}`,
  confirmed to return `mediaItemType: "podcastEpisode"` records keyed by
  `episodeId`, not by the show's item id.

## Scope

**In scope:** browsing a podcast library (Continue Listening + Recently
Added rows), drilling into a show to see its episode list, playing an
episode (from the list or directly from Continue Listening), and correct
per-episode progress tracking.

**Out of scope for this pass** (noted here so they aren't silently dropped,
not because they're unimportant):
- Next/prev episode navigation or auto-advance in the player. Playback is
  single-episode: play one, return to the episode list on finish/back. This
  was an explicit user decision (2026-08-22) — series/playlist next-item
  behavior is NOT expected here, don't build it "for consistency."
- The `newest-episodes`/`listen-again` personalized shelves — not mapped to
  any row.
- Podcast episodes appearing inside user-created playlists — Audiobookshelf
  allows mixed-media playlists in principle; this pass does not add explicit
  handling, and playback of such an entry would still hit the same
  needs-an-episode-id problem this spec fixes elsewhere. A known gap, not a
  regression, and not addressed here.
- For a podcast library, the Series and Playlists rows are simply left
  empty — same visual as any other library that legitimately has none. No
  new row-hiding mechanism.

## Global Constraints

These apply to every task below — copied from this codebase's established,
repeatedly-enforced conventions (see recent git history for the incidents
that established each one):

- No `QGraphicsEffect` subclass anywhere, ever (`docs/qt-graphics-effect-crash.md`).
- Screen-owns-focus: any new screen must hold real Qt `StrongFocus` and drive
  its own `keyPressEvent`; child interactive widgets are `NoFocus`.
  `DetailGridScreen` (the base class `PodcastDetailScreen` extends) already
  does this correctly — inherit it, don't reinvent it.
- Any async fetch callback that can resolve after focus/selection has moved
  on (cover fetches, backdrop fetches, progress fetches) must use the
  established key-guard pattern (`set_expected_key`/tagged callback +
  `sip.isdeleted()` check for widget deletion) — copy the pattern already in
  `DetailGridScreen`/`PlaylistDetailScreen`, don't invent a new one.
- Tests that exercise navigation must drive real key events
  (`qtbot.keyClick` against whatever actually holds focus), not call
  internal handler methods directly, matching this codebase's established,
  hard-won convention (a past whole-plan review found a completely
  unreachable UI surface that only task-scoped tests calling methods
  directly had missed).
- Background-thread-into-Qt-object callbacks must guard against the
  target being deleted mid-flight (see the `sip.isdeleted()` pattern used
  for pairing/discovery in `login.py`) — not expected to be needed here
  since nothing new here crosses a real OS thread boundary, but keep it in
  mind if a task turns out to need one.
- Model fields follow this codebase's existing convention: snake_case
  Python names with `Field(..., alias="camelCase")` and
  `model_config = {"populate_by_name": True}`.

## Data model changes (`src/sixpack/api/models.py`)

New model:

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

`duration` lives under `audioFile.duration` in the real API response, not
at the episode's top level, so it's stored as a raw dict (matching
`LibraryItemMedia.audio_files: list[dict[str, Any]]`'s existing precedent
for untyped nested audio-file data in this file) with a computed property
— not a plain field.

Extend `LibraryItemMedia`:

```python
episodes: list[PodcastEpisode] = Field(default_factory=list)
```

Extend `LibraryItem`:

```python
recent_episode: PodcastEpisode | None = Field(None, alias="recentEpisode")
```

(`recent_episode` sits on `LibraryItem` directly, not `LibraryItemMedia` —
confirmed live, `recentEpisode` is a sibling of `media` in the shelf
entity, not nested inside it.)

## API client changes (`src/sixpack/api/client.py`)

```python
async def start_playback_session(
    self, item_id: str, start_time: float = 0.0, episode_id: str | None = None,
) -> PlaybackSession:
    path = f"/api/items/{item_id}/play"
    if episode_id:
        path = f"{path}/{episode_id}"
    ...  # same body/response handling as today, just the path changes
```

```python
async def get_progress(self, item_id: str, episode_id: str | None = None) -> MediaProgress | None:
    path = f"/api/me/progress/{item_id}"
    if episode_id:
        path = f"{path}/{episode_id}"
    ...  # unchanged otherwise

async def update_progress(
    self, item_id: str, current_time: float, duration: float,
    is_finished: bool = False, episode_id: str | None = None,
) -> None:
    path = f"/api/me/progress/{item_id}"
    if episode_id:
        path = f"{path}/{episode_id}"
    ...  # unchanged otherwise
```

Books never pass `episode_id` — fully backward compatible, no existing
call site needs to change except to keep not passing it.

## New screen: `PodcastDetailScreen` (`src/sixpack/ui/screens/podcast_detail.py`)

Subclasses `DetailGridScreen`, same shape as `PlaylistDetailScreen`
(`src/sixpack/ui/screens/playlist_detail.py` — read it in full before
implementing, it's ~55 lines and is the template to follow almost verbatim):

```python
class PodcastDetailScreen(DetailGridScreen):
    def _item_key(self, item: PodcastEpisode) -> str:
        return item.id

    def _item_progress(self, item: PodcastEpisode, progress: dict) -> tuple[float, bool]:
        # progress dict keyed by episode id, not library_item_id
        ...

    def _item_title(self, item: PodcastEpisode) -> str:
        return item.title

    def _item_subtitle(self, item: PodcastEpisode) -> str:
        return ""

    def _item_cover_url(self, item: PodcastEpisode, server_url: str, token: str) -> str | None:
        # episodes have no cover of their own — use the parent show's.
        # Store the show's LibraryItem (or just its id) on show_loading()/
        # load() so this method has something to build the URL from.
        ...

    def _item_media_type(self, item: PodcastEpisode) -> str:
        return "podcast"

    def show_loading(self, show: LibraryItem, server_url="", token="") -> None:
        self._populate(show.title, show.media.episodes, {}, server_url, token)

    def load(self, show: LibraryItem, progress: dict, server_url="", token="") -> None:
        self._populate(show.title, show.media.episodes, progress, server_url, token)

    def update_progress(self, progress: dict) -> None:
        self._refresh_progress(progress)
```

## Browse dispatch changes (`src/sixpack/ui/screens/browse.py`)

New signals on `BrowseScreen`:

```python
podcast_selected = pyqtSignal(object)          # LibraryItem (a show)
podcast_episode_selected = pyqtSignal(object, object)  # (LibraryItem show, PodcastEpisode)
```

`_emit_item` currently dispatches purely on `row_type`. Change the
"everything else" branch (today: `else: self.book_selected.emit(item)`) to
inspect the item's own shape first, since a podcast show can arrive via
EITHER the Continue Listening or Recently Added row and needs the same
handling regardless of which:

```python
else:
    if getattr(item, "media_type", "") == "podcast":
        if item.recent_episode is not None:
            self.podcast_episode_selected.emit(item, item.recent_episode)
        else:
            self.podcast_selected.emit(item)
    else:
        self.book_selected.emit(item)
```

`RowType.SERIES`/`RowType.PLAYLISTS` branches are untouched.

## App wiring changes (`src/sixpack/ui/app.py`)

**This section intentionally does not prescribe the exact back-target state
machine.** While researching it I traced `_on_playlist_item_activated` →
the real `tag == "playlist_item_chapters"` handler → `_on_playlist_item_play_requested`
by hand and found the wiring subtler than a quick read suggests (the
`_player_back_target`/`_chapter_back_target` ternary's exact correctness
under both branches wasn't something I could fully confirm from static
reading alone). I also found there are currently **two** `elif tag ==
"playlist_item_chapters":` blocks in `_on_result` (one live, one dead/
unreachable, since `elif` chains only ever match the first one) — a
pre-existing, unrelated anomaly worth a separate cleanup look sometime, not
something to fix as part of this feature, and not something to copy.

So: the plan for this task must have its author **read the real, live
playlist trio in full first** — `_on_playlist_item_activated`,
`_on_playlist_item_play_requested`, and the genuinely-reachable (first,
not any later duplicate) `tag == "playlist_item_chapters"` block in
`_on_result` — trace one single-chapter and one multi-chapter execution by
hand against the ACTUAL current code, confirm what `_player_back_target`/
`_chapter_back_target` end up as in each case, and mirror that exact,
verified structure for podcasts with `"podcast_detail"` substituted for
`"playlist_detail"` and episode/show types substituted for
item/playlist types. Do not port the paraphrase above — port the verified
real code.

What's needed either way, regardless of the exact state-machine wiring:

- `self._podcast_detail_screen = PodcastDetailScreen(cover_cache=self._cover_cache)`,
  added to `self._stack`, wired: `browse_screen.podcast_selected.connect(self._on_podcast_selected)`,
  `browse_screen.podcast_episode_selected.connect(self._on_podcast_episode_selected)`,
  `podcast_detail_screen.item_activated.connect(self._on_podcast_episode_activated)`,
  `podcast_detail_screen.back_requested.connect(self._show_browse)`.
- `_on_podcast_selected(show)` — mirrors `_on_playlist_selected`: show the
  detail screen, fetch per-episode progress via `get_progress(show.id, episode.id)`
  for each episode (same `asyncio.gather` + semaphore pattern as
  `_async_fetch_playlist_progress`), call `podcast_detail_screen.update_progress(...)`
  on a new `"podcast_detail"` worker tag.
- `_on_podcast_episode_activated(episode)` — the episode already has
  `chapters` inline (no extra `get_library_item`/worker round-trip needed
  to fetch them, unlike the playlist flow's `_async_get_book_chapters` —
  this task can branch on `len(episode.chapters) > 1` synchronously,
  immediately, no worker tag involved for this step). If `len(episode.chapters) > 1`,
  route to `ChapterSelectScreen` (needs a `load_from_podcast_episode`-style
  method there, or reuse `load_from_library_item` if the shapes are
  compatible enough — check `chapter_select.py`'s existing `load_from_*`
  methods before deciding whether a new one is warranted). Otherwise call
  `_on_podcast_episode_play_requested(episode, start_time)` directly. Track
  the parent show alongside the episode (needed for cover art and the
  episode-list back target) similarly to how `_on_playlist_item_activated`
  implicitly relies on `self._current_playlist` being set already by
  `_on_podcast_selected`.
- `_on_podcast_episode_play_requested(episode, start_time)` — mirrors
  `_on_playlist_item_play_requested` structurally, but simpler per the
  single-episode-only scope decision: no next/prev index bookkeeping.
  `"podcast_detail"` is a new back-target value for both
  `_player_back_target` and `_chapter_back_target` — add the corresponding
  branches in `_on_player_back`/`_on_chapter_back`, calling a new
  `_show_podcast_detail()` alongside the existing
  `_show_detail()`/`_show_playlist_detail()`. Calls
  `self._player_screen.play_podcast_episode(episode, show, start_time, self._server_url, self._token)`
  then `self._worker.run("start_session", self._async_start_podcast_session(show.id, episode.id, start_time))`
  (a new small async wrapper calling `client.start_playback_session(show.id, start_time, episode_id=episode.id)`).
- `_on_podcast_episode_selected(show, episode)` (from Continue Listening) —
  the embedded `recent_episode` already carries its `chapters` inline
  (confirmed live). This path has no intermediate detail screen (mirrors
  `_on_browse_book_selected`'s direct-from-browse book path, not the
  playlist/series detail-screen path) — trace `_on_browse_book_selected`
  and its `tag == "browse_book"` handler the same way, by hand, for this
  one, and use `"browse"` wherever that trio uses `"browse"`.
- Progress updates during playback: `_on_progress_update`'s signal now
  carries an episode id (see Player changes below) —
  `_async_update_progress` gains the same `episode_id: str = ""` parameter,
  passed through to `client.update_progress(...)`.

## Player changes (`src/sixpack/ui/screens/player.py`)

New method, modeled on `play_library_item` (standalone — no series/playlist
index tracking, per the single-episode scope decision):

```python
def play_podcast_episode(
    self, episode: PodcastEpisode, show: LibraryItem, start_time: float,
    server_url: str, token: str,
) -> None:
    self._reset_per_item_state()
    self._current_index = 0
    self._item_id = show.id          # cover/backdrop are per-show
    self._episode_id = episode.id    # progress/session need this too

    self._title_label.setText(episode.title)
    self._series_label.setText(show.title)
    self._episode_label.setText("")

    cover_url = show.cover_url(server_url, token)
    ...  # identical cover/backdrop fetch block to play_library_item's,
         # copy verbatim (same key-guard reasoning applies unchanged)

    self._server_url = server_url
    self._token = token
    self._sync_timer.start()
```

`self._episode_id` is a new field (default `""`, reset in
`_reset_per_item_state()` alongside the existing per-item fields it already
resets — read that method first, it's the established single place all
per-item state gets cleared, don't duplicate the reset logic elsewhere).

`progress_update` signal gains a 5th field:

```python
progress_update = pyqtSignal(str, float, float, bool, str)  # item_id, current_time, duration, is_finished, episode_id
```

The emit site (around line 531 as of this writing) passes
`self._episode_id` as the new final argument. Every existing emit path
(book/library-item/playlist playback) naturally passes `""` since
`_episode_id` only gets set by `play_podcast_episode`, and
`_reset_per_item_state()` clears it back to `""` for every other play
path — confirm this explicitly with a test, since it's the mechanism that
keeps book/playlist progress updates unaffected.

`app.py`'s `_on_progress_update` slot signature and its
`@pyqtSlot(...)` decorator both need the new `str` param added to match.

## Testing approach

- Unit tests for the new/changed model fields (`PodcastEpisode` parsing,
  `LibraryItem.recent_episode`/`episodes` parsing) against realistic
  fixture payloads shaped like the real API responses captured during this
  design's research (structure, not the actual show names/URLs).
- `ABSClient` tests via `respx`, following `test_api/test_client.py`'s
  existing pattern exactly (`async with respx.mock(base_url=...)`) — cover
  both the episode-id-present and episode-id-absent URL shapes for
  `start_playback_session`/`get_progress`/`update_progress`.
- `PodcastDetailScreen` tests following `test_playlist_screens.py`'s
  existing pattern (it's the closest twin — read it before writing new
  tests, don't reinvent the fixture/helper shapes it already established).
- `browse.py` dispatch tests: a podcast show item (no `recent_episode`)
  emits `podcast_selected`; a Continue-Listening-shaped item (with
  `recent_episode`) emits `podcast_episode_selected` with both the show and
  episode; a plain book item still emits `book_selected` unchanged
  (regression guard).
- `app.py` wiring tests following the existing playlist wiring tests'
  pattern (direct state-poking + real signal emission, matching this
  file's established style — see `test_pairing_login_succeeded_saves_token_and_proceeds`
  for the shape).
- `player.py` tests confirming `play_podcast_episode` sets `_item_id`/
  `_episode_id` correctly, and that `progress_update`'s emitted episode id
  is `""` for every OTHER play method (regression guard for the shared
  `_reset_per_item_state()` mechanism described above) — drive this via a
  REAL emitted signal (`qtbot.waitSignal` or a connected spy), not by
  reading the private field directly, so the test actually proves what the
  signal consumer (`app.py`) receives.
- At least one full live/manual verification against the real podcast
  library this design was researched against, the same way every other
  piece of work this session has been verified: launch the real app,
  navigate into a podcast show, play an episode, confirm audio plays and a
  progress record appears server-side keyed by episode id (`curl
  /api/me/progress/{itemId}/{episodeId}` before/after, matching the
  verification technique used during this design's own research).
