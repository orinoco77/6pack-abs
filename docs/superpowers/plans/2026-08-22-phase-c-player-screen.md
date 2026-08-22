# Phase C — Player Screen Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the Now Playing (`PlayerScreen`) screen in line with the rest of the app's cinematic visual language, remove the current silent auto-advance-to-next-book/item behavior in favor of an "up next" indicator followed by a return to the grid/list, and add three new player features: playback speed control, an in-player chapter-jump overlay, and the up-next transition itself.

**Architecture:** `PlayerScreen` gains a `Backdrop` behind its content (reused as-is), restyled transport/progress elements, a small "up next" transitional label, and a chapter-jump overlay built from the same row widgets `chapter_select.py` already defines (`ChapterItem`, `_chapter_status`, `_chapter_fraction` — imported and reused directly, not recopied). `AudioPlayer` gains two new methods (`set_speed`, `seek_to_chapter`). Two currently-mapped-but-unhandled `InputAction`s (`UP`, `MENU`) become the speed-cycle and chapter-overlay triggers in player mode — no new `InputAction` enum members or keyboard/gamepad mapping changes are needed, so gamepad support is inherited automatically per the spec's Non-Goals. The end-of-book behavior change gets its own **new** signal (`PlayerScreen.track_ended`) distinct from the existing `next_item`/`prev_item` signals, which keep their current immediate-auto-play meaning for the *manual* skip-forward/back remote buttons — only the *automatic* end-of-track path changes.

**Tech Stack:** Python 3.12, PyQt6, python-mpv, pytest + pytest-qt (headless via `QT_QPA_PLATFORM=offscreen`).

**Spec:** `docs/superpowers/specs/2026-08-21-app-wide-cinematic-redesign-design.md` (Phase C section, plus the "End-of-book behavior change" paragraph filed under the spec's Phase B section — confirmed via `git grep`/manual check that this specific piece was never implemented in Phase A or B's actual delivered task lists, so it belongs here)

## Global Constraints

- Python ≥ 3.10 (dev/target 3.12). Line length 100 (ruff, `select = ["E","F","I","UP"]`).
- Coverage gate: `--cov-fail-under=80`.
- All Qt tests run under `QT_QPA_PLATFORM=offscreen`.
- No `QGraphicsEffect` subclass anywhere, ever — see `docs/qt-graphics-effect-crash.md`. All visual effects are paint-level (`QPainter`), following the established `_Scrim`/`_Glow`/`_FinishedBadge`/`_ProgressStrip`/`_FinishedCheck` pattern.
- Every scroll/container widget between a `Backdrop` and the screen surface needs explicit `background: transparent` styling (both its own stylesheet and, for `QAbstractScrollArea`-derived widgets, `.viewport().setStyleSheet(...)` too).
- No new `InputAction` enum members, no `keyboard.py`/`gamepad.py` changes — this phase reuses `InputAction.UP` and `InputAction.MENU`, both already mapped in `_PLAYER_MAP` (keyboard) and `gamepad.py`, but currently unhandled in `PlayerScreen.keyPressEvent`.
- `PlayerScreen.next_item`/`prev_item` signals and their existing wiring (manual `InputAction.NEXT_ITEM`/`PREV_ITEM` keypresses and the `_next_btn`/`_prev_btn` mouse buttons) must keep their current immediate-auto-play behavior unchanged — this phase only changes the *automatic* end-of-track path, via a new, separate signal.
- `PlayerScreen`'s public method signatures already called by `app.py` (`play_book`, `play_library_item`, `play_playlist_item`, `set_audio_tracks`) must not change.
- Commit after each task. Branch: `feature/app-wide-cinematic-redesign`.

---

## File Structure

| File | Change |
|------|--------|
| `src/sixpack/player/player.py` (edit) | Add `set_speed(float)`, `seek_to_chapter(index: int)` |
| `src/sixpack/ui/screens/player.py` (edit) | Visual redesign (Backdrop, cover size, progress bar, transport styling); new `track_ended` signal + up-next display; speed-cycle + chapter-overlay key handling |
| `src/sixpack/ui/screens/chapter_select.py` (edit) | Export `ChapterItem`, `_chapter_status`, `_chapter_fraction` for reuse (already module-level, just need to confirm nothing about them is player-screen-hostile) |
| `src/sixpack/ui/app.py` (edit) | New `_on_track_ended` handler replacing the auto-play path for automatic end-of-track; `_on_next_item`/`_on_prev_item` (manual skip) untouched |
| `tests/test_player/test_player.py` (edit) | Tests for `set_speed`, `seek_to_chapter` |
| `tests/test_ui/test_player_screen.py` (new) | Tests for the new visual elements, up-next display, speed-cycle key handling, chapter overlay |
| `tests/test_ui/test_app.py` (edit) | Test for `_on_track_ended`'s navigation behavior (series/playlist next-item pre-focus, standalone → Browse) |

---

## Task 1: `AudioPlayer.set_speed` and `seek_to_chapter`

**Files:**
- Modify: `src/sixpack/player/player.py`
- Test: `tests/test_player/test_player.py`

**Interfaces:**
- Produces: `AudioPlayer.set_speed(speed: float) -> None` — sets `self._mpv.speed = speed`. `AudioPlayer.seek_to_chapter(index: int) -> None` — sets `self._mpv.chapter = index` if `0 <= index < self.chapter_count`, else no-op (mirrors `next_chapter`/`prev_chapter`'s existing bounds-checking style).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_player/test_player.py`, near the existing Chapters section:

```python
def test_set_speed(player):
    player.set_speed(1.5)
    assert _mock_mpv_instance.speed == 1.5


def test_seek_to_chapter_in_range(player):
    _mock_mpv_instance.chapter_list = [{"title": "Ch1"}, {"title": "Ch2"}, {"title": "Ch3"}]
    player.seek_to_chapter(2)
    assert _mock_mpv_instance.chapter == 2


def test_seek_to_chapter_out_of_range_is_noop(player):
    _mock_mpv_instance.chapter_list = [{"title": "Ch1"}, {"title": "Ch2"}]
    _mock_mpv_instance.chapter = 0
    player.seek_to_chapter(5)
    assert _mock_mpv_instance.chapter == 0


def test_seek_to_chapter_negative_is_noop(player):
    _mock_mpv_instance.chapter_list = [{"title": "Ch1"}]
    _mock_mpv_instance.chapter = 0
    player.seek_to_chapter(-1)
    assert _mock_mpv_instance.chapter == 0
```

`MockMPV.__init__` (top of the file) needs a `self.speed = 1.0` default added alongside its existing `self.pause`/`self.time_pos`/etc. attributes — plain attribute access is enough, `MockMPV` doesn't need a `speed` property, it already accepts arbitrary attribute assignment.

- [ ] **Step 2: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_player/test_player.py -v -k "speed or seek_to_chapter"`
Expected: FAIL — `AttributeError: 'AudioPlayer' object has no attribute 'set_speed'` (and `seek_to_chapter`).

- [ ] **Step 3: Implement**

In `src/sixpack/player/player.py`, add near `seek_forward`/`seek_back` (after the seeking section, before the "Chapter navigation" section):

```python
    def set_speed(self, speed: float) -> None:
        self._mpv.speed = speed
```

In the "Chapter navigation" section, after `prev_chapter`:

```python
    def seek_to_chapter(self, index: int) -> None:
        if 0 <= index < self.chapter_count:
            self._mpv.chapter = index
```

- [ ] **Step 4: Add `self.speed = 1.0` to `MockMPV.__init__`**

In `tests/test_player/test_player.py`'s `MockMPV.__init__`, add `self.speed = 1.0` alongside the other default attributes.

- [ ] **Step 5: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_player/test_player.py -v -k "speed or seek_to_chapter"`
Expected: PASS.

- [ ] **Step 6: Run the full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` (3 times)
Expected: all passing, coverage ≥80%.

- [ ] **Step 7: Commit**

```bash
git add src/sixpack/player/player.py tests/test_player/test_player.py
git commit -m "Add AudioPlayer.set_speed and seek_to_chapter"
```

---

## Task 2: `PlayerScreen` up-next display + `track_ended` signal

**Files:**
- Modify: `src/sixpack/ui/screens/player.py`
- Test: `tests/test_ui/test_player_screen.py` (new)

**Interfaces:**
- Consumes: nothing new from Task 1 (this task doesn't touch speed/chapters).
- Produces: new signal `track_ended = pyqtSignal()` (no payload — `app.py`, in Task 3, computes "what's next" itself since it already owns `_current_series`/`_current_playlist` state; `PlayerScreen` doesn't need to duplicate that lookup). New methods `show_up_next(message: str) -> None` and `hide_up_next() -> None` — pure display, no internal timer (the delay is owned by `app.py` in Task 3, keeping all timing/navigation logic in one place). `_handle_end_of_track` changes from `self.next_item.emit()` to `self.track_ended.emit()` — **`next_item`/`prev_item` signals themselves, and every other connection to them, are untouched.**

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ui/test_player_screen.py`:

```python
"""Tests for PlayerScreen's up-next display and track_ended signal."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import Qt

from sixpack.player.player import AudioPlayer
from sixpack.ui.screens.player import PlayerScreen


class _FakePlayer:
    """Stands in for AudioPlayer — PlayerScreen only needs on_*/toggle_pause/
    seek_*/stop/set_speed/seek_to_chapter/chapter_count/current_chapter on it,
    matching AudioPlayer's real interface without constructing real mpv."""

    def __init__(self):
        self.speed_calls = []
        self.seek_to_chapter_calls = []
        self.chapter_count = 0
        self.current_chapter = 0

    def on_position_changed(self, cb): pass
    def on_state_changed(self, cb): pass
    def on_end_of_track(self, cb): pass
    def on_duration_changed(self, cb): pass
    def toggle_pause(self): pass
    def stop(self): pass
    def seek_forward(self): pass
    def seek_back(self): pass
    def seek_forward_long(self): pass
    def seek_back_long(self): pass
    def next_chapter(self): pass
    def prev_chapter(self): pass
    def set_speed(self, speed): self.speed_calls.append(speed)
    def seek_to_chapter(self, index): self.seek_to_chapter_calls.append(index)


@pytest.fixture
def screen(qtbot):
    s = PlayerScreen(player=_FakePlayer())
    qtbot.addWidget(s)
    return s


def test_show_up_next_sets_visible_text(screen):
    screen.show_up_next("Up next: Episode 2")
    assert screen._up_next_label.isVisible()
    assert screen._up_next_label.text() == "Up next: Episode 2"


def test_hide_up_next_clears_visibility(screen):
    screen.show_up_next("Up next: Episode 2")
    screen.hide_up_next()
    assert not screen._up_next_label.isVisible()


def test_up_next_label_hidden_initially(screen):
    assert not screen._up_next_label.isVisible()


def test_track_ended_emitted_not_next_item(qtbot, screen):
    """Regression: the automatic end-of-track path must use the new
    track_ended signal, NOT the existing next_item signal — next_item is
    reserved for the manual skip-forward remote button/key, which must keep
    auto-playing immediately (see this plan's Global Constraints)."""
    next_item_calls = []
    track_ended_calls = []
    screen.next_item.connect(lambda: next_item_calls.append(True))
    screen.track_ended.connect(lambda: track_ended_calls.append(True))

    screen._handle_end_of_track()

    assert track_ended_calls == [True]
    assert next_item_calls == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_player_screen.py -v`
Expected: FAIL — `AttributeError` on `_up_next_label`/`show_up_next`/`track_ended` (whichever the test reaches first).

- [ ] **Step 3: Implement**

In `src/sixpack/ui/screens/player.py`:

Add the new signal alongside the existing ones:

```python
    back_requested = pyqtSignal()
    next_item = pyqtSignal()
    prev_item = pyqtSignal()
    track_ended = pyqtSignal()
    progress_update = pyqtSignal(str, float, float, bool)
```

In `_build_ui`, after the transport `controls` layout is added (after `root.addLayout(controls)`, before `root.addStretch(1)`), add the up-next label:

```python
        self._up_next_label = QLabel("")
        self._up_next_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._up_next_label.setStyleSheet(
            f"color: {theme.TEXT_SECONDARY}; font-size: {theme.FONT_BODY}pt; "
            f"background: transparent;"
        )
        self._up_next_label.setVisible(False)
        root.addWidget(self._up_next_label)
```

Add the two new public methods near `set_audio_tracks`:

```python
    def show_up_next(self, message: str) -> None:
        self._up_next_label.setText(message)
        self._up_next_label.setVisible(True)

    def hide_up_next(self) -> None:
        self._up_next_label.setVisible(False)
```

Change `_handle_end_of_track`:

```python
    @pyqtSlot()
    def _handle_end_of_track(self) -> None:
        self._sync_progress()
        self.track_ended.emit()
```

(Was: `self.next_item.emit()` — that line is now gone; `next_item.emit()` no longer appears anywhere in this file except wherever the manual-skip button/key path already emits it, which this task does not touch.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_player_screen.py -v`
Expected: PASS.

- [ ] **Step 5: Grep-confirm `next_item.emit()` isn't reachable from `_handle_end_of_track` anymore**

Run: `grep -n "next_item.emit\|track_ended.emit" src/sixpack/ui/screens/player.py` — confirm exactly one `track_ended.emit()` (inside `_handle_end_of_track`) and that any remaining `next_item.emit()`/`prev_item.emit()` calls are the ones already wired to the manual skip buttons (`self._next_btn.clicked.connect(self.next_item)` / `self._prev_btn.clicked.connect(self.prev_item)`), unchanged from before this task.

- [ ] **Step 6: Run the full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` (3 times)
Expected: all passing, coverage ≥80%.

- [ ] **Step 7: Commit**

```bash
git add src/sixpack/ui/screens/player.py tests/test_ui/test_player_screen.py
git commit -m "Add PlayerScreen up-next display and track_ended signal"
```

---

## Task 3: End-of-book navigation in `app.py`

**Files:**
- Modify: `src/sixpack/ui/app.py`
- Test: `tests/test_ui/test_app.py`

**Interfaces:**
- Consumes: `PlayerScreen.track_ended` (Task 2), `PlayerScreen.show_up_next(str)`/`hide_up_next()` (Task 2), `DetailGridScreen.focus_item_by_key(key: str)` (already exists on `SeriesDetailScreen`/`PlaylistDetailScreen`).
- Produces: `MainWindow._on_track_ended() -> None`, `MainWindow._advance_after_up_next(target) -> None` (internal, `target` is whatever small structure Step 3 below defines).

Read `src/sixpack/ui/app.py` in full before starting this task — specifically the constructor's signal-wiring block (where `self._player_screen.next_item.connect(self._on_next_item)` etc. currently live, around line 138-141), `_on_next_item`/`_on_prev_item` (around line 433-449, KEEP THESE UNCHANGED), `_on_play_requested`/`_on_playlist_item_play_requested`/`_on_browse_item_play_requested` (to see how `self._current_series`/`self._current_playlist` get set and what state is available), and `_show_detail`/`_show_playlist_detail`/`_show_browse` (the navigation methods you'll call from the new handler). The exact attribute names for "current series books list" / "current playlist items list" must be read from the live file, not assumed — the plan text below describes the shape, not verbatim current code.

- [ ] **Step 1: Read the current file's relevant sections** (listed above) and confirm: how `self._current_series`/`self._current_playlist` are tracked, whether there's already a "current book"/"current playlist item" instance attribute on `MainWindow` (if `PlayerScreen` already exposes `_current_book`/`_current_playlist_item`/`_current_index` as used by `_on_next_item`, reuse those exact same attributes rather than re-deriving state a different way — `_on_next_item`'s existing body, which you are NOT changing, is your reference for how this state is currently read).

- [ ] **Step 2: Write the failing test**

`tests/test_ui/test_app.py` currently has ONE test (`test_main_window_constructs_without_error`) that constructs `MainWindow` inline (with `monkeypatch.setattr(app_module, "AudioPlayer", _FakeAudioPlayer)`, `AppConfig()`, `qtbot.addWidget`, and `window.close()` at the end for clean `QThread` teardown) — there is no shared `window` fixture yet. Since this task adds two new tests needing the same full-`MainWindow` setup, add a `window` pytest fixture to this file (mirroring the existing inline pattern exactly, including the `monkeypatch` and the `window.close()` cleanup via fixture teardown, e.g. `yield window` then `window.close()`), and refactor the existing test to use it too — a real, justified small dedup, not scope creep, since you're the one introducing the second/third consumer that makes the duplication worth removing.

```python
def test_on_track_ended_navigates_to_series_detail_with_next_focused(window, qtbot):
    """Automatic end-of-track must NOT auto-play the next book — it shows
    an up-next message, then lands on the series detail screen with the
    next book pre-focused, per this plan's end-of-book behavior change."""
    from sixpack.api.models import Series, SeriesBook, LibraryItemMedia

    media1 = LibraryItemMedia(metadata={"title": "Book 1"}, duration=100.0)
    media2 = LibraryItemMedia(metadata={"title": "Book 2"}, duration=100.0)
    b1 = SeriesBook(id="b1", libraryId="lib1", media=media1, sequence="1")
    b2 = SeriesBook(id="b2", libraryId="lib1", media=media2, sequence="2")
    series = Series(id="s1", name="A Series", books=[b1, b2])

    window._current_series = series
    window._player_screen._current_book = b1
    window._player_screen._series_books = [b1, b2]
    window._player_screen._current_index = 0

    window._on_track_ended()
    # up-next message shown synchronously; navigation happens after a timer
    assert window._player_screen._up_next_label.isVisible()

    qtbot.wait(window._UP_NEXT_DELAY_MS + 200)

    assert window._stack.currentWidget() is window._detail_screen
    assert window._detail_screen._grid._focused_index == 1  # b2 pre-focused


def test_on_track_ended_standalone_item_returns_to_browse(window, qtbot):
    """A library item played with no series/playlist context has no 'next'
    grid to return to — lands on Browse, per the spec's explicitly-flagged
    open implementation detail."""
    window._current_series = None
    window._current_playlist = None
    window._player_screen._current_book = None
    window._player_screen._current_playlist_item = None
    window._player_screen._series_books = []
    window._player_screen._playlist_items = []

    window._on_track_ended()
    qtbot.wait(window._UP_NEXT_DELAY_MS + 200)

    assert window._stack.currentWidget() is window._browse_screen
```

Check `window` fixture's exact attribute names (`_browse_screen`, `_detail_screen`, `_stack`, etc.) against the real `test_app.py`/`app.py` before finalizing — these must match the live code, not be assumed from this snippet.

- [ ] **Step 3: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_app.py -v -k track_ended`
Expected: FAIL — `AttributeError: 'MainWindow' object has no attribute '_on_track_ended'`.

- [ ] **Step 4: Implement**

In `app.py`'s constructor, alongside the existing `self._player_screen.next_item.connect(self._on_next_item)` / `.prev_item.connect(self._on_prev_item)` lines, add:

```python
        self._player_screen.track_ended.connect(self._on_track_ended)
```

Add a module-level or class-level constant near the top of the file (wherever similar small tuning constants for this file already live, or as a class attribute on `MainWindow`):

```python
    _UP_NEXT_DELAY_MS = 3000
```

Add the new handler near `_on_next_item`/`_on_prev_item` (which stay exactly as they are):

```python
    def _on_track_ended(self) -> None:
        book = self._player_screen._current_book
        books = self._player_screen._series_books
        playlist_item = self._player_screen._current_playlist_item
        playlist_items = self._player_screen._playlist_items

        if book is not None and books:
            idx = books.index(book) if book in books else -1
            if 0 <= idx < len(books) - 1:
                target = ("series", books[idx + 1].id)
                message = f"Up next: {books[idx + 1].title}"
            else:
                target = ("series", None)
                message = "End of series"
        elif playlist_item is not None and playlist_items:
            idx = playlist_items.index(playlist_item) if playlist_item in playlist_items else -1
            if 0 <= idx < len(playlist_items) - 1:
                target = ("playlist", playlist_items[idx + 1].library_item_id)
                message = f"Up next: {playlist_items[idx + 1].title}"
            else:
                target = ("playlist", None)
                message = "End of playlist"
        else:
            target = ("browse", None)
            message = ""

        if message:
            self._player_screen.show_up_next(message)
        QTimer.singleShot(self._UP_NEXT_DELAY_MS, lambda: self._advance_after_up_next(target))

    def _advance_after_up_next(self, target: tuple[str, str | None]) -> None:
        self._player_screen.hide_up_next()
        kind, key = target
        if kind == "series":
            self._show_detail()
            if key is not None:
                self._detail_screen.focus_item_by_key(key)
        elif kind == "playlist":
            self._show_playlist_detail()
            if key is not None:
                self._playlist_detail_screen.focus_item_by_key(key)
        else:
            self._show_browse()
```

Check `QTimer` is already imported in `app.py` (it's a common PyQt6 import; if not present, add `from PyQt6.QtCore import QTimer` to the existing import block — don't duplicate an existing import line). Check the exact method names `_show_detail`/`_show_playlist_detail`/`_show_browse` against the live file — use whatever the real navigation methods are actually called, and confirm each one is safe to call with the target screen already populated with the CURRENT series/playlist's items (it should be, since the user was already browsing that series/playlist before starting playback — but verify this assumption against the actual `_show_detail`/`_show_playlist_detail` implementations; if either one unconditionally reloads/clears the grid from scratch rather than just switching to the already-populated widget, `focus_item_by_key` needs to run AFTER that reload completes, not before — read the method bodies to confirm before finalizing this implementation).

- [ ] **Step 5: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_app.py -v -k track_ended`
Expected: PASS.

- [ ] **Step 6: Confirm `_on_next_item`/`_on_prev_item` are byte-for-byte unchanged**

Run: `git diff src/sixpack/ui/app.py` and manually confirm the diff contains no changes inside `_on_next_item`/`_on_prev_item`'s bodies, and no changes to the `next_item`/`prev_item` signal connections — only additions (`track_ended` connection, `_UP_NEXT_DELAY_MS`, `_on_track_ended`, `_advance_after_up_next`).

- [ ] **Step 7: Run the full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` (3 times)
Expected: all passing, coverage ≥80%.

- [ ] **Step 8: Commit**

```bash
git add src/sixpack/ui/app.py tests/test_ui/test_app.py
git commit -m "Replace end-of-track auto-advance with up-next indicator + pre-focused navigation"
```

---

## Task 4: Player screen visual redesign

**Files:**
- Modify: `src/sixpack/ui/screens/player.py`
- Test: `tests/test_ui/test_player_screen.py`

**Interfaces:** No new public methods — this task restyles existing widgets built in `_build_ui`/`_set_cover_pixmap`. Signatures of `play_book`/`play_library_item`/`play_playlist_item`/`set_audio_tracks` are unchanged.

- [ ] **Step 1: Read `browse.py`'s `Backdrop` usage and `theme.py`'s `GRADIENT_HERO_SCRIM`/`ACCENT`/`SURFACE_HIGH` tokens** to match this screen's new styling to the established visual language, and read `docs/superpowers/specs/2026-08-20-home-cinematic-redesign-design.md` if useful for the original tuning rationale (blur amount, dim overlay opacity).

- [ ] **Step 2: Add a `Backdrop` behind the whole screen**

In `_build_ui`, before building `root = QVBoxLayout(self)`, add:

```python
        self._backdrop = Backdrop(self)
        self._backdrop.lower()
```

Add the import: `from sixpack.ui.widgets.backdrop import Backdrop`. Add a `resizeEvent` override:

```python
    def resizeEvent(self, event) -> None:
        self._backdrop.setGeometry(self.rect())
        super().resizeEvent(event)
```

Remove the flat `self.setStyleSheet(f"background-color: {theme.BG};")` line in `_build_ui` (the Backdrop now provides the background) — but every label/container built afterward needs an explicit `background: transparent` in its own stylesheet if it doesn't already have one (check each: `_series_label`, `_title_label`, `_episode_label`, `_elapsed_label`, `_remaining_label`, `_up_next_label` from Task 2 — add `background: transparent;` to any that are missing it).

- [ ] **Step 3: Feed the Backdrop a cover-derived color/image**

In `play_book`/`play_library_item`/`play_playlist_item`, alongside the existing `self._cover_cache.fetch(cover_url, token, self._set_cover_pixmap)` call, also call `self._cover_cache.fetch_backdrop(cover_url, token, self._set_backdrop_pixmap)` (mirroring the pattern already established in `detail_grid.py`/`chapter_select.py`'s `_load_backdrop`). Add the callback:

```python
    def _set_backdrop_pixmap(self, pix: QPixmap) -> None:
        self._backdrop.show_image(pix)
```

(No `key=` staleness guard is needed here the way `chapter_select.py` needs one — unlike that screen, `PlayerScreen` is a single always-current "what's playing right now" surface with no reused-instance-across-different-books race in the same way multi-item grids have; a stale backdrop callback landing here would just be showing a *previous* track's cover briefly, which self-corrects on the next legitimate call. If you find a concrete reason this assumption is wrong once implementing, add the same `set_expected_key`/`key=` guard `chapter_select.py` uses and note it in your report — don't silently skip verifying.)

- [ ] **Step 4: Grow the cover art and restyle the progress bar**

Change `self._cover_label.setFixedSize(280, 280)` to `self._cover_label.setFixedSize(400, 400)` (a concrete starting value per the spec's "exact size TBD at implementation/visual-iteration time" — adjust after Step 6's screenshot check if it looks disproportionate against real content) and the matching `.scaled(280, 280, ...)` call in `_set_cover_pixmap` to `.scaled(400, 400, ...)`.

Restyle `self._progress_bar` away from the default `QProgressBar` chrome:

```python
        self._progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background: {theme.SURFACE_HIGH};
                border: none;
                border-radius: 5px;
            }}
            QProgressBar::chunk {{
                background: {theme.ACCENT};
                border-radius: 5px;
            }}
        """)
```

- [ ] **Step 5: Restyle the transport controls as static indicators**

The spec calls for these to read as "present but not focusable" (they already have `setFocusPolicy(Qt.FocusPolicy.NoFocus)` — confirm this is still true after your edits) — visually de-emphasize them relative to the accent-colored play/pause button so they don't look like a competing focus target. A reasonable approach: keep `self._play_btn`'s existing accent-filled circular style, and give the smaller transport buttons (`_prev_btn`, `_rew_btn`, `_fwd_btn`, `_next_btn`) a flatter, more muted style, e.g.:

```python
        for btn in (self._prev_btn, self._rew_btn, self._fwd_btn, self._next_btn):
            btn.setStyleSheet(
                f"background: transparent; color: {theme.TEXT_SECONDARY}; "
                f"border: none; font-size: 18pt;"
            )
```

(Apply this alongside the existing `setFocusPolicy(Qt.FocusPolicy.NoFocus)` loop, or fold into it — your call on exact placement, just don't lose the existing focus-policy line.)

- [ ] **Step 6: Verify visually against real data**

Follow this project's established verification method for this exact bug class (opaque widget hiding a `Backdrop`) and for general visual sign-off: write a throwaway offscreen screenshot script (see `/private/tmp/.../scratchpad/shots_phase_b.py` from an earlier phase for the established pattern — real server data via `ABSClient`, `QT_QPA_PLATFORM=offscreen`, render to PNG) that constructs `PlayerScreen` with a real book/cover from the `merton.home` test server, calls `play_book`/`set_audio_tracks`-equivalent state population (you may need to populate state directly without actually invoking `AudioPlayer.play()` against a real mpv instance, since screenshot scripts don't need real audio — check how earlier phases' scripts avoided constructing a real `AudioPlayer`), and renders to PNG. Look at the actual image. Confirm: the Backdrop is visible (not occluded), the cover art size looks proportionate, the progress bar reads clearly against the backdrop, transport buttons are legible but not visually competing with the accent play button.

- [ ] **Step 7: Run the full suite and existing PlayerScreen tests**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_player_screen.py tests/test_ui/test_app.py -v` then the full suite 3 times: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`
Expected: all passing, coverage ≥80%. Add/update tests for anything Step 2-5 changed that the existing tests directly assert on (e.g. if any test checks `screen.styleSheet()` or cover label fixed size, update it to match the new values — grep `tests/test_ui/test_player_screen.py` and any other file referencing `PlayerScreen` for such assertions first).

- [ ] **Step 8: Commit**

```bash
git add src/sixpack/ui/screens/player.py tests/test_ui/test_player_screen.py
git commit -m "Player screen visual redesign: Backdrop, larger cover, restyled progress/transport"
```

---

## Task 5: Playback speed control

**Files:**
- Modify: `src/sixpack/ui/screens/player.py`
- Test: `tests/test_ui/test_player_screen.py`

**Interfaces:**
- Consumes: `AudioPlayer.set_speed(float)` (Task 1).
- Produces: `PlayerScreen._cycle_speed() -> None` (internal), a `_speed_label` widget showing the current speed, `InputAction.UP` handled in `keyPressEvent` (player mode).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_ui/test_player_screen.py`:

```python
def test_speed_starts_at_1x(screen):
    assert screen._speed_label.text() == "1.0x"


def test_up_key_cycles_speed_forward(qtbot, screen):
    screen.show()
    qtbot.waitExposed(screen)
    qtbot.keyClick(screen, Qt.Key.Key_Up)
    assert screen._speed_label.text() == "1.25x"
    assert screen._player.speed_calls == [1.25]


def test_speed_cycle_wraps_around(qtbot, screen):
    screen.show()
    qtbot.waitExposed(screen)
    for _ in range(5):  # 1.0 -> 1.25 -> 1.5 -> 1.75 -> 2.0 -> 1.0
        qtbot.keyClick(screen, Qt.Key.Key_Up)
    assert screen._speed_label.text() == "1.0x"
    assert screen._player.speed_calls[-1] == 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_player_screen.py -v -k speed`
Expected: FAIL.

- [ ] **Step 3: Implement**

In `player.py`, add a module-level constant near `_fmt_time`:

```python
_SPEED_STEPS = [1.0, 1.25, 1.5, 1.75, 2.0]
```

In `__init__`, add `self._speed_index = 0` alongside the other instance state (e.g. near `self._duration`/`self._position`).

In `_build_ui`, add a speed label — place it in the `times` row alongside `_elapsed_label`/`_remaining_label`, or directly in the `controls` row near `_play_btn`; either is reasonable, pick whichever reads cleaner once you see it (this is a small visual-placement call, not a design decision requiring a plan amendment):

```python
        self._speed_label = QLabel("1.0x")
        self._speed_label.setStyleSheet(
            f"color: {theme.TEXT_SECONDARY}; font-size: {theme.FONT_META}pt; "
            f"background: transparent;"
        )
        controls.addWidget(self._speed_label)
```

Add the cycling method near `_sync_progress`:

```python
    def _cycle_speed(self) -> None:
        self._speed_index = (self._speed_index + 1) % len(_SPEED_STEPS)
        speed = _SPEED_STEPS[self._speed_index]
        self._player.set_speed(speed)
        self._speed_label.setText(f"{speed}x")
```

In `keyPressEvent`, add a branch (placement within the existing `if/elif` chain doesn't matter functionally — add it wherever reads clearest, e.g. after the `PLAY_PAUSE` branch):

```python
        elif action == InputAction.UP:
            self._cycle_speed()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_player_screen.py -v -k speed`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` (3 times)
Expected: all passing, coverage ≥80%.

- [ ] **Step 6: Commit**

```bash
git add src/sixpack/ui/screens/player.py tests/test_ui/test_player_screen.py
git commit -m "Add playback speed control (InputAction.UP cycles 1.0x-2.0x)"
```

---

## Task 6: In-player chapter access overlay

**Files:**
- Modify: `src/sixpack/ui/screens/player.py`
- Modify: `src/sixpack/ui/screens/chapter_select.py` (only if Step 1 finds something genuinely blocking reuse — see below)
- Test: `tests/test_ui/test_player_screen.py`

**Interfaces:**
- Consumes: `ChapterItem`, `_chapter_status`, `_chapter_fraction` from `chapter_select.py` (already module-level, exported implicitly by being public names in that module — `from sixpack.ui.screens.chapter_select import ChapterItem, _chapter_status, _chapter_fraction`). `AudioPlayer.seek_to_chapter(int)` (Task 1).
- Produces: `PlayerScreen._chapter_overlay` (a `QListWidget`, structurally mirroring `ChapterSelectScreen._list`), `PlayerScreen._toggle_chapter_overlay() -> None`, `InputAction.MENU` handled in `keyPressEvent` to open/close it, `InputAction.SELECT`/`UP`/`DOWN`/`BACK` re-routed to the overlay's own navigation while it's open.

**This task needs the current book's chapter list, which `PlayerScreen` does not currently receive.** `play_book`/`play_library_item`/`play_playlist_item` are called from `app.py` with the book/item but not its chapters (chapters are fetched separately, via `app.py`'s existing chapter-fetching flow that currently feeds `ChapterSelectScreen`). Before writing any UI code:

- [ ] **Step 1: Trace how `app.py` currently obtains chapters** for a book/playlist-item/library-item (grep for `.chapters` and the `_async_get_book_chapters`-style methods referenced in this plan's Task 3 dispatch context, or equivalent) and how it flows to `ChapterSelectScreen.load*`. Decide the smallest correct way to also hand this same chapter list to `PlayerScreen` when playback actually starts — the two most likely shapes are (a) add an optional `chapters: list[Chapter] | None = None` parameter to `play_book`/`play_library_item`/`play_playlist_item`, populated by `app.py` wherever it already has the chapter list in hand before calling these methods, or (b) a new `PlayerScreen.set_chapters(chapters: list[Chapter]) -> None` called separately by `app.py` right after the `play_*` call. Prefer (a) if `app.py` already has the chapters available at the same call site as the existing `play_*` calls (check the call sites from Task 3's `_on_play_requested`/`_on_browse_item_play_requested`/playlist-item equivalent) — it keeps construction atomic and avoids an ordering bug where playback starts before chapters are set. If chapters are NOT reliably available at those call sites (e.g. some paths skip chapter-select and never fetch chapters at all — a single-chapter book, for instance), (b) with a safe "no chapters, overlay does nothing" fallback is the right shape. State which you chose and why in your task report — this is a real implementation decision this plan is deliberately leaving to you because it depends on `app.py`'s exact current call graph, not because it doesn't matter.

- [ ] **Step 2: Write the failing tests**

Add to `tests/test_ui/test_player_screen.py` (adjust the exact `play_book`/`set_chapters` call based on Step 1's decision):

```python
def test_menu_key_opens_chapter_overlay(qtbot, screen):
    from sixpack.api.models import Chapter
    chapters = [Chapter(id=0, start=0.0, end=100.0, title="Ch1"),
                Chapter(id=1, start=100.0, end=200.0, title="Ch2")]
    # Adjust this call per Step 1's decision — either pass chapters= to
    # play_book, or call screen.set_chapters(chapters) separately.
    screen._chapters = chapters  # placeholder — replace with the real API
    screen.show()
    qtbot.waitExposed(screen)

    assert not screen._chapter_overlay.isVisible()
    qtbot.keyClick(screen, Qt.Key.Key_Return)  # MENU in player mode
    assert screen._chapter_overlay.isVisible()


def test_menu_key_closes_open_overlay(qtbot, screen):
    from sixpack.api.models import Chapter
    screen._chapters = [Chapter(id=0, start=0.0, end=100.0, title="Ch1")]
    screen.show()
    qtbot.waitExposed(screen)
    qtbot.keyClick(screen, Qt.Key.Key_Return)
    assert screen._chapter_overlay.isVisible()
    qtbot.keyClick(screen, Qt.Key.Key_Return)
    assert not screen._chapter_overlay.isVisible()


def test_select_in_overlay_seeks_and_closes(qtbot, screen):
    from sixpack.api.models import Chapter
    screen._chapters = [Chapter(id=0, start=0.0, end=100.0, title="Ch1"),
                         Chapter(id=1, start=100.0, end=200.0, title="Ch2")]
    screen.show()
    qtbot.waitExposed(screen)
    qtbot.keyClick(screen, Qt.Key.Key_Return)  # open
    screen._chapter_overlay.setCurrentRow(1)
    qtbot.keyClick(screen, Qt.Key.Key_Return)  # select — closes AND seeks

    assert screen._player.seek_to_chapter_calls == [1]
    assert not screen._chapter_overlay.isVisible()


def test_back_closes_overlay_without_seeking(qtbot, screen):
    from sixpack.api.models import Chapter
    screen._chapters = [Chapter(id=0, start=0.0, end=100.0, title="Ch1")]
    screen.show()
    qtbot.waitExposed(screen)
    qtbot.keyClick(screen, Qt.Key.Key_Return)  # open
    qtbot.keyClick(screen, Qt.Key.Key_Escape)  # BACK

    assert screen._player.seek_to_chapter_calls == []
    assert not screen._chapter_overlay.isVisible()
```

Update these to use whichever real API Step 1 settled on instead of the `screen._chapters = chapters` placeholder — that line is illustrative of the test *setup intent* (get chapters into the screen), not literal code to keep.

- [ ] **Step 3: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_player_screen.py -v -k overlay`
Expected: FAIL.

- [ ] **Step 4: Implement chapter delivery** per Step 1's decision (either extend `play_book`/`play_library_item`/`play_playlist_item`'s signatures with `chapters: list[Chapter] | None = None`, storing `self._chapters = chapters or []`, or add a standalone `set_chapters` method). If you extend the `play_*` signatures, update every call site in `app.py` accordingly (grep for each method name) and confirm this doesn't violate this plan's Global Constraints — re-read that section: **only `set_audio_tracks` and `play_book`/`play_library_item`/`play_playlist_item`'s EXISTING parameters are protected from changes there; adding a new trailing optional parameter with a default is a backward-compatible extension, not a breaking signature change, but state explicitly in your report that you read the constraint that way and why it's satisfied.**

- [ ] **Step 5: Build the overlay**

In `_build_ui`, construct the overlay as a child widget (initially hidden), positioned/sized in `resizeEvent` to cover a reasonable portion of the screen (e.g. centered, ~60% width, most of the height) — mirror `chapter_select.py`'s `QListWidget` construction (spacing, transparent-but-with-a-visible-scrim styling so it reads as a modal over the player, not part of the base layout) rather than adding it to `root`'s layout flow directly:

```python
        self._chapter_overlay = QListWidget(self)
        self._chapter_overlay.setSpacing(2)
        self._chapter_overlay.setStyleSheet(f"""
            QListWidget {{
                background: {theme.SURFACE};
                border: 2px solid {theme.ACCENT};
                border-radius: 8px;
                outline: none;
            }}
            QListWidget::item {{ padding: 0; margin: 2px 0; border: none; }}
            QListWidget::item:selected {{ background-color: transparent; }}
        """)
        self._chapter_overlay.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._chapter_overlay.itemActivated.connect(self._on_overlay_chapter_activated)
        self._chapter_overlay.hide()
```

Add to `resizeEvent` (alongside the `Backdrop` geometry line from Task 4):

```python
        w, h = int(self.width() * 0.6), int(self.height() * 0.7)
        self._chapter_overlay.setGeometry((self.width() - w) // 2, (self.height() - h) // 2, w, h)
```

Add the import: `from sixpack.ui.screens.chapter_select import ChapterItem, _chapter_status, _chapter_fraction` and `from PyQt6.QtWidgets import QListWidget, QListWidgetItem` (add to the existing `PyQt6.QtWidgets` import line rather than a new line, if one already exists in this file — check first).

- [ ] **Step 6: Populate and toggle the overlay**

```python
    def _toggle_chapter_overlay(self) -> None:
        if self._chapter_overlay.isVisible():
            self._chapter_overlay.hide()
            return
        if not self._chapters:
            return
        self._chapter_overlay.clear()
        current_time = self._position
        for i, chapter in enumerate(self._chapters):
            status = _chapter_status(chapter, current_time, is_finished=False)
            fraction = _chapter_fraction(chapter, current_time, status)
            widget = ChapterItem(i, chapter, status, fraction)
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 68))
            self._chapter_overlay.addItem(item)
            self._chapter_overlay.setItemWidget(item, widget)
        self._chapter_overlay.setCurrentRow(self._current_chapter_index())
        self._chapter_overlay.show()

    def _current_chapter_index(self) -> int:
        for i, chapter in enumerate(self._chapters):
            if self._position < chapter.end:
                return i
        return max(0, len(self._chapters) - 1)

    def _on_overlay_chapter_activated(self, item: QListWidgetItem) -> None:
        row = self._chapter_overlay.row(item)
        self._player.seek_to_chapter(row)
        self._chapter_overlay.hide()
```

Add `from PyQt6.QtCore import QSize` to the existing `PyQt6.QtCore` import line if `QSize` isn't already imported there.

- [ ] **Step 7: Wire keyboard handling**

In `keyPressEvent`, the overlay needs to intercept SELECT/BACK/UP/DOWN *while open*, before the normal player-mode handling runs (opening chapters shouldn't also seek ±30s via the normal SEEK_FORWARD/BACK bindings, etc. — check `_PLAYER_MAP` for exactly which actions might otherwise collide and decide whether to gate the whole `if/elif` chain behind an `if self._chapter_overlay.isVisible():` early branch, or handle the overlay-specific actions first and `return` before falling into the rest of the chain). Add near the top of `keyPressEvent`, before the existing `action = key_to_action(...)` line's `if/elif` chain is evaluated for its normal branches:

```python
        action = key_to_action(event.key(), player_mode=True)

        if self._chapter_overlay.isVisible():
            if action == InputAction.BACK:
                self._chapter_overlay.hide()
            elif action == InputAction.MENU:
                self._chapter_overlay.hide()
            elif action == InputAction.SELECT:
                current = self._chapter_overlay.currentItem()
                if current:
                    self._on_overlay_chapter_activated(current)
            elif action == InputAction.UP:
                row = self._chapter_overlay.currentRow()
                if row > 0:
                    self._chapter_overlay.setCurrentRow(row - 1)
            elif action == InputAction.DOWN:
                row = self._chapter_overlay.currentRow()
                if row + 1 < self._chapter_overlay.count():
                    self._chapter_overlay.setCurrentRow(row + 1)
            return

        if action == InputAction.MENU:
            self._toggle_chapter_overlay()
        elif action == InputAction.BACK:
```

This replaces the existing `action = key_to_action(...)` line and the start of the `if/elif` chain — the rest of the existing chain (`PLAY_PAUSE`, `STOP`, `SEEK_FORWARD`, etc., plus Task 5's new `UP` branch) continues unchanged below this, all still reachable when the overlay is closed. Read the current full `keyPressEvent` body (shown in this plan's Task 5, Step 3, plus everything below it in the live file) before editing so the merge is exact — don't duplicate the `action = key_to_action(...)` line.

- [ ] **Step 8: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_player_screen.py -v -k overlay`
Expected: PASS.

- [ ] **Step 9: Run the full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` (3 times)
Expected: all passing, coverage ≥80%.

- [ ] **Step 10: Commit**

```bash
git add src/sixpack/ui/screens/player.py tests/test_ui/test_player_screen.py src/sixpack/ui/app.py
git commit -m "Add in-player chapter access overlay (InputAction.MENU)"
```

---

## Self-Review

**Spec coverage:** All 3 "New functionality" bullets from the spec's Phase C section covered (Tasks 5, 6, and 2+3 together for up-next). The spec's "Visual" paragraph covered by Task 4. The end-of-book behavior change (filed under the spec's Phase B heading but never actually implemented in Phase A/B's real task lists — confirmed by grepping the current `app.py` for the still-present unconditional auto-advance) covered by Tasks 2+3, with the standalone-item fallback the spec explicitly flagged as needing to not be silently dropped (Task 3, `_advance_after_up_next`'s `"browse"` branch). ✓

**Placeholder scan:** Task 6 is the one task with a genuine open implementation decision (Step 1, how chapters reach `PlayerScreen`) — flagged explicitly as a real decision for the implementer to make and justify, not a vague "figure it out," consistent with how this plan's spec itself flagged its own open items. All other tasks specify exact code.

**Type consistency:** `AudioPlayer.set_speed(speed: float)`/`seek_to_chapter(index: int)` (Task 1) consumed identically in Task 5/6. `PlayerScreen.track_ended`/`show_up_next(str)`/`hide_up_next()` (Task 2) consumed identically in Task 3. `ChapterItem`/`_chapter_status`/`_chapter_fraction` imported with the same names they're defined with in `chapter_select.py` (Task 6).
