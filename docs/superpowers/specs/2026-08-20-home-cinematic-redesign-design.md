# SixPack — "Cinematic Dark" Home/Browse Redesign

**Date:** 2026-08-20
**Status:** Design — awaiting review
**Scope:** Visual polish + cinematic depth for the Home/Browse screen only (phase 1)

## Overview

SixPack is a PyQt6 10-foot client for Audiobookshelf, navigated by remote
control. The bones are solid (Kodi-style sidebar + horizontal card rows,
zone-based remote navigation, disk-backed cover cache) but the visual language
is flat: a single surface shade on near-black, a hard 3px focus border, and
text glyphs standing in for icons.

This redesign gives the Home/Browse screen a "cinematic dark" treatment —
layered depth, tactile focus feedback, and a blurred cover-art backdrop with a
reflective hero — matching the feel of Kodi / Plex / Jellyfin / Apple TV. The
navigation model is deliberately left untouched.

## Goals

- Layered, elevated dark palette replacing the single flat surface.
- Tactile focus feedback: focused card scales + gains an accent glow; siblings dim.
- A full-screen blurred cover-art backdrop behind the rows that cross-fades as focus moves.
- A reflective, **non-focusable** hero text overlay (title / author / meta) mirroring the focused item.
- Sidebar and iconography polish (library-type icons, active-item accent bar, styled "See all" chip, better placeholder cover).
- A dev-only offscreen screenshot harness for visual iteration against real merton.home data.

## Non-Goals (deferred to later phases)

- Layout changes to any screen other than Home/Browse (detail, player, chapter, login, series, playlists inherit the refreshed `theme.py` automatically, but keep their current layouts).
- Animated screen-to-screen transitions.
- Progress bars on browse cards / progress in the hero (browse rows don't currently load per-item progress; out of scope to avoid extra network fetches).
- Any change to the remote-navigation model in `browse.py` (zones, focus, key handling).

## Approved Decisions

1. **Backdrop strategy:** pre-blur each focused cover **once**, cache the
   blurred + scrimmed pixmap, and cross-fade between cached pixmaps (~200ms).
   A **dominant-color gradient** derived from the cover is shown instantly as a
   fallback while the blur is being computed (and permanently for items whose
   cover fails to load). Not live-blur (jank risk); not color-only (less depth).
2. **Hero:** a reflective, non-focusable text overlay that mirrors the focused
   card. It does NOT introduce a new focus zone.
3. **Accent:** keep the existing blue `#4a9eff`; add a glow variant token.

## Architecture

Five units, each independently testable:

### 1. `theme.py` — palette & tokens (edit)
- Add elevation shades (e.g. `SURFACE`, `SURFACE_HIGH`, plus a new low/`SURFACE_LOW`), a subtle background gradient definition, an accent **glow** color, and scrim gradient constants for the backdrop.
- Add focus-animation tokens: `FOCUS_SCALE` (~1.06–1.08), `FOCUS_ANIM_MS` (~130), `UNFOCUSED_DIM_OPACITY`.
- Keep all existing public names so other screens/tests keep working; only add and re-tune values.

### 2. `media_card.py` — tactile focus (edit)
- On `set_focused(True)`: animate scale up to `FOCUS_SCALE` over `FOCUS_ANIM_MS` via `QPropertyAnimation`, apply a `QGraphicsDropShadowEffect` in the accent glow color; on `False`: reverse.
- Unfocused cards render at `UNFOCUSED_DIM_OPACITY` (via a `QGraphicsOpacityEffect` or paint tweak) so the focused one stands out.
- Replace the `♪` placeholder with a cleaner generic cover (type-aware glyph/art).
- Must degrade gracefully under `QT_QPA_PLATFORM=offscreen` (tests run headless): animations/effects are set up but never block, and `set_focused` remains synchronous in its state change so existing assertions hold.

### 3. `cover_cache.py` — blurred-variant + dominant color (edit)
- Add `fetch_backdrop(url, token, callback)`: returns a processed backdrop
  `QPixmap` (blurred + darkened + scrim), cached to disk under a distinct key
  (e.g. hash of `"backdrop:" + url`) so it never collides with the raw cover.
- Add dominant-color extraction from a downloaded cover (downscale to ~1px /
  small average) returning a `QColor`; cheap and synchronous once bytes exist.
- Reuse the existing in-flight coalescing and eviction logic.

### 4. `backdrop.py` — new widget (new)
- A full-screen background widget holding two stacked layers for cross-fade.
- `show_for(item, dominant_color, backdrop_pixmap=None)`:
  - immediately paint the dominant-color gradient;
  - when the blurred pixmap arrives, cross-fade (~200ms `QPropertyAnimation` on opacity) from the outgoing layer to the new one.
- Purely presentational; owns no navigation state.

### 5. `browse.py` — integrate backdrop + hero + sidebar polish (edit)
- Insert the `Backdrop` widget behind the existing content (`QStackedLayout` with `StackAll`, or a positioned child at z-order 0). Rows/sidebar keep transparent backgrounds so the backdrop shows through where intended; a scrim keeps text legible.
- Add a reflective hero overlay (title big, author/subtitle, small meta line) positioned top-left over the backdrop. Updated from a single new method `_reflect_focus(item)`.
- Call `_reflect_focus(item)` + `backdrop.show_for(...)` from the existing focus-change points (`focus_card`, row change, grid focus) — these are the only new calls; no zone/key logic changes.
- Sidebar: per-`Library.media_type` icon, left-edge accent bar on the active item, refined spacing. Style the `See all` label as a chip. Refine row-title weight/letter-spacing.

## Data Flow

```
focus moves (existing key handler)
  → browse._reflect_focus(item)          # hero text
  → browse.backdrop.show_for(item, color)# instant gradient
  → cover_cache.fetch_backdrop(url,...)  # async blurred pixmap
      → backdrop cross-fades to blurred image when ready
```

Dominant color: computed from the raw cover the first time it's cached; stored
in-memory keyed by item id so repeated focus is instant.

## Error Handling

- No cover / failed download → backdrop stays on the dominant-color gradient (or a neutral theme gradient if color extraction also fails). Hero still shows text.
- Offscreen/headless (tests, CI) → effects and animations construct but are inert; all methods return synchronously with correct end-state so existing UI tests pass unchanged.
- Blur computation failure → fall back to the dominant-color gradient; never crash the browse screen.

## Testing

- **TDD for new non-visual logic:**
  - dominant-color extraction (deterministic given a known pixmap),
  - backdrop cache-key derivation (distinct from raw cover key),
  - hero text selection for each item type (LibraryItem / Series / Playlist),
  - `_reflect_focus` picks the right item on row/card/grid focus changes.
- **Existing UI tests must keep passing** (`tests/test_ui/test_widgets.py`, `test_browse_screen.py`, `test_screens.py`) with no assertion changes; run under offscreen platform.
- **Screenshots for the purely visual parts:** a dev-only offscreen harness (`tools/shots.py`, not packaged) authenticates to merton.home using the token at `~/.config/sixpack/token`, builds the browse screen with real covers, and renders 1920×1080 PNGs for before/after comparison. Excluded from coverage and the wheel.

## Rollout / Verification

1. Build harness; capture "before" screenshots of current browse.
2. Implement units 1→5 with tests; re-run full suite (must stay ≥80% coverage gate).
3. Capture "after" screenshots; iterate on the visuals until they hold up at 10ft.
4. Hand back to user with before/after images; final real-hardware check on cholet.home.

## File Summary

| File | Change |
|------|--------|
| `src/sixpack/ui/theme.py` | edit — palette, gradients, glow, focus/anim tokens |
| `src/sixpack/ui/widgets/media_card.py` | edit — scale+glow focus, dim siblings, placeholder |
| `src/sixpack/ui/cover_cache.py` | edit — `fetch_backdrop`, dominant color |
| `src/sixpack/ui/widgets/backdrop.py` | new — cross-fading backdrop widget |
| `src/sixpack/ui/screens/browse.py` | edit — backdrop + hero overlay + sidebar/icon polish |
| `tools/shots.py` | new — dev-only offscreen screenshot harness |
| `tests/test_ui/...` | new tests for the above logic |
