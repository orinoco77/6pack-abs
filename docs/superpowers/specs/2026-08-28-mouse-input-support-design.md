# Mouse Input Support Design

## Problem

SixPack is built for a TV remote/gamepad-first, 10-foot UX: every custom
widget (`MediaCard`, `_SidebarItem`, `ChapterItem`) is constructed
`NoFocus` and driven entirely through each host screen's own
`keyPressEvent`/`keyReleaseEvent`. That's the right default, but it went
further than intended — a user running the app on a laptop currently has
no way to use their mouse at all for navigation-shaped content (cards,
sidebar entries, chapter rows). Only plain `QPushButton`s (player
controls, popups, login, update-prompt, on-screen keyboard) already work
with a mouse, since Qt gives those clicks for free regardless of focus
policy.

This restores mouse support everywhere a click naturally makes sense,
without weakening the keyboard/gamepad-first design: directional
navigation stays exclusively keyboard/gamepad (no D-pad-via-mouse
concept), and every mouse action reuses the exact method a keyboard
Select/hold already calls — there is no parallel "mouse activation"
logic anywhere.

## Non-goals

- No right-click context menus (existing, established non-goal in this
  app — see the mark-finished design).
- No hover-tracking on `PlayerScreen`'s control row. Its buttons are
  plain `QPushButton`s, already clickable natively; they're always all
  visible at once (not a scrollable list needing wayfinding), so
  hover-highlighting them buys little for the extra plumbing a hover
  signal on a stock `QPushButton` would need. Left/Right + Select stays
  the only way to move that row's highlight.
- No scroll-wheel-driven navigation. `QScrollArea`'s native wheel
  scrolling already works everywhere; once the user stops scrolling,
  ordinary hover (below) picks up whatever card is now under the
  pointer.
- No changes to `ConfirmPopup`, login, update-prompt, or the on-screen
  keyboard — all `QPushButton`/`QLineEdit`-based already and confirmed
  (by reading `app.py`'s cursor-autohide `eventFilter`, which never
  swallows events) to already receive mouse clicks with no interference.

## Architecture

One rule, applied to three widgets and their three host screens:

> A widget's `enterEvent` reports "the pointer is over me" upward; its
> host reacts by calling **the exact same focus-move method the
> keyboard already calls** for that position. A short click reports
> "activate me"; the host calls **the exact same activation method** a
> keyboard Select-tap already calls. Where a long-press-to-mark-finished
> gesture exists today (`MediaCard` only), a mouse-button hold past the
> same 500ms threshold — measured with the same wall-clock backstop
> `FocusGrid`/`BrowseScreen` already use for the keyboard gesture, so
> this doesn't reintroduce that already-fixed race — reports the same
> "long-press me" signal.

Concretely, each of `MediaCard`, `_SidebarItem`, and `ChapterItem` gains:

- `hovered = pyqtSignal()`, emitted from a new `enterEvent` override.
- `activated` (already exists on `MediaCard`/reused conceptually on the
  others) now fires on a **single** left-click release — not
  double-click. `MediaCard.mouseDoubleClickEvent` is removed; its
  `mousePressEvent`/`mouseReleaseEvent` pair takes over, matching normal
  click semantics (see below for the click-vs-hold split).
- `MediaCard` only: `long_pressed = pyqtSignal()`, from the same
  press/release pair once the 500ms threshold is crossed — mirroring
  `FocusGrid.keyPressEvent`/`keyReleaseEvent`'s existing hold detection
  field-for-field (`QTimer` + `QElapsedTimer` backstop), since a mouse
  hold can stall exactly the way a keyboard hold can.
- A pointing-hand cursor (`Qt.CursorShape.PointingHandCursor`), already
  set on `MediaCard`, added to `_SidebarItem` and `ChapterItem` for the
  same discoverability.
- A release outside the widget's own `rect()` cancels silently (no
  `activated`/`long_pressed`), matching standard button drag-off
  behavior — this is mouse-only; there's no keyboard equivalent to keep
  in sync with.

Each host then connects those signals, per item, to **its own existing,
unchanged handler** — the same one keyboard/gamepad Select already
reaches:

| Widget | Host | `hovered` connects to | `activated` connects to | `long_pressed` connects to |
|---|---|---|---|---|
| `MediaCard` (grids) | `FocusGrid.add_item` | `focus_item(idx)` | *(already wired: `item_activated.emit(idx)`)* | `long_press_activated.emit(idx)` |
| `MediaCard` (browse rows) | `_RowWidget.add_card` → re-emitted, `BrowseScreen` connects | zone-aware focus-move (below) | `_activate_row_item(row_idx, item_idx)` | `_on_select_long_press()` *(already index-free — see below)* |
| `MediaCard` (browse "see all" grid) | `BrowseScreen.populate_grid`/`_enter_grid` | `_set_grid_focus(idx)` | `_activate_grid_item(idx)` | `_on_select_long_press()` |
| `_SidebarItem` | `BrowseScreen._rebuild_sidebar` | sidebar focus-move (below) | sidebar select-equivalent (below) | — (no finished-state concept) |
| `ChapterItem` | `ChapterSelectScreen._populate_chapters` | `self._list.setCurrentRow(idx)` | `self._on_item_activated(list_item)` | — (chapters have no finished-state; see the original mark-finished design's non-goals) |

`BrowseScreen._on_select_long_press()` already reads "whichever item is
currently focused" via `_current_focused_item()` — it takes no index
argument today, so hover-driven focus-sync (below) makes a mouse hold
just work by calling it directly, no new plumbing needed there.

### Browse screen specifics

`BrowseScreen` has no single generic "focus index" — it's a zone machine
(`sidebar` / `rows` / `grid`) with per-row focus arrays. Hover on a row
card must therefore also make that row/zone the current one (mirroring
what `UP`/`DOWN` between rows already does), not just move the card
highlight within an already-focused row:

```python
def _on_row_card_hovered(self, row_idx: int, item_idx: int) -> None:
    if self._see_all_focused:
        self._set_see_all_focused(False)
    if self._zone != "rows" or self._focused_row != row_idx:
        if self._zone == "rows":
            self._row_widgets[self._focused_row].unfocus()
        self._zone = "rows"
        self._focused_row = row_idx
        self._update_row_styles()
    self._row_item_idxs[row_idx] = item_idx
    self._row_widgets[row_idx].focus_card(item_idx)
    self._reflect_current()
```

Hovering the "See all" label reuses `_set_see_all_focused(True)` (already
zone-agnostic-safe since it only touches the currently-focused row's
widget) plus the same row/zone sync above. Hovering a grid card while in
`grid` zone is just `_set_grid_focus(idx)`, already zone-correct.

Hovering a sidebar item is the sidebar-zone equivalent of the table
above:

```python
def _on_sidebar_item_hovered(self, idx: int) -> None:
    if self._zone != "sidebar":
        self._zone = "sidebar"
        self._update_row_styles()  # unfocus whatever was in rows/grid
    self._sidebar_idx = idx
    self._update_sidebar_styles()
    self._reflect_current()
```

Clicking a sidebar item reuses the existing `_handle_sidebar` bodies for
`RIGHT`/`SELECT` (open exit-confirm for index 0, `_enter_rows()`
otherwise) — extracted as a small `_activate_sidebar_item(idx)` called by
both the keyboard branch and the new mouse handler, so there's still one
implementation, not two.

### `_RowWidget` re-emission

`_RowWidget` sits between each `MediaCard` and `BrowseScreen`, so it
re-emits per-card signals with the card's index already resolved (same
shape as `FocusGrid.add_item`'s existing `activated` connection):

```python
card_hovered = pyqtSignal(int)
card_activated = pyqtSignal(int)
card_long_pressed = pyqtSignal(int)
see_all_hovered = pyqtSignal()
see_all_activated = pyqtSignal()

def add_card(self, card: MediaCard) -> None:
    ...
    idx = len(self._cards) - 1
    card.hovered.connect(lambda i=idx: self.card_hovered.emit(i))
    card.activated.connect(lambda i=idx: self.card_activated.emit(i))
    card.long_pressed.connect(lambda i=idx: self.card_long_pressed.emit(i))
```

`self._see_all` (a plain `QLabel`) gets an `eventFilter` installed on it
(mirroring `MediaCard._body`'s existing `installEventFilter(self)`
pattern) catching `QEvent.Type.Enter` → `see_all_hovered`,
`QEvent.Type.MouseButtonRelease` → `see_all_activated` (matching the
existing keyboard behavior noted in `keyPressEvent`'s comment: "See all"
activates immediately, no hold concept). It also gets
`Qt.CursorShape.PointingHandCursor`.

`BrowseScreen` connects each `_RowWidget`'s three `card_*`/two `see_all_*`
signals, per row index, when the row widget is constructed.

## Components

### `src/sixpack/ui/widgets/media_card.py`

- Remove `mouseDoubleClickEvent`.
- Add `hovered`, `long_pressed` signals.
- Add `enterEvent` → `self.hovered.emit()`.
- Add `mousePressEvent`/`mouseReleaseEvent`: press (left button only)
  starts a 500ms `QTimer` + `QElapsedTimer`, exactly mirroring
  `FocusGrid`'s fields; release checks `rect().contains(event.pos())`
  first (drag-off cancels silently), then resolves hold-vs-click the
  same way `FocusGrid.keyReleaseEvent` does (timer-fired flag OR elapsed
  backstop → `long_pressed`; otherwise → `activated`).

### `src/sixpack/ui/widgets/focus_grid.py`

- `add_item`: connect the new `widget.hovered` (if present, same
  `hasattr` guard already used for `activated`) to
  `lambda: self.focus_item(index)`, and `widget.long_pressed` (if
  present) to `lambda: self.long_press_activated.emit(index)`.
  `item_activated`'s existing `activated` connection is unchanged.

### `src/sixpack/ui/screens/detail_grid.py`, `series_detail.py`, `playlist_detail.py`, `podcast_detail.py`

No changes — they only ever talk to `FocusGrid`'s public signals, which
already cover the new mouse paths transparently.

### `src/sixpack/ui/screens/browse.py`

- `_SidebarItem`: add `hovered`/`activated` signals,
  `enterEvent`/`mousePressEvent`/`mouseReleaseEvent` (click only — no
  hold concept for sidebar items), pointing-hand cursor.
- `_RowWidget`: re-emission signals and `_see_all` event filter, as
  above.
- `BrowseScreen`:
  - `_rebuild_sidebar`: connect each `_SidebarItem`'s `hovered`/
    `activated` by index to the new `_on_sidebar_item_hovered`/
    `_activate_sidebar_item` methods.
  - Row construction: connect each `_RowWidget`'s re-emitted signals by
    row index to `_on_row_card_hovered`/`_activate_row_item`/
    `_on_select_long_press`, and `see_all_hovered`/`see_all_activated`
    to the "See all" focus-sync + `_trigger_see_all()`.
  - `populate_grid`/`_enter_grid`: connect each grid `MediaCard`'s
    `hovered`/`activated`/`long_pressed` by index to `_set_grid_focus`/
    `_activate_grid_item`/`_on_select_long_press`.
  - Extract `_activate_sidebar_item(idx)` from the body of
    `_handle_sidebar`'s `RIGHT`/`SELECT` branch so keyboard and mouse
    share one implementation.

### `src/sixpack/ui/screens/chapter_select.py`

- `ChapterItem`: add `hovered`/`activated` signals,
  `enterEvent`/`mousePressEvent`/`mouseReleaseEvent` (click only — no
  hold concept, matching the original mark-finished design's explicit
  chapter non-goal), pointing-hand cursor.
- `_populate_chapters`: connect each `ChapterItem`'s `hovered` to
  `self._list.setCurrentRow(i)` and `activated` to
  `lambda: self._on_item_activated(list_item)` (capturing the specific
  `QListWidgetItem`, matching what `keyPressEvent`'s `SELECT` branch
  already passes via `self._list.currentItem()`).

## Data flow

**Hover, any screen:** `enterEvent` → widget's `hovered` → host's
existing focus-move method (`focus_item`/`_set_grid_focus`/row-and-zone
sync/`setCurrentRow`) → same visual highlight + `ensureWidgetVisible`/
`focus_changed` a keyboard arrow press already produces.

**Click, any screen:** `mouseReleaseEvent` (release still inside the
widget, under the 500ms threshold) → widget's `activated` → host's
existing activation method → identical downstream behavior (play a
book, open a series, switch a library, jump to a chapter) to a keyboard
Select-tap.

**Click-and-hold on a book/podcast card (`MediaCard` only):** past
500ms → widget's `long_pressed` → `FocusGrid.long_press_activated` /
`BrowseScreen._on_select_long_press()` → the existing mark-finished
popup, unchanged.

**Drag-off:** release outside the widget's `rect()` → nothing emitted,
matching a normal button.

## Testing

- `tests/test_ui/test_widgets.py` (`MediaCard` section): `enterEvent`
  emits `hovered`; a quick press+release emits `activated` and not
  `long_pressed`; a held press (`time.sleep` past 500ms, mirroring the
  existing `FocusGrid` race test) emits `long_pressed` and not
  `activated`; release outside `rect()` emits neither;
  `mouseDoubleClickEvent` no longer exists / double-click behaves as two
  independent single clicks.
- `tests/test_ui/test_widgets.py` (`FocusGrid` section): a `MediaCard`'s
  `hovered` moves grid focus to its index; `long_pressed` fires
  `long_press_activated` with that index.
- `tests/test_ui/test_screens.py` (chapter-select section): a
  `ChapterItem`'s `hovered` moves `_list.currentRow`; `activated` fires
  the same `play_requested`/etc. signal a keyboard Select-tap does.
- `tests/test_ui/test_screens.py` (browse section, new): sidebar item
  hover switches zone/highlight; sidebar item click enters rows (or
  opens exit-confirm for index 0); row card hover syncs zone + row +
  item index; row card click activates the right item; "See all" hover/
  click behave like today's keyboard path; grid card hover/click/hold
  behave like today's keyboard path in grid zone.
