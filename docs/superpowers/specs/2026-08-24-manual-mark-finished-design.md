# Manual Mark Finished/Unfinished Design

## Problem

Audiobookshelf tracks "finished" by listening position reaching (close to)
the end of a file. That breaks down for audio that includes content the
user doesn't intend to listen to in full — bonus material, music suites,
or other non-narrative content appended after the story. Today there is no
way to mark an item finished (or revert a mistaken/premature finish)
except by actually playing through to the point ABS considers it done.

This adds a manual override, reachable from two places:

- **The player screen**, while an item is playing — for the primary case
  ("I'm done with this one, don't make me sit through the rest").
- **The series/playlist/podcast detail grids**, on a focused card — for
  fixing a mistake later, or finishing/unfinishing something without
  playing it at all.

## Non-goals

- Not touching `BrowseScreen`'s home-screen rows or its own "see all" grid.
  Those use a separate, custom card-grid implementation (not `FocusGrid`);
  confirmed out of scope for this pass.
- Not giving the player screen an unfinished-toggle. Actively playing
  something is virtually never already-finished; the rare "replay a
  finished book" case is handled by opening its card in the detail grid,
  which already supports both directions.
- Not persisting any local "recently marked" undo history. Reverting a
  mistake means re-opening the same card and toggling back — the existing
  finished/unfinished state (read from the server's own progress data) is
  the only source of truth.
- Not adding this to `ChapterSelectScreen`. Chapters aren't independently
  markable in Audiobookshelf's own progress model (progress is per
  library-item/episode, not per-chapter).

## Architecture

Two independent trigger mechanisms feeding the same downstream update:

**Player screen:** a new button in the existing control row (alongside
chapters/prev/rew/play/fwd/next/speed) — no new input primitive. Clicking
it (or focusing it and pressing Select, exactly like every other control
row button) opens a confirm popup; confirming stops playback, marks the
item finished, and hands off to the exact same "up next" flow that a
natural end-of-track already uses.

**Detail grids:** a genuine hold-Select gesture on `FocusGrid`. Every
other action a card supports (arrow navigation, Select-to-play, Back-to-
exit) already uses all six universal actions, so there's no spare input
left for "open this card's options" without one of two things: a new
button-shaped affordance per card (adds real estate and a new navigable
element to every card — larger change, worse fit for a TV grid), or
distinguishing a held Select from a tapped one. This picks the latter:
`FocusGrid` gains real press/release timing (a capability nothing in this
app has needed before), and a 500ms hold opens the same confirm popup,
now offering "mark finished" or "mark unfinished" depending on the card's
current state.

Both trigger paths end up emitting the same signal shape PlayerScreen's
`progress_update` already uses — `(item_id, current_time, duration,
is_finished, episode_id)` — so `app.py` needs no new async method, just
one more connection to the existing `_on_progress_update` slot, which
already calls `ABSClient.update_progress()` (already accepts
`is_finished`; no API-layer changes at all).

### Cross-input coverage

A hold gesture only works if "how long was this held" is actually known.
Real remotes overwhelmingly present to Linux as HID keyboards, so Qt's own
`keyPressEvent`/`keyReleaseEvent` pair (with `isAutoRepeat()` used to
ignore OS key-repeat noise) already covers keyboard *and* the common
remote case for free. True gamepads (evdev) are a separate, narrower path
that currently reports presses only — `gamepad.py`'s `_map_event` reacts
to `value == 1` and discards `value == 0` (release) entirely, and the
synthetic-key dispatch built for gamepad support (`app.py`'s
`_dispatch_gamepad_key`) only ever sends `QEvent.Type.KeyPress`. Both need
extending so a gamepad Select hold produces the same real press/release
timing a keyboard press does — otherwise gamepad users would have no way
to reach this feature at all on the grid screens, not even as a degraded
bonus path.

## Components

### `src/sixpack/ui/widgets/confirm_popup.py` (new)

A small reusable centered overlay, shared by `PlayerScreen` and
`DetailGridScreen` rather than building the same Cancel/Confirm dialog
twice. Not a `QDialog` (this app never uses modal Qt dialogs — every
existing overlay, e.g. the chapter overlay, is a plain child widget shown
on top of the host screen; matches that convention).

```python
class ConfirmPopup(QWidget):
    """Centered Cancel/Confirm confirmation overlay. The host screen is
    responsible for checking `.isVisible()` in its own keyPressEvent and
    forwarding via `handle_key()` before falling through to its normal
    handling -- exactly PlayerScreen's existing chapter-overlay
    convention, just extracted since two screens need it now.
    """

    confirmed = pyqtSignal()
    cancelled = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None: ...

    def show_confirm(
        self, message: str, confirm_label: str = "Confirm", cancel_label: str = "Cancel"
    ) -> None:
        """Shows the popup with Cancel focused by default (safer default
        for a state-changing action triggered by a hold gesture)."""

    def handle_key(self, action: InputAction) -> bool:
        """LEFT/RIGHT move focus between the two buttons, SELECT activates
        the focused one (emitting confirmed/cancelled and hiding), BACK
        always cancels regardless of focus. Returns True if the action was
        consumed (host should return immediately after calling this)."""
```

### `FocusGrid` changes (`src/sixpack/ui/widgets/focus_grid.py`)

- New signal: `long_press_activated = pyqtSignal(int)`.
- New `keyReleaseEvent` override (this widget has never needed one before).
- Select no longer activates on press. On a non-autorepeat Select press, a
  500ms single-shot `QTimer` starts; if it fires before release, this was
  a hold — emit `long_press_activated(self._focused_index)` and mark the
  press as "already resolved." On release, if the press was *not* already
  resolved as a hold, stop the timer and emit `item_activated` (the
  existing, unchanged behavior) — just now resolved on release instead of
  press, the standard and necessary trade-off for this pattern; it does
  not affect Select handling anywhere else in the app, since no other
  screen uses `FocusGrid`.
- Mouse double-click (`MediaCard.activated` → `item_activated`, wired in
  `add_item`) is untouched — long-press is a keyboard/gamepad-only concept
  here, matching that a mouse user already has a normal way to get a
  context action (this app doesn't do right-click menus; out of scope).

### `DetailGridScreen` changes (`src/sixpack/ui/screens/detail_grid.py`)

- New signal: `finished_changed = pyqtSignal(str, float, float, bool, str)`
  — same shape as `PlayerScreen.progress_update`, so `app.py` reuses
  `_on_progress_update` verbatim.
- New subclass contract method `_item_progress_ids(item) -> tuple[str, str | None]`
  returning `(item_id, episode_id)` for the `update_progress` API call —
  distinct from the existing `_item_key(item)`, which is the *progress
  dict lookup* key and differs from the API's `item_id` for podcast
  episodes specifically (`_item_key` returns the episode's own id;
  `update_progress` needs the show's library-item id as `item_id` and the
  episode's id as `episode_id` separately). `SeriesBook` →
  `(item.id, None)`; `PlaylistItem` → `(item.library_item_id,
  item.episode_id)`; `PodcastEpisode` → `(item.library_item_id, item.id)`.
- `self._finish_popup = ConfirmPopup(self)`, connected to a new
  `_toggle_finished(index)`:

```python
def _toggle_finished(self, index: int) -> None:
    if not (0 <= index < len(self._items)):
        return
    item = self._items[index]
    key = self._item_key(item)
    prog = self._progress.get(key)
    _fraction, finished = self._item_progress(item, self._progress)
    new_finished = not finished
    duration = item.duration
    current_time = duration if new_finished else (prog.current_time if prog else 0.0)
    item_id, episode_id = self._item_progress_ids(item)
    self.finished_changed.emit(item_id, current_time, duration, new_finished, episode_id or "")
    # Optimistic local update -- reflects immediately, no round trip wait.
    self._progress[key] = MediaProgress(
        libraryItemId=item_id, episodeId=episode_id,
        currentTime=current_time, duration=duration, isFinished=new_finished,
    )
    fraction, finished = self._item_progress(item, self._progress)
    self._grid._items[index].set_progress(fraction)
    self._grid._items[index].set_finished(finished)
```

`self._grid.long_press_activated.connect(...)` opens the popup (message
built from the card's current finished state via `_item_progress`);
popup's `confirmed` connects to a handler that calls `_toggle_finished`
with the index captured at open time.

`keyPressEvent` gains a leading check (matching the existing `BACK`-only
handling, extended):

```python
def keyPressEvent(self, event) -> None:
    from sixpack.input.actions import InputAction
    from sixpack.input.keyboard import key_to_action

    action = key_to_action(event.key())
    if self._finish_popup.isVisible():
        if self._finish_popup.handle_key(action):
            return
    if action == InputAction.BACK:
        self.back_requested.emit()
    else:
        super().keyPressEvent(event)
```

### `PlayerScreen` changes (`src/sixpack/ui/screens/player.py`)

- New control-row button (icon TBD — sourced from Material Icons
  Outlined's own codepoints file at implementation time, same process
  used for every existing icon in this app, never guessed), appended
  after the speed button. Added to `self._control_buttons`, so it's
  reachable via the row's existing Left/Right + Select handling with no
  changes to that logic.
- `self._finish_popup = ConfirmPopup(self)`; button click calls
  `self._finish_popup.show_confirm(f"Mark '{title}' as finished?",
  confirm_label="Mark Finished")`.
- `keyPressEvent` gets the same leading `self._finish_popup.isVisible()`
  check as the chapter overlay's, checked before the chapter-overlay
  block (only one overlay can be meaningfully open at a time in practice,
  but the check order makes that explicit rather than assumed).
- Confirm handler:

```python
def _on_finish_confirmed(self) -> None:
    self.progress_update.emit(
        self._item_id, self._position, self._duration, True, self._episode_id
    )
    self._player.stop()
    self.track_ended.emit()
```

Uses the *real* current position (`self._position`), not a fabricated
100% — this reflects where the user actually stopped, matching the design
already agreed for this trigger. `self._player.stop()` is required here
(unlike the natural end-of-track path, where mpv has already stopped
organically by the time `_handle_end_of_track` fires) since this fires
mid-playback. Reuses `track_ended` so `app.py`'s existing "up next"
navigation (`_on_track_ended`) handles what comes next identically to a
natural finish — no new navigation logic.

### `app.py` wiring

```python
self._detail_screen.finished_changed.connect(self._on_progress_update)
self._playlist_detail_screen.finished_changed.connect(self._on_progress_update)
self._podcast_detail_screen.finished_changed.connect(self._on_progress_update)
```

No new async method, no new `_on_result`/`_on_error` branches — this
reuses the `"progress"` fire-and-forget tag `_on_progress_update` already
dispatches through.

### `gamepad.py` changes

`_map_event`'s return type changes from `InputAction | None` to
`tuple[InputAction, bool] | None` (action, is_press). `EV_KEY` events now
react to both `value == 1` (press) and `value == 0` (release), ignoring
`value == 2` (repeat) same as before. `EV_ABS` (D-pad) events are
unaffected — navigation doesn't need hold detection, so they keep firing
once per direction with an implicit `is_press=True` and no release ever
sent. `GamepadListener.__init__`'s callback contract changes from
`Callable[[InputAction], None]` to `Callable[[InputAction, bool], None]`;
`_listen`'s loop unpacks and passes both through.

### `app.py`'s gamepad dispatch changes

`_on_gamepad_action(self, action: InputAction, is_press: bool)` — the
extra bool rides along through the existing `QMetaObject.invokeMethod`
marshal (`Q_ARG(bool, is_press)` alongside the existing `Q_ARG(int,
key.value)`). `_dispatch_gamepad_key` synthesizes `QEvent.Type.KeyPress`
or `QEvent.Type.KeyRelease` accordingly, instead of always `KeyPress`.

## Data flow

**Player screen, mark finished:** button click (or Select on the focused
button) → `show_confirm()` → user confirms → `progress_update.emit(...,
is_finished=True)` + `player.stop()` + `track_ended.emit()` →
`app.py._on_progress_update` persists it via `update_progress()` (fire-
and-forget, same as every other progress sync) → `app.py._on_track_ended`
runs the existing up-next flow.

**Detail grid, mark finished or unfinished:** hold Select on a focused
card (500ms) → `FocusGrid.long_press_activated` → popup opens with a
label reflecting the card's *current* state → user confirms →
`_toggle_finished()` flips it, updates the card in place, and emits
`finished_changed` → `app.py._on_progress_update` persists it.

**Cancelled, either surface:** Back, or Select on the Cancel button →
popup hides, nothing emitted, nothing sent to the server.

**Tapped, not held, on a grid card:** unchanged from today — plays the
item.

## Error handling

Persistence reuses the existing `progress_update` → `_on_progress_update`
→ `_async_update_progress` path verbatim, which is already fire-and-forget
(`self._worker.run("progress", ...)`, `_on_result`'s `"progress"` branch
is a deliberate no-op, `AsyncWorker._run_coro` logs any failure via
`logger.exception` — see the audit-fix pass). This feature adds no new
error handling: a failed `update_progress` call for a manual mark-finished
fails exactly as silently (logged, not surfaced to the user) as a failed
periodic sync during normal playback does today. Consistent with existing
behavior, not a regression — flagged here as a deliberate non-change
rather than an oversight.

## Testing

- `tests/test_ui/test_confirm_popup.py` (new): construction, `show_confirm`
  sets the message/labels and defaults focus to Cancel, `handle_key`'s
  Left/Right/Select/Back behavior, `confirmed`/`cancelled` signals fire
  correctly and hide the popup.
- `tests/test_ui/test_widgets.py` additions (FocusGrid section): a tap
  (`qtbot.keyClick`, press+release close together) still fires
  `item_activated` and not `long_press_activated`; a held press
  (`qtbot.keyPress` + `qtbot.wait()` past the threshold + `qtbot.keyRelease`)
  fires `long_press_activated` and not `item_activated`; releasing before
  the threshold cancels the pending timer cleanly (no double-fire);
  autorepeat presses/releases are ignored.
- `tests/test_ui/test_screens.py` (detail-grid section) additions:
  `_item_progress_ids` per subclass returns the right `(item_id,
  episode_id)` pairs; `_toggle_finished` on an unfinished item emits
  `finished_changed` with `is_finished=True` and `current_time == duration`,
  updates the card in place, and flips correctly on a second toggle
  (finished → unfinished, preserving/reconstructing a sensible
  `current_time`); popup message reflects current state correctly for
  both directions.
- `tests/test_ui/test_widgets.py` (PlayerScreen section) additions: the
  new button is reachable via existing Left/Right/Select control-row
  navigation; confirming emits `progress_update` with `is_finished=True`
  and the real current position (not duration); confirming calls
  `player.stop()` and emits `track_ended`.
- `tests/test_ui/test_app.py` additions: the three grids'
  `finished_changed` signals are connected to `_on_progress_update`
  (mirroring the existing `progress_update` connection test).
- `tests/test_input/test_gamepad.py` updates: existing tests asserting
  `gl._map_event(event) == InputAction.X` update to the new `(action,
  is_press)` tuple return; new tests cover release events (`value == 0`)
  returning `(action, False)`, and repeat events (`value == 2`) returning
  `None`.
