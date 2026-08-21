# App-Wide Cinematic Redesign — Design Spec

## Context

The Home/Browse screen (`browse.py`) already went through a "cinematic dark" redesign: layered palette, `Backdrop` (blurred cover-art wash), `MediaCard` (paint-level focus glow + dim), a reflective hero overlay, `FocusGrid` (wrapping-grid keyboard navigation). Every other screen in the app predates that redesign and still uses the original flat/plain styling. This spec covers bringing the rest of the app in line, and along the way removing dead code and reconsidering a few behaviors the visual work surfaced as questionable.

All work here targets the same constraints as the Home/Browse redesign: 10-ft TV viewing distance, remote-control-only input (no mouse, no keyboard as the primary path), the existing zone-based focus/navigation model, and `QT_QPA_PLATFORM=offscreen` test compatibility (see `docs/qt-graphics-effect-crash.md` — **no `QGraphicsEffect` subclass anywhere in this codebase**, all effects are paint-level).

## Goals

- Bring every reachable screen to the same visual language as Browse: dark layered palette, blurred `Backdrop`, consistent typography, `MediaCard`-based cards where content has real artwork.
- Remove unreachable dead code discovered during this pass.
- Fix the duplicate-code problem across `series_detail.py`/`playlist_detail.py`/`chapter_select.py` by building one shared shell rather than three parallel implementations.
- Reconsider auto-advance behavior now that "Play All" is being removed.
- Add a small set of player features (speed control, in-player chapter access, "up next") that the redesign work surfaced as natural additions.
- Replace remote-unfriendly text-entry login with a phone/laptop pairing flow, keeping an on-screen keyboard as a fallback.

## Non-Goals

- No changes to the underlying Audiobookshelf API client, data models, or sync/progress-tracking logic beyond what's needed for the end-of-book behavior change.
- No changes to Browse itself (already done).
- No gamepad-specific work beyond what already exists in `input/gamepad.py` — new interactions should work through the existing `InputAction` abstraction so gamepad support is inherited for free, not extended deliberately.
- Sleep timer — considered and explicitly deferred (not selected for this round).
- Any change to how the ABS server's own auth works — it's `POST /login` with username+password, nothing else; the pairing flow is built entirely on SixPack's side, not the server's.

## Architecture

Four phases, each independently shippable and separately committed/reviewed, in this order (later phases depend on earlier ones — Phase C's in-player chapter access depends on Phase B's chapter-list redesign existing):

### Phase A — Remove dead screens

`src/sixpack/ui/screens/library.py`, `series.py`, `playlists.py` are unreachable in the current app (traced fully — see conversation history / commit history around `e5002d6` which introduced Browse and superseded them). Delete:

- The three screen files and their corresponding test files.
- `app.py`: `LibraryScreen`/`SeriesScreen`/`PlaylistsScreen` construction, all their signal wiring (`library_selected`, `view_switch_requested`, the `series_screen`/`playlists_screen`-specific `back_requested`/`library_switch_requested` connections), `_show_libraries`/`_show_series`/`_show_playlists`, `_on_library_selected`, `_on_view_switch_requested`, `_on_playlist_library_selected` (confirm this one isn't reused by anything reachable before removing), and the `"series_list"`/`"playlists"` result-tag branches in `_on_result` that only these dead screens consumed.

**Verification:** full test suite green after removal; grep the codebase for any remaining reference to the removed class names to confirm nothing was missed.

### Phase B — Unified detail screen (episodes / playlist items / chapters)

**New shared component**, tentatively `DetailGridScreen` (exact name TBD at implementation time — pick whatever reads clearest once the shape is in code) in a new file, e.g. `src/sixpack/ui/screens/detail_grid.py`:

- Owns a `Backdrop` (reused as-is from `widgets/backdrop.py`), a hero area (title = static context — series/playlist name — set once on load; subtitle = dynamic, reflects the focused item's title + status, updated the same way Browse's `_reflect_focus` pattern already works), and a `FocusGrid` (reused as-is from `widgets/focus_grid.py`) populated with `MediaCard` instances.
- Subclassed/configured by `series_detail.py` (episodes) and `playlist_detail.py` (playlist items) — each supplies: how to build a `MediaCard` per item (title, subtitle, cover URL, progress), what "activate" does (play directly for single-track items, route to chapter selection for multi-chapter items — this logic already exists in `app.py`'s `_on_result` "browse_book" handling and in the existing `episode_activated`/`item_activated` signals; preserve it, just route through the new shell), and the back-navigation target.
- `MediaCard` gains a **finished badge**: a small checkmark/tick shown when progress indicates completion, alongside its existing `set_progress()` bar (already implemented, currently unused — reusing this over the deprecated `EpisodeItem`/`PlaylistItemWidget` dot+text progress language). Exact badge rendering (a small paint-level overlay, consistent with `_Scrim`/`_Glow`'s existing pattern — **not** a `QGraphicsEffect`) is an implementation detail; the requirement is: visually distinct at a glance, doesn't obscure the cover art's readability.

**`chapter_select.py`** gets its own redesign, not the card grid: chapters share one cover (the book's), so a grid of duplicate art is`nt useful. Instead: same `Backdrop` + hero shell (hero shows the book's title; since art doesn't change per-chapter, the backdrop's cross-fade is effectively a one-time settle rather than something that re-triggers per focus move — implementation should special-case this rather than force it through the per-item cross-fade path the grid screens use), but the list itself becomes a richer, cinematic version of today's `ChapterItem` rows: same bar+checkmark progress language as the cards, bigger typography, dim/glow-style focus feedback matching `MediaCard`'s visual weight even though it's a list row, not a card. This keeps one consistent progress vocabulary across the whole app while respecting that chapters aren't a "browse many distinct things" scenario the way episodes/playlist items are.

**"Play All" is removed entirely** — no button, no equivalent action. Underlying rationale (from design conversation): within one book, chapters already flow into each other via the player's own chapter handling, uninterrupted. Across a series or playlist, forcing a decision after each book is preferable to silently continuing.

**End-of-book behavior change** (`app.py`): today, `PlayerScreen._handle_end_of_track()` unconditionally emits `next_item`, and `_on_next_item()` auto-plays the next series book with no user input (playlist auto-advance is currently dead — `_on_next_item` only ever checks `self._current_series`, so a playlist item finishing does nothing). New behavior for both series and playlists: on end-of-track, return to the item's `DetailGridScreen` (or chapter list, if the book has no series/playlist context — see "standalone library items" below) with the *next* item pre-focused (`FocusGrid.focus_item(next_index)`), not auto-played. This replaces `_on_next_item`/`_on_prev_item`'s auto-play logic with pure navigation — the user presses Select if they want to continue.

*Open implementation detail, not requiring a design decision now:* standalone library items (played directly from Browse, no series/playlist context — see `play_library_item`) have no natural "next item" grid to return to. On finishing such an item, land back on Browse itself (closest existing equivalent of "nowhere further to go"). Flag this explicitly in the implementation plan so it's not silently dropped.

### Phase C — Player screen (Now Playing)

**Visual:** `Backdrop` behind the whole screen. Cover art grows substantially past the current fixed 280×280 (exact size TBD at implementation/visual-iteration time, same as Browse's own tuning pass — this is a "verify by screenshot, adjust" detail, not a number to lock in now). Progress bar restyled to match the app's accent/track palette instead of the default `QProgressBar` look. Transport control icons stay visually present (orientation + mouse fallback) but styled as static indicators, not implying focusability — this screen's real interaction model remains global remote-key actions via `keyPressEvent`, unchanged.

**New functionality:**
- **Playback speed control** — cycles a fixed step list (1.0× / 1.25× / 1.5× / 1.75× / 2.0×, wrapping) bound to a new `InputAction`, wired directly to `AudioPlayer` via a new `set_speed(float)` method (python-mpv exposes `speed` as a settable property directly — no new abstraction needed beyond that one method). Current speed shown somewhere in the transport area.
- **In-player chapter access** — an overlay/modal reusing Phase B's redesigned chapter-list shell, triggered by a new `InputAction`, so chapter-jumping doesn't leave the player or lose playback state. Selecting a chapter seeks via the player's existing `next_chapter`/`prev_chapter`/chapter-index machinery (extend as needed — `AudioPlayer` doesn't currently expose "seek to chapter N directly," only relative next/prev, so this needs a small addition, e.g. `seek_to_chapter(index: int)`).
- **"Up next" indicator** — shown briefly at end-of-track (ties directly into Phase B's end-of-book behavior change), naming what's next (the next episode/item's title) or indicating "end of series/playlist," before the screen transitions back to the grid/list. A short, non-interactive transitional state — not a new persistent UI element.

### Phase D — Login & Splash

**Login, pairing flow (primary path):**
1. `LoginScreen` (redesigned) starts a small local HTTP server (Python stdlib `http.server`/`socketserver`, or `httpx`'s async server equivalent if it fits the existing asyncio-worker pattern better — implementation's call) bound to the machine's LAN-reachable interface, on an ephemeral port.
2. Generates a random pairing code (short — e.g. 6 alphanumeric characters) with a short expiry (e.g. 10 minutes) and single-use semantics (invalidated after first successful submission).
3. Displays the code as text, plus a QR code encoding the local URL (`http://<lan-ip>:<port>/?code=<code>`), rendered directly via `QPainter` from the `qrcode` library's matrix output (`qrcode.QRCode().get_matrix()` or equivalent — avoids a Pillow dependency; draw filled `QRect`s per module). New dependency: `qrcode` (pure Python core; confirmed no Pillow requirement for matrix-only use).
4. The local server serves a minimal plain HTML form (server URL, username, password) at `/`, requires the pairing code (from the query string or a hidden field) to match and not be expired/used, and on submit performs the actual ABS `client.login(username, password)` call from the SixPack process itself (not the browser), saves the resulting token via the existing `AppConfig`/`ServerConfig` flow, and shows a simple "connected — you can return to the TV" confirmation page. The TV side polls or is notified (simplest: the local server sets a flag / calls back into the Qt event loop via a queued signal) and proceeds to `_show_browse()` exactly as autologin does today.
5. Security scope: LAN-only exposure (not internet-facing — same trust boundary ABS itself already sits in), single-use short-lived code, no persistent server (torn down once login completes or the screen is left). This is deliberately not hardened further (no TLS, no rate-limiting beyond the single-use code) — proportionate to a local network setup flow, not a general-purpose auth system.

**On-screen keyboard (fallback path):** reachable via an explicit action from the login screen ("use the remote instead" or similar). D-pad-navigable QWERTY-ish layout, same three fields (URL/username/password), styled consistently with the rest of the redesign. This is the existing `QLineEdit`-based flow's replacement input method, not a new screen — same fields, same `login_requested` signal, different input mechanism.

**Visual:** both paths get `Backdrop`/typography consistent with the rest of the app instead of today's plain centered form.

**Splash:** typography/spacing brought in line with existing font/color tokens (`FONT_HUGE`, `ACCENT`, etc. — already partially used). No structural change; low priority.

## Component Reuse Summary

| Component | Reused from | New use |
|---|---|---|
| `Backdrop` | `widgets/backdrop.py` | Series/playlist detail, chapter list, player, login |
| `FocusGrid` | `widgets/focus_grid.py` | Series/playlist detail card grids |
| `MediaCard` | `widgets/media_card.py` | Series/playlist detail cards (+ new finished-badge) |
| Hero pattern | `browse.py`'s `_reflect_focus`/hero widgets | Generalized into `DetailGridScreen`, static-title/dynamic-subtitle variant |

No `QGraphicsEffect` anywhere in any of this — finished badges, restyled progress bars, on-screen keyboard focus states, and QR rendering are all plain `QPainter`/stylesheet work, consistent with `docs/qt-graphics-effect-crash.md`'s standing rule.

## Error Handling

- Pairing server: port-in-use or bind failure falls back to the on-screen keyboard path automatically (with a brief inline note), rather than presenting a broken pairing screen.
- Pairing code expiry/reuse: the served HTML form shows a clear "code expired, generate a new one" state rather than a generic error.
- Existing error-handling patterns (ABS auth failures, network errors) carry over unchanged — this spec doesn't touch `LoginScreen.show_error`'s underlying flow, only how credentials get typed in.

## Testing

- Standard Qt offscreen test coverage for every new/changed widget, matching the existing project convention (`QT_QPA_PLATFORM=offscreen`, pytest-qt).
- `DetailGridScreen` and its two subclasses get shared test coverage for the base behavior (grid population, focus/hero reflection, end-of-book navigation) plus per-subclass tests for their specific activation logic.
- Pairing flow: the local HTTP server's request handling (code validation, expiry, single-use, successful-login path) is testable directly via `httpx`/`requests` against a real bound test-port instance, independent of Qt — no need to drive it through the GUI in tests.
- New `AudioPlayer` methods (`set_speed`, `seek_to_chapter`) get direct unit coverage against the existing player test patterns.

## Self-Review

- **Placeholder scan:** No TBDs left as open decisions — the two flagged "implementation detail, not a design decision" items (standalone-item end-of-book target, exact cover-art size on the player) are deliberately left to implementation/visual-iteration time, consistent with how the Browse redesign's own plan handled tuning values (`BACKDROP_DARKEN`, glow radius, etc. were tuned during implementation, not pre-specified).
- **Internal consistency:** Phase C's in-player chapter access and "up next" indicator both depend on Phase B's chapter-list shell and end-of-book behavior existing first — phase ordering in the plan must enforce this.
- **Scope:** four phases, each independently implementable and reviewable — matches the plan/spec granularity the writing-plans skill expects. Each phase can become its own task sequence.
- **Ambiguity check:** "Play All" removal and the end-of-book behavior change are stated as unconditional for both series and playlists, resolving the previous inconsistency (series auto-advanced, playlists silently didn't) into one consistent rule.
