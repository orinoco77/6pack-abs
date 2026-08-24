# Manual Mark Finished/Unfinished Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user manually mark an item finished (or revert a mistaken/premature finish) from the player screen (a control-row button) and from the series/playlist/podcast detail grids (a hold-Select gesture on a focused card), for content that shouldn't count toward natural completion (e.g. trailing bonus material).

**Architecture:** A new reusable `ConfirmPopup` widget (Cancel/Confirm overlay, same non-modal-child-widget convention as the existing chapter overlay) is shared by `PlayerScreen` and `DetailGridScreen`. Both surfaces end up emitting the same `(item_id, current_time, duration, is_finished, episode_id)` signal shape `PlayerScreen.progress_update` already uses, so `app.py` needs no new async method — just more connections to the existing `_on_progress_update` slot, which already calls `ABSClient.update_progress()` (already accepts `is_finished`). The grid's hold-Select gesture requires real press/release timing in `FocusGrid` (new capability) and, for gamepad parity, in `gamepad.py` and `app.py`'s synthetic-key dispatch (both currently press-only).

**Tech Stack:** PyQt6, pytest + pytest-qt (all existing). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-24-manual-mark-finished-design.md`

## Global Constraints

- Python ≥ 3.10 (dev/target 3.12). Line length 100. Ruff `select = ["E","F","I","UP","B","C4","SIM","RUF","PERF"]` — this is the full expanded ruleset; run `ruff check` (not just a diff against pre-existing violations) on every file this plan touches, since the whole tree is currently clean.
- All Qt tests run under `QT_QPA_PLATFORM=offscreen` (default via `tests/conftest.py`).
- Coverage gate: `--cov-fail-under=85`. `src/sixpack/ui/app.py` is excluded from coverage (`pyproject.toml`'s `[tool.coverage.run] omit`); every other file this plan touches or creates is NOT excluded and needs real coverage.
- Tests run sequentially by default (`pytest-xdist` is installed but NOT wired into `addopts` — a prior session found it crashes real CI workers under this Qt test suite; do not add `-n auto` back).
- Icon glyphs are real Private-Use-Area Unicode characters from the bundled Material Icons Outlined font — they render as invisible/blank in a terminal or a tool call's visible text, but ARE the correct character when typed directly. Editing an *existing* invisible glyph in a file via a plain string-match `Edit` call is unreliable (the exact bytes don't visually match what you type); Task 4 gives the exact safe technique (a small inline Python script using `chr(codepoint)`) — use it verbatim, don't try a direct `Edit` on `theme.py`'s icon lines.
- Confirmed codepoint for the new icon (from Google's own `MaterialIconsOutlined-Regular.codepoints` file, not guessed): `check_circle` = `0xE86C`.
- `self._progress` on `DetailGridScreen` and its subclasses holds `dict[str, MediaProgress]` in production (confirmed: `series_detail.py`/`playlist_detail.py`/`podcast_detail.py`'s `load()`/`update_progress()` all type-hint it that way) — Task 3 also updates `tests/test_ui/test_detail_grid.py`'s test-only fake subclass to use real `MediaProgress` instances instead of plain dicts, so the base class's new `_toggle_finished()` can rely on that shape uniformly rather than adding extra abstract methods just to keep a simplified test double happy.
- Commit after each task. Branch: `feature/mark-finished` (already checked out, based on `main`, with the spec doc as the branch's only prior commit).

---

## File Structure

| File | Change |
|------|--------|
| `src/sixpack/ui/widgets/confirm_popup.py` (new) | `ConfirmPopup` — reusable Cancel/Confirm overlay |
| `src/sixpack/ui/widgets/focus_grid.py` (edit) | `long_press_activated` signal; real press/release hold detection on Select |
| `src/sixpack/ui/screens/detail_grid.py` (edit) | `_item_progress_ids` subclass contract; `finished_changed` signal; `_toggle_finished`; popup wiring |
| `src/sixpack/ui/screens/series_detail.py` (edit) | `_item_progress_ids` implementation |
| `src/sixpack/ui/screens/playlist_detail.py` (edit) | `_item_progress_ids` implementation |
| `src/sixpack/ui/screens/podcast_detail.py` (edit) | `_item_progress_ids` implementation |
| `src/sixpack/ui/screens/player.py` (edit) | New control-row button + popup + confirm handler |
| `src/sixpack/ui/theme.py` (edit) | `ICON_CHECK_CIRCLE` constant |
| `src/sixpack/ui/app.py` (edit) | Connect the three grids' `finished_changed` to existing `_on_progress_update` |
| `src/sixpack/input/gamepad.py` (edit) | `_map_event`/`GamepadListener` callback contract gains press/release |
| `tests/test_ui/test_confirm_popup.py` (new) | `ConfirmPopup` tests |
| `tests/test_ui/test_widgets.py` (edit) | `FocusGrid` hold-detection tests; `PlayerScreen` new-button tests |
| `tests/test_ui/test_detail_grid.py` (edit) | `_TestScreen`/`_FakeItem` updated to real `MediaProgress`; new `_toggle_finished`/`_item_progress_ids` tests |
| `tests/test_ui/test_screens.py` (edit) | `_item_progress_ids` test for `SeriesDetailScreen` |
| `tests/test_ui/test_playlist_screens.py` (edit) | `_item_progress_ids` test for `PlaylistDetailScreen` |
| `tests/test_ui/test_podcast_detail.py` (edit) | `_item_progress_ids` test for `PodcastDetailScreen` |
| `tests/test_ui/test_app.py` (edit) | `finished_changed` wiring tests |
| `tests/test_input/test_gamepad.py` (edit) | Updated for the new `(action, is_press)` tuple contract |

---

## Task 1: `ConfirmPopup` widget

**Files:**
- Create: `src/sixpack/ui/widgets/confirm_popup.py`
- Test: `tests/test_ui/test_confirm_popup.py`

**Interfaces:**
- Produces:
  - `class ConfirmPopup(QWidget)`
  - `show_confirm(message: str, confirm_label: str = "Confirm", cancel_label: str = "Cancel") -> None`
  - `handle_key(action: InputAction | None) -> None` — host calls this (and unconditionally returns from its own `keyPressEvent`) whenever `self._finish_popup.isVisible()` is true, mirroring `PlayerScreen`'s existing chapter-overlay convention.
  - Signals: `confirmed = pyqtSignal()`, `cancelled = pyqtSignal()`
  - Starts hidden (`self.hide()` in `__init__`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ui/test_confirm_popup.py`:

```python
"""Tests for ConfirmPopup -- the reusable Cancel/Confirm overlay shared by
PlayerScreen and DetailGridScreen."""
from __future__ import annotations

from sixpack.input.actions import InputAction
from sixpack.ui.widgets.confirm_popup import ConfirmPopup


def test_starts_hidden(qtbot):
    popup = ConfirmPopup()
    qtbot.addWidget(popup)
    assert not popup.isVisible()


def test_show_confirm_sets_message_and_labels(qtbot):
    popup = ConfirmPopup()
    qtbot.addWidget(popup)
    popup.show_confirm("Mark 'Book A' as finished?", confirm_label="Mark Finished")
    assert popup._message_label.text() == "Mark 'Book A' as finished?"
    assert popup._confirm_btn.text() == "Mark Finished"
    assert popup._cancel_btn.text() == "Cancel"
    assert popup.isVisible()


def test_show_confirm_defaults_focus_to_cancel(qtbot):
    popup = ConfirmPopup()
    qtbot.addWidget(popup)
    popup.show_confirm("Are you sure?")
    assert popup._focus_index == 0


def test_right_moves_focus_to_confirm(qtbot):
    popup = ConfirmPopup()
    qtbot.addWidget(popup)
    popup.show_confirm("Are you sure?")
    popup.handle_key(InputAction.RIGHT)
    assert popup._focus_index == 1


def test_right_does_not_move_past_confirm(qtbot):
    popup = ConfirmPopup()
    qtbot.addWidget(popup)
    popup.show_confirm("Are you sure?")
    popup.handle_key(InputAction.RIGHT)
    popup.handle_key(InputAction.RIGHT)
    assert popup._focus_index == 1


def test_left_does_not_move_before_cancel(qtbot):
    popup = ConfirmPopup()
    qtbot.addWidget(popup)
    popup.show_confirm("Are you sure?")
    popup.handle_key(InputAction.LEFT)
    assert popup._focus_index == 0


def test_select_on_confirm_emits_confirmed_and_hides(qtbot):
    popup = ConfirmPopup()
    qtbot.addWidget(popup)
    popup.show_confirm("Are you sure?")
    popup.handle_key(InputAction.RIGHT)
    received = []
    popup.confirmed.connect(lambda: received.append(True))

    popup.handle_key(InputAction.SELECT)

    assert received == [True]
    assert not popup.isVisible()


def test_select_on_cancel_emits_cancelled_and_hides(qtbot):
    popup = ConfirmPopup()
    qtbot.addWidget(popup)
    popup.show_confirm("Are you sure?")
    received = []
    popup.cancelled.connect(lambda: received.append(True))

    popup.handle_key(InputAction.SELECT)  # still focused on Cancel by default

    assert received == [True]
    assert not popup.isVisible()


def test_back_always_cancels_regardless_of_focus(qtbot):
    popup = ConfirmPopup()
    qtbot.addWidget(popup)
    popup.show_confirm("Are you sure?")
    popup.handle_key(InputAction.RIGHT)  # move to Confirm
    received = []
    popup.cancelled.connect(lambda: received.append(True))

    popup.handle_key(InputAction.BACK)

    assert received == [True]


def test_reopening_resets_focus_to_cancel(qtbot):
    popup = ConfirmPopup()
    qtbot.addWidget(popup)
    popup.show_confirm("First message")
    popup.handle_key(InputAction.RIGHT)
    assert popup._focus_index == 1

    popup.show_confirm("Second message")
    assert popup._focus_index == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_confirm_popup.py -v --no-cov`
Expected: FAIL — `ModuleNotFoundError: No module named 'sixpack.ui.widgets.confirm_popup'`.

- [ ] **Step 3: Implement**

Create `src/sixpack/ui/widgets/confirm_popup.py`:

```python
"""Reusable centered Cancel/Confirm confirmation overlay, shared by
PlayerScreen and DetailGridScreen (see the manual mark-finished design
spec). Not a QDialog -- this app never uses modal Qt dialogs; every
existing overlay (e.g. PlayerScreen's chapter overlay) is a plain child
widget shown on top of its host screen, and this follows the same
convention.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from sixpack.input.actions import InputAction
from sixpack.ui import theme


class ConfirmPopup(QWidget):
    """Host screens must check `.isVisible()` in their own keyPressEvent
    and call `handle_key(action)` (then unconditionally return) before
    falling through to normal handling -- see PlayerScreen's existing
    chapter-overlay convention, now shared by two screens. `handle_key`
    always consumes the key while visible; it has no return value because
    every caller's usage is unconditional "call it, then return" while
    the popup is up.
    """

    confirmed = pyqtSignal()
    cancelled = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._focus_index = 0  # 0 = Cancel, 1 = Confirm -- safer default
        self._build_ui()
        self.hide()

    def _build_ui(self) -> None:
        self.setStyleSheet(
            f"background: {theme.SURFACE}; border: 2px solid {theme.ACCENT}; "
            f"border-radius: 8px;"
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(20)

        self._message_label = QLabel("")
        self._message_label.setWordWrap(True)
        self._message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._message_label.setStyleSheet(
            f"color: {theme.TEXT_PRIMARY}; font-size: {theme.FONT_BODY}pt; "
            f"background: transparent; border: none;"
        )
        outer.addWidget(self._message_label)

        button_row = QHBoxLayout()
        button_row.setSpacing(16)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._cancel_btn.clicked.connect(self._activate_cancel)
        self._confirm_btn = QPushButton("Confirm")
        self._confirm_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._confirm_btn.clicked.connect(self._activate_confirm)
        button_row.addWidget(self._cancel_btn)
        button_row.addWidget(self._confirm_btn)
        outer.addLayout(button_row)
        self._buttons = [self._cancel_btn, self._confirm_btn]

    def show_confirm(
        self, message: str, confirm_label: str = "Confirm", cancel_label: str = "Cancel"
    ) -> None:
        self._message_label.setText(message)
        self._confirm_btn.setText(confirm_label)
        self._cancel_btn.setText(cancel_label)
        self._focus_index = 0
        self._reflect_focus()
        self.show()
        self.raise_()

    def handle_key(self, action: InputAction | None) -> None:
        if action == InputAction.BACK:
            self._activate_cancel()
        elif action == InputAction.LEFT:
            self._focus_index = max(0, self._focus_index - 1)
            self._reflect_focus()
        elif action == InputAction.RIGHT:
            self._focus_index = min(len(self._buttons) - 1, self._focus_index + 1)
            self._reflect_focus()
        elif action == InputAction.SELECT:
            self._buttons[self._focus_index].click()
        # Anything else is silently swallowed too -- the popup owns all
        # input while visible, matching the chapter overlay's convention.

    def _reflect_focus(self) -> None:
        for i, btn in enumerate(self._buttons):
            border = theme.ACCENT if i == self._focus_index else "transparent"
            btn.setStyleSheet(
                f"background: {theme.SURFACE_HIGH}; color: {theme.TEXT_PRIMARY}; "
                f"border: 2px solid {border}; border-radius: 6px; padding: 8px 20px; "
                f"font-size: {theme.FONT_BODY}pt;"
            )

    def _activate_cancel(self) -> None:
        self.hide()
        self.cancelled.emit()

    def _activate_confirm(self) -> None:
        self.hide()
        self.confirmed.emit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_confirm_popup.py -v --no-cov`
Expected: all tests PASS.

- [ ] **Step 5: Lint**

Run: `.venv/bin/ruff check src/sixpack/ui/widgets/confirm_popup.py tests/test_ui/test_confirm_popup.py`
Expected: clean (new files, nothing pre-existing to inherit).

- [ ] **Step 6: Commit**

```bash
git add src/sixpack/ui/widgets/confirm_popup.py tests/test_ui/test_confirm_popup.py
git commit -m "Add ConfirmPopup: reusable Cancel/Confirm overlay"
```

---

## Task 2: `FocusGrid` hold-Select detection

**Files:**
- Modify: `src/sixpack/ui/widgets/focus_grid.py`
- Test: `tests/test_ui/test_widgets.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: new signal `long_press_activated = pyqtSignal(int)` on `FocusGrid`. `item_activated` keeps its existing signature and meaning (still fires on a short tap) but now resolves on key *release* instead of press — this only affects `FocusGrid`; no other screen in this app uses this widget.

- [ ] **Step 1: Write the failing tests**

Read `tests/test_ui/test_widgets.py`'s existing `FocusGrid` section first (search for `class FocusGrid` usage / `# ===` `FocusGrid tests` header near the top of the file) for this project's construction conventions (`FocusGrid(columns=N)`, `qtbot.addWidget`, adding real focusable child widgets via `add_item`).

Add to `tests/test_ui/test_widgets.py`, in the `FocusGrid` tests section:

```python
def test_short_tap_fires_item_activated_not_long_press(qtbot):
    from sixpack.ui.widgets.focus_grid import FocusGrid
    from sixpack.ui.widgets.media_card import MediaCard

    grid = FocusGrid(columns=3)
    qtbot.addWidget(grid)
    grid.add_item(MediaCard(title="A"))
    grid.show()
    grid.setFocus()

    activated = []
    long_pressed = []
    grid.item_activated.connect(lambda idx: activated.append(idx))
    grid.long_press_activated.connect(lambda idx: long_pressed.append(idx))

    qtbot.keyClick(grid, Qt.Key.Key_Return)  # press+release, near-instant

    assert activated == [0]
    assert long_pressed == []


def test_held_select_fires_long_press_not_item_activated(qtbot):
    from sixpack.ui.widgets.focus_grid import FocusGrid
    from sixpack.ui.widgets.media_card import MediaCard

    grid = FocusGrid(columns=3)
    qtbot.addWidget(grid)
    grid.add_item(MediaCard(title="A"))
    grid.show()
    grid.setFocus()

    activated = []
    long_pressed = []
    grid.item_activated.connect(lambda idx: activated.append(idx))
    grid.long_press_activated.connect(lambda idx: long_pressed.append(idx))

    qtbot.keyPress(grid, Qt.Key.Key_Return)
    qtbot.wait(600)  # past the 500ms hold threshold
    qtbot.keyRelease(grid, Qt.Key.Key_Return)

    assert long_pressed == [0]
    assert activated == []


def test_release_before_threshold_does_not_double_fire(qtbot):
    """Releasing just under the threshold must fire exactly one signal
    (item_activated), never both."""
    from sixpack.ui.widgets.focus_grid import FocusGrid
    from sixpack.ui.widgets.media_card import MediaCard

    grid = FocusGrid(columns=3)
    qtbot.addWidget(grid)
    grid.add_item(MediaCard(title="A"))
    grid.show()
    grid.setFocus()

    activated = []
    long_pressed = []
    grid.item_activated.connect(lambda idx: activated.append(idx))
    grid.long_press_activated.connect(lambda idx: long_pressed.append(idx))

    qtbot.keyPress(grid, Qt.Key.Key_Return)
    qtbot.wait(100)
    qtbot.keyRelease(grid, Qt.Key.Key_Return)
    qtbot.wait(600)  # let any (incorrect) pending timer fire, if it exists

    assert activated == [0]
    assert long_pressed == []


def test_long_press_uses_currently_focused_index(qtbot):
    from sixpack.ui.widgets.focus_grid import FocusGrid
    from sixpack.ui.widgets.media_card import MediaCard

    grid = FocusGrid(columns=3)
    qtbot.addWidget(grid)
    for title in ("A", "B", "C"):
        grid.add_item(MediaCard(title=title))
    grid.show()
    grid.setFocus()
    grid.focus_item(2)

    long_pressed = []
    grid.long_press_activated.connect(lambda idx: long_pressed.append(idx))

    qtbot.keyPress(grid, Qt.Key.Key_Return)
    qtbot.wait(600)
    qtbot.keyRelease(grid, Qt.Key.Key_Return)

    assert long_pressed == [2]


def test_non_select_keys_still_work_during_a_pending_hold(qtbot):
    """Left/Right navigation must not be blocked by an in-progress Select
    hold timer -- only release/hold detection is special-cased."""
    from sixpack.ui.widgets.focus_grid import FocusGrid
    from sixpack.ui.widgets.media_card import MediaCard

    grid = FocusGrid(columns=3)
    qtbot.addWidget(grid)
    for title in ("A", "B"):
        grid.add_item(MediaCard(title=title))
    grid.show()
    grid.setFocus()

    qtbot.keyPress(grid, Qt.Key.Key_Return)
    qtbot.keyClick(grid, Qt.Key.Key_Right)
    qtbot.keyRelease(grid, Qt.Key.Key_Return)

    assert grid._focused_index == 1
```

(These tests need `from PyQt6.QtCore import Qt` in scope — confirm it's already imported near the top of `tests/test_ui/test_widgets.py`; it is, per the file's existing `FocusGrid`/`MediaCard` tests.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_widgets.py -k "long_press or short_tap or non_select_keys" -v --no-cov`
Expected: FAIL — `AttributeError: 'FocusGrid' object has no attribute 'long_press_activated'`.

- [ ] **Step 3: Implement**

In `src/sixpack/ui/widgets/focus_grid.py`, add the `QTimer` import and the new signal:

```python
from PyQt6.QtCore import QTimer, Qt, pyqtSignal
```

```python
    item_activated = pyqtSignal(int)
    long_press_activated = pyqtSignal(int)
    focus_changed = pyqtSignal(int)
```

In `__init__`, after `self._focused_index = 0`, add:

```python
        # Select-hold detection (see keyPressEvent/keyReleaseEvent below).
        # 500ms is the standard long-press threshold (matches Android's own
        # ViewConfiguration.getLongPressTimeout() default).
        self._select_hold_timer = QTimer(self)
        self._select_hold_timer.setSingleShot(True)
        self._select_hold_timer.setInterval(500)
        self._select_hold_timer.timeout.connect(self._on_select_hold_timeout)
        self._select_held = False
        self._select_resolved_as_hold = False
```

Change `keyPressEvent`'s `SELECT` branch from:

```python
        elif action == InputAction.SELECT:
            self.item_activated.emit(idx)
```

to:

```python
        elif action == InputAction.SELECT:
            if not event.isAutoRepeat() and not self._select_held:
                self._select_held = True
                self._select_resolved_as_hold = False
                self._select_hold_timer.start()
```

(`item_activated` no longer fires here at all -- it moves to the new `keyReleaseEvent` below.)

Add a new `keyReleaseEvent` and the timeout handler, right after `keyPressEvent`:

```python
    def keyReleaseEvent(self, event) -> None:
        from sixpack.input.actions import InputAction
        from sixpack.input.keyboard import key_to_action

        if event.isAutoRepeat():
            return
        action = key_to_action(event.key())
        if action != InputAction.SELECT or not self._select_held:
            super().keyReleaseEvent(event)
            return
        self._select_held = False
        self._select_hold_timer.stop()
        if not self._select_resolved_as_hold:
            self.item_activated.emit(self._focused_index)

    def _on_select_hold_timeout(self) -> None:
        self._select_resolved_as_hold = True
        self.long_press_activated.emit(self._focused_index)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_widgets.py -v --no-cov`
Expected: all tests in the file PASS, including every pre-existing `FocusGrid`/`MediaCard`/`PlayerScreen` test (confirms `item_activated` firing on release instead of press doesn't break any existing test that clicks/activates a grid item and checks the result afterward).

- [ ] **Step 5: Lint**

Run: `.venv/bin/ruff check src/sixpack/ui/widgets/focus_grid.py tests/test_ui/test_widgets.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/sixpack/ui/widgets/focus_grid.py tests/test_ui/test_widgets.py
git commit -m "Add hold-Select detection to FocusGrid (long_press_activated)"
```

---

## Task 3: `DetailGridScreen` — mark finished/unfinished on grid cards

**Files:**
- Modify: `src/sixpack/ui/screens/detail_grid.py`
- Modify: `src/sixpack/ui/screens/series_detail.py`
- Modify: `src/sixpack/ui/screens/playlist_detail.py`
- Modify: `src/sixpack/ui/screens/podcast_detail.py`
- Modify: `tests/test_ui/test_detail_grid.py`
- Modify: `tests/test_ui/test_screens.py`
- Modify: `tests/test_ui/test_playlist_screens.py`
- Modify: `tests/test_ui/test_podcast_detail.py`

**Interfaces:**
- Consumes: `ConfirmPopup` (Task 1), `FocusGrid.long_press_activated` (Task 2).
- Produces:
  - New abstract method `_item_progress_ids(item) -> tuple[str, str | None]` (item_id, episode_id) that `SeriesDetailScreen`/`PlaylistDetailScreen`/`PodcastDetailScreen` must implement.
  - New signal `finished_changed = pyqtSignal(str, float, float, bool, str)` — `(item_id, current_time, duration, is_finished, episode_id)`, same shape as `PlayerScreen.progress_update`.
  - New method `_toggle_finished(index: int) -> None`.

- [ ] **Step 1: Write the failing tests**

First, update the existing test fixtures in `tests/test_ui/test_detail_grid.py` to use real `MediaProgress` objects (matching what every real subclass actually stores in `self._progress`) instead of plain dicts — this file's `_TestScreen`/`_FakeItem` predate this feature and used a simplified fake shape that the new `_toggle_finished()` (which lives in the base class and must work identically for the fake and every real subclass) can't special-case around.

Replace the top of `tests/test_ui/test_detail_grid.py` (the `_FakeItem`/`_TestScreen` classes) with:

```python
"""Tests for the DetailGridScreen base (series/playlist item grid shell)."""
from __future__ import annotations

from sixpack.api.models import MediaProgress
from sixpack.ui.screens.detail_grid import DetailGridScreen


class _FakeItem:
    def __init__(self, key, title, subtitle="", cover_url=None, duration=100.0):
        self.key = key
        self.title_ = title
        self.subtitle_ = subtitle
        self.cover_url = cover_url
        self.duration = duration


class _TestScreen(DetailGridScreen):
    """Minimal concrete subclass for testing the base in isolation."""

    def _item_key(self, item):
        return item.key

    def _item_progress(self, item, progress):
        p: MediaProgress | None = progress.get(item.key)
        if p is None or not item.duration:
            return 0.0, False
        finished = bool(p.is_finished)
        fraction = 0.0 if finished else max(0.0, min(1.0, p.current_time / item.duration))
        return fraction, finished

    def _item_progress_ids(self, item):
        return item.key, None

    def _item_title(self, item):
        return item.title_

    def _item_subtitle(self, item):
        return item.subtitle_

    def _item_cover_url(self, item, server_url, token):
        return item.cover_url  # None unless a test opts in
```

Then update every existing test in the file that builds a progress dict with plain `{"fraction": ..., "finished": ...}` literals to use `MediaProgress` instead. There are five: `test_detail_grid_populate_focuses_resume_index`, `test_detail_grid_refresh_progress_updates_in_place_without_rebuild`, `test_detail_grid_refresh_progress_sets_finished_badge`, `test_detail_grid_refresh_progress_preserves_navigated_focus`, `test_detail_grid_refresh_progress_still_focuses_resume_if_untouched`. In each, replace e.g.:

```python
    progress = {"a": {"fraction": 1.0, "finished": True}}
```

with:

```python
    progress = {"a": MediaProgress(currentTime=100.0, duration=100.0, isFinished=True)}
```

(and the equivalent inline dict literals passed directly to `_refresh_progress({...})` in the other four tests — same substitution, `MediaProgress(currentTime=100.0, duration=100.0, isFinished=True)` in place of `{"fraction": 1.0, "finished": True}`). Leave every other line in those tests unchanged — this is purely a fixture-shape substitution, the assertions themselves don't change.

Now append new tests to the end of `tests/test_ui/test_detail_grid.py`:

```python
def test_item_progress_ids_default_from_test_screen(qtbot):
    screen = _TestScreen()
    qtbot.addWidget(screen)
    item_id, episode_id = screen._item_progress_ids(_FakeItem("a", "Item A"))
    assert item_id == "a"
    assert episode_id is None


def test_toggle_finished_on_unfinished_item_marks_finished_at_full_duration(qtbot):
    screen = _TestScreen()
    qtbot.addWidget(screen)
    screen._populate("My Series", _items(), {}, "http://s", "t")

    received = []
    screen.finished_changed.connect(lambda *args: received.append(args))
    screen._toggle_finished(0)

    assert received == [("a", 100.0, 100.0, True, "")]
    fraction, finished = screen._item_progress(_items()[0], screen._progress)
    assert finished is True
    assert screen._grid._items[0]._finished is True


def test_toggle_finished_on_finished_item_marks_unfinished_preserving_position(qtbot):
    screen = _TestScreen()
    qtbot.addWidget(screen)
    progress = {"a": MediaProgress(currentTime=42.0, duration=100.0, isFinished=True)}
    screen._populate("My Series", _items(), progress, "http://s", "t")

    received = []
    screen.finished_changed.connect(lambda *args: received.append(args))
    screen._toggle_finished(0)

    assert received == [("a", 42.0, 100.0, False, "")]
    assert screen._grid._items[0]._finished is False


def test_toggle_finished_reverting_with_no_recorded_position_uses_zero(qtbot):
    """Marking an item unfinished when its recorded position is already
    0.0 (e.g. it was finished without ever really being played) must not
    fabricate a nonzero position -- distinct from the "preserving position"
    test above, which covers a nonzero recorded position."""
    screen = _TestScreen()
    qtbot.addWidget(screen)
    progress = {"a": MediaProgress(currentTime=0.0, duration=100.0, isFinished=True)}
    screen._populate("My Series", _items(), progress, "http://s", "t")

    received = []
    screen.finished_changed.connect(lambda *args: received.append(args))
    screen._toggle_finished(0)

    assert received == [("a", 0.0, 100.0, False, "")]


def test_toggle_finished_out_of_range_index_is_noop(qtbot):
    screen = _TestScreen()
    qtbot.addWidget(screen)
    screen._populate("My Series", _items(), {}, "http://s", "t")
    received = []
    screen.finished_changed.connect(lambda *args: received.append(args))
    screen._toggle_finished(99)
    assert received == []


def test_grid_long_press_opens_popup_with_correct_message(qtbot):
    screen = _TestScreen()
    qtbot.addWidget(screen)
    screen._populate("My Series", _items(), {}, "http://s", "t")
    screen.show()

    screen._grid.long_press_activated.emit(0)

    assert screen._finish_popup.isVisible()
    assert "Item A" in screen._finish_popup._message_label.text()
    assert "finished" in screen._finish_popup._message_label.text().lower()


def test_grid_long_press_on_finished_item_offers_unfinish_wording(qtbot):
    screen = _TestScreen()
    qtbot.addWidget(screen)
    progress = {"a": MediaProgress(currentTime=100.0, duration=100.0, isFinished=True)}
    screen._populate("My Series", _items(), progress, "http://s", "t")
    screen.show()

    screen._grid.long_press_activated.emit(0)

    assert "unfinished" in screen._finish_popup._message_label.text().lower()


def test_confirming_popup_toggles_finished_state(qtbot):
    screen = _TestScreen()
    qtbot.addWidget(screen)
    screen._populate("My Series", _items(), {}, "http://s", "t")
    screen.show()

    received = []
    screen.finished_changed.connect(lambda *args: received.append(args))
    screen._grid.long_press_activated.emit(0)
    screen._finish_popup.confirmed.emit()

    assert received == [("a", 100.0, 100.0, True, "")]


def test_cancelling_popup_does_not_toggle(qtbot):
    screen = _TestScreen()
    qtbot.addWidget(screen)
    screen._populate("My Series", _items(), {}, "http://s", "t")
    screen.show()

    received = []
    screen.finished_changed.connect(lambda *args: received.append(args))
    screen._grid.long_press_activated.emit(0)
    screen._finish_popup.cancelled.emit()

    assert received == []


def test_keypress_while_popup_visible_does_not_fall_through_to_back(qtbot):
    from PyQt6.QtCore import Qt

    screen = _TestScreen()
    qtbot.addWidget(screen)
    screen._populate("My Series", _items(), {}, "http://s", "t")
    screen.show()
    screen._grid.long_press_activated.emit(0)

    back_received = []
    screen.back_requested.connect(lambda: back_received.append(True))
    qtbot.keyClick(screen, Qt.Key.Key_Backspace)  # BACK -- popup must consume it

    assert back_received == []
    assert not screen._finish_popup.isVisible()  # BACK cancelled the popup instead
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_detail_grid.py -v --no-cov`
Expected: FAIL — `AttributeError: '_TestScreen' object has no attribute '_item_progress_ids'` (or `finished_changed`), depending on which test collects first.

- [ ] **Step 3: Implement**

In `src/sixpack/ui/screens/detail_grid.py`, add imports:

```python
from sixpack.api.models import MediaProgress
from sixpack.ui.widgets.confirm_popup import ConfirmPopup
```

Add the new signal, alongside the existing ones:

```python
    item_activated = pyqtSignal(object)
    finished_changed = pyqtSignal(str, float, float, bool, str)
    back_requested = pyqtSignal()
```

Add the new abstract method, alongside the other subclass-contract methods:

```python
    def _item_progress_ids(self, item: Any) -> tuple[str, str | None]:
        """(item_id, episode_id) for the update_progress() API call --
        distinct from _item_key(), which is the progress-dict lookup key
        and (for podcast episodes specifically) holds a different value:
        _item_key returns the episode's own id, but update_progress needs
        the show's library-item id as item_id and the episode's id
        separately as episode_id."""
        raise NotImplementedError
```

In `_build_ui()`, after `self._grid.focus_changed.connect(self._on_grid_focus_changed)`, add:

```python
        self._grid.long_press_activated.connect(self._on_grid_long_press)

        self._finish_popup = ConfirmPopup(self)
        self._finish_popup.confirmed.connect(self._on_finish_confirmed)
        self._pending_finish_index: int | None = None
```

In `resizeEvent`, alongside the existing `self._hero_backdrop.setGeometry(self.rect())`, add:

```python
        w, h = int(self.width() * 0.5), 180
        self._finish_popup.setGeometry((self.width() - w) // 2, (self.height() - h) // 2, w, h)
```

Add the new handler methods, near `_find_resume_index`:

```python
    def _on_grid_long_press(self, index: int) -> None:
        if not (0 <= index < len(self._items)):
            return
        item = self._items[index]
        _fraction, finished = self._item_progress(item, self._progress)
        self._pending_finish_index = index
        if finished:
            self._finish_popup.show_confirm(
                f"Mark '{self._item_title(item)}' as unfinished?",
                confirm_label="Mark Unfinished",
            )
        else:
            self._finish_popup.show_confirm(
                f"Mark '{self._item_title(item)}' as finished?",
                confirm_label="Mark Finished",
            )

    def _on_finish_confirmed(self) -> None:
        if self._pending_finish_index is not None:
            self._toggle_finished(self._pending_finish_index)
        self._pending_finish_index = None

    def _toggle_finished(self, index: int) -> None:
        if not (0 <= index < len(self._items)):
            return
        item = self._items[index]
        key = self._item_key(item)
        prog: MediaProgress | None = self._progress.get(key)
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

Update `keyPressEvent` to check the popup first:

```python
    def keyPressEvent(self, event) -> None:
        from sixpack.input.actions import InputAction
        from sixpack.input.keyboard import key_to_action

        action = key_to_action(event.key())
        if self._finish_popup.isVisible():
            self._finish_popup.handle_key(action)
            return
        if action == InputAction.BACK:
            self.back_requested.emit()
        else:
            super().keyPressEvent(event)
```

Now implement `_item_progress_ids` in each real subclass.

In `src/sixpack/ui/screens/series_detail.py`, add alongside `_item_progress`:

```python
    def _item_progress_ids(self, item: SeriesBook) -> tuple[str, str | None]:
        return item.id, None
```

In `src/sixpack/ui/screens/playlist_detail.py`, add alongside `_item_progress`:

```python
    def _item_progress_ids(self, item: PlaylistItem) -> tuple[str, str | None]:
        return item.library_item_id, item.episode_id
```

In `src/sixpack/ui/screens/podcast_detail.py`, add alongside `_item_progress`:

```python
    def _item_progress_ids(self, item: PodcastEpisode) -> tuple[str, str | None]:
        return item.library_item_id, item.id
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_detail_grid.py -v --no-cov`
Expected: all tests PASS.

Then add one `_item_progress_ids` test per real subclass, in its own actual test file (playlist and podcast are NOT tested in `test_screens.py` — they have their own files).

In `tests/test_ui/test_screens.py`, using the existing `_make_series()` helper (defined just above `# ---- SeriesDetailScreen ----`, returns a `Series` with books `b1`/`b2`), add:

```python
def test_series_detail_item_progress_ids(qtbot):
    screen = SeriesDetailScreen()
    qtbot.addWidget(screen)
    book = _make_series().books[0]
    assert screen._item_progress_ids(book) == ("b1", None)
```

In `tests/test_ui/test_playlist_screens.py`, using the existing `_make_playlist()` helper (defined just above `# ---- PlaylistDetailScreen ----`, returns a `Playlist` with items built via `_make_item("li1", ...)`/`_make_item("li2", ...)`), add:

```python
def test_playlist_detail_item_progress_ids(qtbot):
    screen = PlaylistDetailScreen()
    qtbot.addWidget(screen)
    item = _make_playlist().items[0]
    assert screen._item_progress_ids(item) == ("li1", None)
```

In `tests/test_ui/test_podcast_detail.py`, using the existing `_episode(episode_id, title, duration)` helper (hardcodes `libraryItemId="show1"`), add:

```python
def test_podcast_detail_item_progress_ids(qtbot):
    screen = PodcastDetailScreen()
    qtbot.addWidget(screen)
    episode = _episode("ep1", "Episode One")
    assert screen._item_progress_ids(episode) == ("show1", "ep1")
```

Then run all three:

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_screens.py tests/test_ui/test_playlist_screens.py tests/test_ui/test_podcast_detail.py -v --no-cov 2>&1 | tail -40`
Expected: PASS, including every pre-existing test in all three files (confirms adding the one new abstract method to `DetailGridScreen` and implementing it in each subclass didn't break any existing construction/behavior).

- [ ] **Step 5: Lint**

Run: `.venv/bin/ruff check src/sixpack/ui/screens/detail_grid.py src/sixpack/ui/screens/series_detail.py src/sixpack/ui/screens/playlist_detail.py src/sixpack/ui/screens/podcast_detail.py tests/test_ui/test_detail_grid.py tests/test_ui/test_screens.py tests/test_ui/test_playlist_screens.py tests/test_ui/test_podcast_detail.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/sixpack/ui/screens/detail_grid.py src/sixpack/ui/screens/series_detail.py src/sixpack/ui/screens/playlist_detail.py src/sixpack/ui/screens/podcast_detail.py tests/test_ui/test_detail_grid.py tests/test_ui/test_screens.py tests/test_ui/test_playlist_screens.py tests/test_ui/test_podcast_detail.py
git commit -m "Add mark finished/unfinished via hold-Select on detail-grid cards"
```

---

## Task 4: `PlayerScreen` — mark finished control-row button

**Files:**
- Modify: `src/sixpack/ui/theme.py`
- Modify: `src/sixpack/ui/screens/player.py`
- Modify: `tests/test_ui/test_widgets.py`

**Interfaces:**
- Consumes: `ConfirmPopup` (Task 1). `theme.ICON_CHECK_CIRCLE` (new, this task).
- Produces: `PlayerScreen._finish_btn: QPushButton` (appended to `self._control_buttons`), `PlayerScreen._finish_popup: ConfirmPopup`.

- [ ] **Step 1: Add the icon constant**

`Edit`'s exact-string-match against an *existing* invisible PUA glyph character can silently fail (the visible text looks like empty quotes but isn't byte-identical to what gets typed) -- per this project's established, reliable technique, insert the new constant via a small inline Python script instead of a direct `Edit` call:

```bash
.venv/bin/python3 << 'PYEOF'
import re

path = "src/sixpack/ui/theme.py"
with open(path) as f:
    content = f.read()

marker = "ICON_LOGOUT = " + chr(0xE9BA) + "\n"
assert marker in content, "ICON_LOGOUT line not found or already changed -- check theme.py by hand"

new_line = "ICON_CHECK_CIRCLE = " + chr(0xE86C) + "\n"
content = content.replace(marker, marker + new_line)

with open(path, "w") as f:
    f.write(content)
PYEOF
```

Verify it landed correctly:

```bash
.venv/bin/python3 -c "
from sixpack.ui import theme
import sys
sys.path.insert(0, 'src')
"
.venv/bin/python3 -c "
import sys
sys.path.insert(0, 'src')
from sixpack.ui import theme
assert ord(theme.ICON_CHECK_CIRCLE) == 0xE86C
print('OK:', hex(ord(theme.ICON_CHECK_CIRCLE)))
"
```

Expected: prints `OK: 0xe86c`.

- [ ] **Step 2: Write the failing tests**

Read `tests/test_ui/test_widgets.py`'s existing `PlayerScreen` control-row tests first (search for `_control_buttons` in that file) for this project's construction convention (`PlayerScreen(mock_player)` with a `MockAudioPlayer`, `qtbot.addWidget`, driving via real `qtbot.keyClick`).

Add to `tests/test_ui/test_widgets.py`, in the `PlayerScreen` section:

```python
def test_finish_button_is_last_control_button(qtbot):
    from sixpack.ui.screens.player import PlayerScreen
    mock_player = MockAudioPlayer()
    screen = PlayerScreen(mock_player)
    qtbot.addWidget(screen)
    assert screen._control_buttons[-1] is screen._finish_btn


def test_finish_button_reachable_via_left_right_select(qtbot):
    from PyQt6.QtCore import Qt
    from sixpack.ui.screens.player import PlayerScreen
    mock_player = MockAudioPlayer()
    screen = PlayerScreen(mock_player)
    qtbot.addWidget(screen)
    screen.show()
    screen.setFocus()

    for _ in range(len(screen._control_buttons) - 1):
        qtbot.keyClick(screen, Qt.Key.Key_Right)

    assert screen._control_focus_idx == screen._control_buttons.index(screen._finish_btn)
    qtbot.keyClick(screen, Qt.Key.Key_Return)

    assert screen._finish_popup.isVisible()


def test_finish_button_click_opens_popup_with_title(qtbot):
    from sixpack.ui.screens.player import PlayerScreen
    mock_player = MockAudioPlayer()
    screen = PlayerScreen(mock_player)
    qtbot.addWidget(screen)
    screen._title_label.setText("My Book")

    screen._finish_btn.click()

    assert screen._finish_popup.isVisible()
    assert "My Book" in screen._finish_popup._message_label.text()


def test_confirming_finish_emits_progress_update_with_real_position(qtbot):
    from sixpack.ui.screens.player import PlayerScreen
    mock_player = MockAudioPlayer()
    screen = PlayerScreen(mock_player)
    qtbot.addWidget(screen)
    screen._item_id = "item1"
    screen._episode_id = "ep1"
    screen._position = 123.0
    screen._duration = 999.0

    received = []
    screen.progress_update.connect(lambda *args: received.append(args))
    screen._finish_btn.click()
    screen._finish_popup.confirmed.emit()

    assert received == [("item1", 123.0, 999.0, True, "ep1")]


def test_confirming_finish_stops_player_and_emits_track_ended(qtbot):
    from sixpack.ui.screens.player import PlayerScreen
    mock_player = MockAudioPlayer()
    screen = PlayerScreen(mock_player)
    qtbot.addWidget(screen)

    ended = []
    screen.track_ended.connect(lambda: ended.append(True))
    screen._finish_btn.click()
    screen._finish_popup.confirmed.emit()

    assert mock_player.stop_called is True
    assert ended == [True]


def test_cancelling_finish_popup_does_not_stop_or_emit(qtbot):
    from sixpack.ui.screens.player import PlayerScreen
    mock_player = MockAudioPlayer()
    screen = PlayerScreen(mock_player)
    qtbot.addWidget(screen)

    ended = []
    screen.track_ended.connect(lambda: ended.append(True))
    screen._finish_btn.click()
    screen._finish_popup.cancelled.emit()

    assert mock_player.stop_called is False
    assert ended == []


def test_keypress_while_finish_popup_visible_does_not_fall_through(qtbot):
    from PyQt6.QtCore import Qt
    from sixpack.ui.screens.player import PlayerScreen
    mock_player = MockAudioPlayer()
    screen = PlayerScreen(mock_player)
    qtbot.addWidget(screen)
    screen.show()
    screen.setFocus()
    screen._finish_btn.click()

    back_received = []
    screen.back_requested.connect(lambda: back_received.append(True))
    qtbot.keyClick(screen, Qt.Key.Key_Backspace)

    assert back_received == []
    assert not screen._finish_popup.isVisible()
```

Check `MockAudioPlayer` (this file's existing player test double, used by the rest of the `PlayerScreen` test section) for a `stop()` method — if it doesn't already track calls, add a `self.stop_called = False` in its `__init__` and set it `True` inside its `stop()` method, matching however it already tracks other calls (e.g. `toggle_pause_called` or similar, if present — follow that exact existing pattern).

- [ ] **Step 3: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_widgets.py -k finish -v --no-cov`
Expected: FAIL — `AttributeError: 'PlayerScreen' object has no attribute '_finish_btn'`.

- [ ] **Step 4: Implement**

In `src/sixpack/ui/screens/player.py`, add the import:

```python
from sixpack.ui.widgets.confirm_popup import ConfirmPopup
```

After the existing `self._speed_btn = QPushButton(theme.ICON_SPEED)` / `self._speed_btn.clicked.connect(self._cycle_speed)` block, add:

```python
        self._finish_btn = QPushButton(theme.ICON_CHECK_CIRCLE)
        self._finish_btn.setFixedSize(44, 44)
        self._finish_btn.clicked.connect(self._on_finish_clicked)
```

Change the `self._control_buttons` list to include it at the end:

```python
        self._control_buttons: list[QPushButton] = [
            self._chapters_btn, self._prev_btn, self._rew_btn, self._play_btn,
            self._fwd_btn, self._next_btn, self._speed_btn, self._finish_btn,
        ]
```

In `_reflect_control_focus`, add `self._finish_btn` to the tertiary-styling group (same de-emphasized style as chapters/speed):

```python
            elif btn in (self._chapters_btn, self._speed_btn, self._finish_btn):
```

After the existing `self._chapter_overlay = QListWidget(self)` ... `self._chapter_overlay.hide()` block, add:

```python
        self._finish_popup = ConfirmPopup(self)
        self._finish_popup.confirmed.connect(self._on_finish_confirmed)
```

In `resizeEvent`, alongside the existing chapter-overlay geometry line, add:

```python
        fw, fh = int(self.width() * 0.5), 180
        self._finish_popup.setGeometry((self.width() - fw) // 2, (self.height() - fh) // 2, fw, fh)
```

Add the new handler methods near `_toggle_chapter_overlay`:

```python
    def _on_finish_clicked(self) -> None:
        title = self._title_label.text()
        self._finish_popup.show_confirm(
            f"Mark '{title}' as finished?", confirm_label="Mark Finished"
        )

    def _on_finish_confirmed(self) -> None:
        self.progress_update.emit(
            self._item_id, self._position, self._duration, True, self._episode_id
        )
        self._player.stop()
        self.track_ended.emit()
```

Update `keyPressEvent` to check the new popup first (before the existing chapter-overlay check):

```python
    def keyPressEvent(self, event: QKeyEvent) -> None:
        from sixpack.input.actions import InputAction
        from sixpack.input.keyboard import key_to_action

        action = key_to_action(event.key(), player_mode=True)

        if self._finish_popup.isVisible():
            self._finish_popup.handle_key(action)
            return

        if self._chapter_overlay.isVisible():
```

(everything from `if self._chapter_overlay.isVisible():` onward is unchanged — just now reached only when the finish popup isn't up.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_widgets.py -v --no-cov`
Expected: all tests in the file PASS, including every pre-existing `PlayerScreen` test (confirms the new button in `_control_buttons` doesn't shift any index-based assertion elsewhere — search the file for any test asserting a literal numeric `_control_focus_idx` value tied to "last button" or "speed is last"; update any such assertion to reference `screen._control_buttons.index(screen._speed_btn)` or similar instead of a hardcoded index, since speed is no longer last).

- [ ] **Step 6: Lint**

Run: `.venv/bin/ruff check src/sixpack/ui/theme.py src/sixpack/ui/screens/player.py tests/test_ui/test_widgets.py`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/sixpack/ui/theme.py src/sixpack/ui/screens/player.py tests/test_ui/test_widgets.py
git commit -m "Add mark-finished control-row button to PlayerScreen"
```

---

## Task 5: Wire grid `finished_changed` signals into `app.py`

**Files:**
- Modify: `src/sixpack/ui/app.py`
- Modify: `tests/test_ui/test_app.py`

**Interfaces:**
- Consumes: `DetailGridScreen.finished_changed` (Task 3, inherited by all three detail screens).
- Produces: nothing new — this task only adds signal connections. No new methods.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_ui/test_app.py`:

```python
def test_series_detail_finished_changed_wired_to_progress_update(window, monkeypatch):
    calls = []
    monkeypatch.setattr(window, "_on_progress_update", lambda *a: calls.append(a))
    window._detail_screen.finished_changed.emit("item1", 100.0, 100.0, True, "")
    assert calls == [("item1", 100.0, 100.0, True, "")]


def test_playlist_detail_finished_changed_wired_to_progress_update(window, monkeypatch):
    calls = []
    monkeypatch.setattr(window, "_on_progress_update", lambda *a: calls.append(a))
    window._playlist_detail_screen.finished_changed.emit("item1", 100.0, 100.0, True, "")
    assert calls == [("item1", 100.0, 100.0, True, "")]


def test_podcast_detail_finished_changed_wired_to_progress_update(window, monkeypatch):
    calls = []
    monkeypatch.setattr(window, "_on_progress_update", lambda *a: calls.append(a))
    window._podcast_detail_screen.finished_changed.emit("item1", 100.0, 100.0, True, "ep1")
    assert calls == [("item1", 100.0, 100.0, True, "ep1")]
```

(Mirrors this file's existing `test_on_progress_update_via_real_signal_forwards_episode_id` pattern of monkeypatching the handler and emitting the real signal, rather than calling the handler directly — confirms the actual wiring exists, not just that the handler works in isolation.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_app.py -k finished_changed -v --no-cov`
Expected: FAIL — `calls == []` (nothing connected yet), not an error; the signal exists (Task 3) but nothing listens to it yet.

- [ ] **Step 3: Implement**

In `src/sixpack/ui/app.py`'s `_build_ui()`, alongside the existing lines:

```python
        self._detail_screen.episode_activated.connect(self._on_episode_activated)
        self._detail_screen.back_requested.connect(self._show_browse)
```

add:

```python
        self._detail_screen.finished_changed.connect(self._on_progress_update)
```

alongside:

```python
        self._playlist_detail_screen.item_activated.connect(self._on_playlist_item_activated)
        self._playlist_detail_screen.back_requested.connect(self._show_browse)
```

add:

```python
        self._playlist_detail_screen.finished_changed.connect(self._on_progress_update)
```

alongside:

```python
        self._podcast_detail_screen.item_activated.connect(self._on_podcast_episode_activated)
        self._podcast_detail_screen.back_requested.connect(self._show_browse)
```

add:

```python
        self._podcast_detail_screen.finished_changed.connect(self._on_progress_update)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_app.py -v --no-cov`
Expected: all tests in the file PASS.

Then run the full suite twice (this project's established habit before any commit touching shared wiring):

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --no-cov`
Expected: PASS, twice in a row.

Then with coverage:

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest`
Expected: PASS, `--cov-fail-under=85` satisfied.

- [ ] **Step 5: Lint**

Run: `.venv/bin/ruff check src/sixpack/ui/app.py tests/test_ui/test_app.py --diff`
Confirm any reported issues are pre-existing (unrelated import-ordering etc., already present before this task) rather than on lines this task touched — this file has known pre-existing violations; never conflate them with new ones.

- [ ] **Step 6: Commit**

```bash
git add src/sixpack/ui/app.py tests/test_ui/test_app.py
git commit -m "Wire detail-grid finished_changed signals into existing progress-update path"
```

---

## Task 6: Gamepad press/release support (cross-input parity for the hold gesture)

**Files:**
- Modify: `src/sixpack/input/gamepad.py`
- Modify: `src/sixpack/ui/app.py`
- Modify: `tests/test_input/test_gamepad.py`
- Modify: `tests/test_ui/test_app.py`

**Interfaces:**
- Consumes: nothing from prior tasks (independent input-layer plumbing).
- Produces: `GamepadListener.__init__`'s callback contract changes from `Callable[[InputAction], None]` to `Callable[[InputAction, bool], None]` (action, is_press). `MainWindow._on_gamepad_action`'s signature changes to `(self, action: InputAction, is_press: bool)`.

- [ ] **Step 1: Write the failing tests**

Read `tests/test_input/test_gamepad.py` in full first — every existing test does `action = gl._map_event(event); assert action == InputAction.X`, which needs updating to the new tuple return.

Replace every existing assertion of the shape `assert action == InputAction.X` in that file with `assert action == (InputAction.X, True)` (all existing tests construct press events, `value=1`, so they're all "is_press=True" cases). Do this for: `test_button_south_maps_to_select`, `test_button_east_maps_to_back`, `test_dpad_left`, `test_dpad_right`, `test_dpad_up`, `test_dpad_down`, `test_lb_maps_to_prev_chapter`, `test_rb_maps_to_next_chapter`.

`test_button_release_ignored` currently asserts `action is None` for a `value=0` (release) `BTN_SOUTH` event — this is the ONE existing test whose expected behavior actually changes (releases are no longer ignored for buttons). Replace it with:

```python
def test_button_release_reports_press_false(listener):
    gl, actions = listener
    ec = _make_ecodes()
    event = _make_event(ec.EV_KEY, ec.BTN_SOUTH, 0)  # release
    result = gl._map_event(event)
    from sixpack.input.actions import InputAction
    assert result == (InputAction.SELECT, False)
```

`test_dpad_center_ignored` and `test_unmapped_button_returns_none` and `test_start_is_unmapped` keep asserting `is None` (unaffected — center/unmapped stay `None` in both directions).

Add new tests for the repeat-event and unmapped-button-release cases:

```python
def test_key_repeat_event_ignored(listener):
    """value == 2 (autorepeat) must be ignored for both press and release
    detection, matching keyboard.py's isAutoRepeat() handling."""
    gl, actions = listener
    ec = _make_ecodes()
    event = _make_event(ec.EV_KEY, ec.BTN_SOUTH, 2)
    result = gl._map_event(event)
    assert result is None


def test_unmapped_button_release_returns_none(listener):
    gl, actions = listener
    ec = _make_ecodes()
    event = _make_event(ec.EV_KEY, 999, 0)
    result = gl._map_event(event)
    assert result is None
```

Add a test confirming `_listen`'s loop passes both values through to the callback:

```python
def test_listen_callback_receives_action_and_is_press(patch_evdev):
    from sixpack.input.gamepad import GamepadListener
    ec = _make_ecodes()

    class _FakeDevice:
        name = "fake"
        def read_loop(self):
            yield _make_event(ec.EV_KEY, ec.BTN_SOUTH, 1)
            yield _make_event(ec.EV_KEY, ec.BTN_SOUTH, 0)

    received = []
    gl = GamepadListener(callback=lambda action, is_press: received.append((action, is_press)))
    gl._listen(_FakeDevice())

    from sixpack.input.actions import InputAction
    assert received == [(InputAction.SELECT, True), (InputAction.SELECT, False)]
```

Now, in `tests/test_ui/test_app.py`, find the existing gamepad dispatch tests (search for `_on_gamepad_action`/`_dispatch_gamepad_key`) and update them for the new two-argument callback. Add:

```python
def test_gamepad_action_release_dispatches_key_release(window, qtbot):
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QLineEdit

    from sixpack.input.actions import InputAction

    target = QLineEdit()
    qtbot.addWidget(target)
    target.show()
    target.setFocus()
    qtbot.waitUntil(lambda: target.hasFocus(), timeout=2000)

    received = []
    target.keyReleaseEvent = lambda event: received.append(event.key())

    window._on_gamepad_action(InputAction.SELECT, False)

    qtbot.waitUntil(lambda: len(received) == 1, timeout=2000)
    assert received[0] == Qt.Key.Key_Return
```

(This mirrors the file's existing `test_gamepad_action_dispatches_synthetic_key_to_focused_widget` test for the press case — that test itself needs no change, since `window._on_gamepad_action(InputAction.SELECT)` becomes `window._on_gamepad_action(InputAction.SELECT, True)`; update that one call site's arguments.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_input/test_gamepad.py tests/test_ui/test_app.py -k "gamepad or dpad or button or listen_callback" -v --no-cov`
Expected: FAIL — tuple-vs-enum comparison failures in `test_gamepad.py`; `TypeError: _on_gamepad_action() missing 1 required positional argument` in `test_app.py`.

- [ ] **Step 3: Implement**

In `src/sixpack/input/gamepad.py`, change `_map_event`'s return type and logic:

```python
    def _map_event(self, event: evdev.InputEvent) -> tuple[InputAction, bool] | None:
        if not _EVDEV_AVAILABLE:
            return None
        if event.type == ecodes.EV_KEY:
            if event.value == 1:
                action = self._button_map.get(event.code)
                return (action, True) if action is not None else None
            if event.value == 0:
                action = self._button_map.get(event.code)
                return (action, False) if action is not None else None
            return None  # value == 2 (autorepeat) -- ignored, matches keyboard.py
        if event.type == ecodes.EV_ABS and event.value != 0:
            action = self._hat_map.get((event.code, event.value))
            return (action, True) if action is not None else None
        return None
```

Change `GamepadListener.__init__`'s type hint and `_listen`'s loop:

```python
    def __init__(self, callback: Callable[[InputAction, bool], None]) -> None:
```

```python
    def _listen(self, device: evdev.InputDevice) -> None:
        try:
            for event in device.read_loop():
                if self._stop_event.is_set():
                    break
                result = self._map_event(event)
                if result is not None:
                    action, is_press = result
                    self._callback(action, is_press)
        except OSError as exc:
            logger.warning("Gamepad %s disconnected: %s", device.name, exc)
```

In `src/sixpack/ui/app.py`, find `_on_gamepad_action` and `_dispatch_gamepad_key` (search for those exact names). Change:

```python
    def _on_gamepad_action(self, action: InputAction) -> None:
```

to:

```python
    def _on_gamepad_action(self, action: InputAction, is_press: bool) -> None:
```

and its body's `QMetaObject.invokeMethod` call to pass the extra argument through:

```python
        key = _GAMEPAD_ACTION_TO_KEY.get(action)
        if key is None:
            return
        QMetaObject.invokeMethod(
            self, "_dispatch_gamepad_key",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(int, key.value),
            Q_ARG(bool, is_press),
        )
```

Change `_dispatch_gamepad_key`'s signature and body:

```python
    @pyqtSlot(int, bool)
    def _dispatch_gamepad_key(self, key_value: int, is_press: bool) -> None:
        target = QApplication.focusWidget()
        if target is None:
            return
        event_type = QEvent.Type.KeyPress if is_press else QEvent.Type.KeyRelease
        event = QKeyEvent(event_type, Qt.Key(key_value), Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(target, event)
```

Find the existing `test_gamepad_action_dispatches_synthetic_key_to_focused_widget` test in `tests/test_ui/test_app.py` and update its single call site from `window._on_gamepad_action(InputAction.SELECT)` to `window._on_gamepad_action(InputAction.SELECT, True)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_input/test_gamepad.py tests/test_ui/test_app.py -v --no-cov`
Expected: all tests PASS.

Then the full suite twice, then with coverage:

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --no-cov` (twice)
Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest`
Expected: PASS both times, coverage gate satisfied.

- [ ] **Step 5: Lint**

Run: `.venv/bin/ruff check src/sixpack/input/gamepad.py src/sixpack/ui/app.py tests/test_input/test_gamepad.py tests/test_ui/test_app.py --diff`
Confirm any reported issues on `app.py`/its test are pre-existing (unrelated), not on lines this task touched. `gamepad.py`/its test should be fully clean.

- [ ] **Step 6: Commit**

```bash
git add src/sixpack/input/gamepad.py src/sixpack/ui/app.py tests/test_input/test_gamepad.py tests/test_ui/test_app.py
git commit -m "Extend gamepad input with press/release for the hold-Select gesture"
```

---

## Final checks (after all 6 tasks)

- [ ] Full suite, twice: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --no-cov`
- [ ] Full suite with coverage: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest` — `--cov-fail-under=85` satisfied
- [ ] Whole-tree lint: `.venv/bin/ruff check src/ tests/` — clean (the whole tree was clean before this branch started; it must stay that way)
- [ ] Manually verify on a live run (per this project's established habit): relaunch the app, open a series/playlist/podcast detail grid, hold Select on a focused card, confirm the popup appears and toggling works both directions; open the player screen, navigate to the new finish button, confirm it opens the popup and confirming stops playback and advances to "up next".
