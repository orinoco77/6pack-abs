# Mouse Input Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore mouse click/hover support across SixPack's custom, keyboard-only widgets (`MediaCard`, `ChapterItem`, `_SidebarItem`) without touching the keyboard/gamepad-first navigation model — every mouse action reuses the exact method a keyboard Select-tap or hold already calls.

**Architecture:** Each affected widget gains a `hovered` signal (from `enterEvent`) and click/hold detection on `mousePressEvent`/`mouseReleaseEvent` (mirroring `FocusGrid`'s existing 500ms-hold-with-elapsed-backstop pattern where a hold gesture applies). Host screens connect these signals to their own existing, unchanged focus-move/activation methods — no new activation logic anywhere, no changes to directional (arrow-key/D-pad) navigation.

**Tech Stack:** Python 3.12, PyQt6, pytest-qt (`qtbot`), offscreen Qt platform for tests (already configured in `tests/conftest.py`).

**Spec:** `docs/superpowers/specs/2026-08-28-mouse-input-support-design.md`

## Global Constraints

- Hover moves the keyboard-style focus highlight (calls the same method an arrow key already calls) — this applies everywhere in this plan.
- A single left-click activates (no double-click anywhere in this app after this plan).
- The long-press-to-mark-finished threshold is 500ms, matching `FocusGrid`/`BrowseScreen`'s existing constant, and must include the same wall-clock (`QElapsedTimer`) backstop against a GUI-thread stall swallowing the `QTimer` callback — do not reintroduce the race that pattern was built to fix.
- A mouse-button release outside the widget's own `rect()` cancels silently (no `activated`/`long_pressed`) — matches normal button drag-off behavior.
- No right-click menus. No hover-tracking on `PlayerScreen`'s control row (out of scope — see spec's Non-goals).
- Run the full test suite (`python -m pytest --no-cov -q`, from the repo root with `.venv` activated and `QT_QPA_PLATFORM=offscreen`) and `ruff check src tests` before every commit in this plan.

---

## Task 1: `MediaCard` — hover moves focus

**Files:**
- Modify: `src/sixpack/ui/widgets/media_card.py:1-16` (imports), `:122` (signals), new `enterEvent` method
- Test: `tests/test_ui/test_widgets.py` (MediaCard section, near line 479)

**Interfaces:**
- Produces: `MediaCard.hovered` signal (`pyqtSignal()`), emitted from a new `enterEvent(self, event)` override.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_ui/test_widgets.py`, near the existing `test_media_card_mouse_press_no_crash`:

```python
def test_media_card_enter_emits_hovered(qtbot):
    from PyQt6.QtCore import QEvent

    card = MediaCard(title="Test")
    qtbot.addWidget(card)

    hovered = []
    card.hovered.connect(lambda: hovered.append(True))

    card.enterEvent(QEvent(QEvent.Type.Enter))

    assert hovered == [True]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/ajs/RiderProjects/6pack-abs && source .venv/bin/activate && QT_QPA_PLATFORM=offscreen python -m pytest tests/test_ui/test_widgets.py::test_media_card_enter_emits_hovered -v --no-cov`
Expected: FAIL with `AttributeError: 'MediaCard' object has no attribute 'hovered'`

- [ ] **Step 3: Add the signal and `enterEvent` override**

In `src/sixpack/ui/widgets/media_card.py`, change the import line (currently line 6):

```python
from PyQt6.QtCore import QEvent, QSize, Qt, pyqtSignal
```

(unchanged — `QEvent` is already imported; no import change needed for this task).

Change the class-level signal declaration (currently line 122):

```python
    activated = pyqtSignal()
```

to:

```python
    activated = pyqtSignal()
    hovered = pyqtSignal()
```

Add this method near `keyPressEvent` (currently at line 317), right before it:

```python
    def enterEvent(self, event) -> None:
        self.hovered.emit()
        super().enterEvent(event)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/ajs/RiderProjects/6pack-abs && source .venv/bin/activate && QT_QPA_PLATFORM=offscreen python -m pytest tests/test_ui/test_widgets.py::test_media_card_enter_emits_hovered -v --no-cov`
Expected: PASS

- [ ] **Step 5: Run the full suite and lint, then commit**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest --no-cov -q` — expect all passing (no regressions).
Run: `ruff check src tests` — expect no findings.

```bash
git add src/sixpack/ui/widgets/media_card.py tests/test_ui/test_widgets.py
git commit -m "Add hovered signal to MediaCard"
```

---

## Task 2: `MediaCard` — single-click activates, mouse hold triggers long-press, drag-off cancels

**Files:**
- Modify: `src/sixpack/ui/widgets/media_card.py`
- Test: `tests/test_ui/test_widgets.py`

**Interfaces:**
- Consumes: `MediaCard.hovered` (Task 1, unaffected by this task).
- Produces: `MediaCard.long_pressed` signal (`pyqtSignal()`). `MediaCard.activated` (already existed) now fires on single click release instead of double-click. `mouseDoubleClickEvent` is removed.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_ui/test_widgets.py`, right after `test_media_card_enter_emits_hovered`:

```python
def test_media_card_single_click_emits_activated(qtbot):
    from PyQt6.QtCore import Qt

    card = MediaCard(title="Test")
    qtbot.addWidget(card)
    card.show()

    activated = []
    long_pressed = []
    card.activated.connect(lambda: activated.append(True))
    card.long_pressed.connect(lambda: long_pressed.append(True))

    qtbot.mouseClick(card, Qt.MouseButton.LeftButton)

    assert activated == [True]
    assert long_pressed == []


def test_media_card_held_click_emits_long_pressed_not_activated(qtbot):
    import time

    from PyQt6.QtCore import Qt

    card = MediaCard(title="Test")
    qtbot.addWidget(card)
    card.show()

    activated = []
    long_pressed = []
    card.activated.connect(lambda: activated.append(True))
    card.long_pressed.connect(lambda: long_pressed.append(True))

    qtbot.mousePress(card, Qt.MouseButton.LeftButton)
    # A plain time.sleep (unlike qtbot.wait) blocks the thread without
    # pumping Qt's event loop, so it deterministically prevents the
    # 500ms hold QTimer from firing during the "hold" -- proving the
    # wall-clock elapsed-time backstop (not just the timer callback)
    # is what resolves this as a hold, mirroring FocusGrid's own
    # stalled-main-thread regression test.
    time.sleep(0.6)
    qtbot.mouseRelease(card, Qt.MouseButton.LeftButton)

    assert long_pressed == [True]
    assert activated == []


def test_media_card_release_outside_rect_cancels_silently(qtbot):
    from PyQt6.QtCore import QPoint, Qt

    card = MediaCard(title="Test")
    qtbot.addWidget(card)
    card.show()

    activated = []
    long_pressed = []
    card.activated.connect(lambda: activated.append(True))
    card.long_pressed.connect(lambda: long_pressed.append(True))

    qtbot.mousePress(card, Qt.MouseButton.LeftButton)
    qtbot.mouseRelease(card, Qt.MouseButton.LeftButton, pos=QPoint(-10, -10))

    assert activated == []
    assert long_pressed == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/ajs/RiderProjects/6pack-abs && source .venv/bin/activate && QT_QPA_PLATFORM=offscreen python -m pytest tests/test_ui/test_widgets.py -k "media_card_single_click or media_card_held_click or media_card_release_outside" -v --no-cov`
Expected: FAIL — `test_media_card_single_click_emits_activated` fails because `activated` isn't emitted on a single click yet (only on double-click); the other two fail with `AttributeError: 'MediaCard' object has no attribute 'long_pressed'`.

- [ ] **Step 3: Implement click/hold detection**

In `src/sixpack/ui/widgets/media_card.py`, update the import line (currently line 6):

```python
from PyQt6.QtCore import QElapsedTimer, QEvent, QSize, Qt, QTimer, pyqtSignal
```

Add the new signal next to `hovered` (from Task 1):

```python
    activated = pyqtSignal()
    hovered = pyqtSignal()
    long_pressed = pyqtSignal()
```

Add a class constant near `_PLACEHOLDER_GLYPH` (currently line 124):

```python
    _HOLD_MS = 500
```

In `__init__` (currently lines 126-148), after `self._focused = False` (currently line 146) and before `self._build_ui()`, add:

```python
        # Mouse-hold detection, mirroring FocusGrid's own 500ms
        # hold-vs-click pattern (QTimer + QElapsedTimer wall-clock
        # backstop, so a GUI-thread stall during the hold can't make a
        # genuine hold silently resolve as a click -- see FocusGrid's
        # keyReleaseEvent docstring for the full reasoning this mirrors).
        self._pressed = False
        self._press_resolved_as_hold = False
        self._hold_timer = QTimer(self)
        self._hold_timer.setSingleShot(True)
        self._hold_timer.setInterval(self._HOLD_MS)
        self._hold_timer.timeout.connect(self._on_hold_timeout)
        self._press_elapsed = QElapsedTimer()
```

Replace the existing `mouseDoubleClickEvent` (currently the last two lines of the file, 326-327):

```python
    def mouseDoubleClickEvent(self, event) -> None:
        self.activated.emit()
```

with:

```python
    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        self._pressed = True
        self._press_resolved_as_hold = False
        self._hold_timer.start()
        self._press_elapsed.start()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or not self._pressed:
            super().mouseReleaseEvent(event)
            return
        self._pressed = False
        self._hold_timer.stop()
        if (
            not self._press_resolved_as_hold
            and self._press_elapsed.elapsed() >= self._HOLD_MS
        ):
            self._press_resolved_as_hold = True
            self.long_pressed.emit()
        if self._press_resolved_as_hold:
            return
        # A release outside the card (dragged off before letting go)
        # cancels silently, matching normal button behavior -- mouse-only,
        # there's no keyboard equivalent of "drag off" to keep in sync with.
        if self.rect().contains(event.pos()):
            self.activated.emit()

    def _on_hold_timeout(self) -> None:
        self._press_resolved_as_hold = True
        self.long_pressed.emit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/ajs/RiderProjects/6pack-abs && source .venv/bin/activate && QT_QPA_PLATFORM=offscreen python -m pytest tests/test_ui/test_widgets.py -k "media_card" -v --no-cov`
Expected: All PASS, including the pre-existing `test_media_card_mouse_press_no_crash`.

- [ ] **Step 5: Run the full suite and lint, then commit**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest --no-cov -q` — expect all passing.
Run: `ruff check src tests` — expect no findings.

```bash
git add src/sixpack/ui/widgets/media_card.py tests/test_ui/test_widgets.py
git commit -m "Replace MediaCard double-click with single-click + mouse-hold detection"
```

---

## Task 3: `FocusGrid` — wire `MediaCard`'s mouse signals

**Files:**
- Modify: `src/sixpack/ui/widgets/focus_grid.py:66-76` (`add_item`)
- Test: `tests/test_ui/test_widgets.py` (FocusGrid section)

**Interfaces:**
- Consumes: `MediaCard.hovered`, `MediaCard.long_pressed` (Tasks 1-2), `FocusGrid.focus_item(index: int)` and `FocusGrid.long_press_activated` (both pre-existing, unchanged).

This is the only task needed to make every `FocusGrid`-hosted screen (Series/Playlist/Podcast detail grids) fully mouse-capable — `DetailGridScreen` and its subclasses only ever talk to `FocusGrid`'s public signals, so they need no changes at all.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_ui/test_widgets.py`, near the existing FocusGrid hold-detection tests (after `test_long_press_uses_currently_focused_index`):

```python
def test_focus_grid_card_hover_moves_focus(qtbot):
    grid = FocusGrid(columns=3)
    qtbot.addWidget(grid)
    for title in ("A", "B", "C"):
        grid.add_item(MediaCard(title=title))
    grid.show()
    grid.setFocus()

    assert grid.focused_index == 0
    grid._items[2].hovered.emit()

    assert grid.focused_index == 2


def test_focus_grid_card_long_press_emits_long_press_activated(qtbot):
    grid = FocusGrid(columns=3)
    qtbot.addWidget(grid)
    for title in ("A", "B"):
        grid.add_item(MediaCard(title=title))
    grid.show()
    grid.setFocus()
    grid.focus_item(1)

    long_pressed = []
    grid.long_press_activated.connect(lambda idx: long_pressed.append(idx))

    grid._items[1].long_pressed.emit()

    assert long_pressed == [1]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/ajs/RiderProjects/6pack-abs && source .venv/bin/activate && QT_QPA_PLATFORM=offscreen python -m pytest tests/test_ui/test_widgets.py -k "focus_grid_card_hover or focus_grid_card_long_press" -v --no-cov`
Expected: FAIL — `test_focus_grid_card_hover_moves_focus` fails because `focused_index` stays `0`; `test_focus_grid_card_long_press_emits_long_press_activated` fails because `long_pressed` is empty (nothing connected to it yet).

- [ ] **Step 3: Wire the signals in `add_item`**

In `src/sixpack/ui/widgets/focus_grid.py`, the current `add_item` (lines 66-76) is:

```python
    def add_item(self, widget: QWidget) -> int:
        index = len(self._items)
        self._items.append(widget)
        row = index // self._columns
        col = index % self._columns
        self._grid.addWidget(widget, row, col)

        if hasattr(widget, "activated"):
            widget.activated.connect(lambda idx=index: self.item_activated.emit(idx))

        return index
```

Change it to:

```python
    def add_item(self, widget: QWidget) -> int:
        index = len(self._items)
        self._items.append(widget)
        row = index // self._columns
        col = index % self._columns
        self._grid.addWidget(widget, row, col)

        if hasattr(widget, "activated"):
            widget.activated.connect(lambda idx=index: self.item_activated.emit(idx))
        if hasattr(widget, "hovered"):
            widget.hovered.connect(lambda idx=index: self.focus_item(idx))
        if hasattr(widget, "long_pressed"):
            widget.long_pressed.connect(lambda idx=index: self.long_press_activated.emit(idx))

        return index
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/ajs/RiderProjects/6pack-abs && source .venv/bin/activate && QT_QPA_PLATFORM=offscreen python -m pytest tests/test_ui/test_widgets.py -k "focus_grid" -v --no-cov`
Expected: All PASS.

- [ ] **Step 5: Run the full suite and lint, then commit**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest --no-cov -q` — expect all passing.
Run: `ruff check src tests` — expect no findings.

```bash
git add src/sixpack/ui/widgets/focus_grid.py tests/test_ui/test_widgets.py
git commit -m "Wire MediaCard hover/long-press into FocusGrid"
```

---

## Task 4: `ChapterItem` — hover and click signals

**Files:**
- Modify: `src/sixpack/ui/screens/chapter_select.py:145-207` (`ChapterItem`)
- Test: `tests/test_ui/test_screens.py` (chapter-select section)

**Interfaces:**
- Produces: `ChapterItem.hovered` (`pyqtSignal()`), `ChapterItem.activated` (`pyqtSignal()`).

`ChapterItem` gets no `long_pressed` — chapters have no independently-markable "finished" state (see the original mark-finished design's explicit non-goal, restated in this feature's spec).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_ui/test_screens.py`, near the other chapter-select tests (after `test_chapter_screen_down_arrow_moves_current_row`):

```python
def test_chapter_item_click_emits_activated(qtbot):
    from PyQt6.QtCore import Qt

    from sixpack.ui.screens.chapter_select import ChapterItem

    item = ChapterItem(0, _make_chapters()[0], status="unstarted")
    qtbot.addWidget(item)
    item.show()

    activated = []
    hovered = []
    item.activated.connect(lambda: activated.append(True))
    item.hovered.connect(lambda: hovered.append(True))

    qtbot.mouseClick(item, Qt.MouseButton.LeftButton)

    assert activated == [True]


def test_chapter_item_enter_emits_hovered(qtbot):
    from PyQt6.QtCore import QEvent

    from sixpack.ui.screens.chapter_select import ChapterItem

    item = ChapterItem(0, _make_chapters()[0], status="unstarted")
    qtbot.addWidget(item)

    hovered = []
    item.hovered.connect(lambda: hovered.append(True))

    item.enterEvent(QEvent(QEvent.Type.Enter))

    assert hovered == [True]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/ajs/RiderProjects/6pack-abs && source .venv/bin/activate && QT_QPA_PLATFORM=offscreen python -m pytest tests/test_ui/test_screens.py -k "chapter_item" -v --no-cov`
Expected: FAIL with `AttributeError: 'ChapterItem' object has no attribute 'activated'` (and `hovered`).

- [ ] **Step 3: Add the signals and mouse handling**

In `src/sixpack/ui/screens/chapter_select.py`, the current `ChapterItem` class (lines 145-156) is:

```python
class ChapterItem(QWidget):
    def __init__(
        self,
        index: int,
        chapter: Chapter,
        status: str,
        fraction: float = 0.0,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._build_ui(index, chapter, status, fraction)

    def _build_ui(self, index: int, chapter: Chapter, status: str, fraction: float) -> None:
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.set_focused(False)
```

Change it to:

```python
class ChapterItem(QWidget):
    hovered = pyqtSignal()
    activated = pyqtSignal()

    def __init__(
        self,
        index: int,
        chapter: Chapter,
        status: str,
        fraction: float = 0.0,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._build_ui(index, chapter, status, fraction)

    def _build_ui(self, index: int, chapter: Chapter, status: str, fraction: float) -> None:
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.set_focused(False)
```

Add these methods right after `set_focused` (currently lines 202-206, the last method in the class):

```python
    def enterEvent(self, event) -> None:
        self.hovered.emit()
        super().enterEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.pos()):
            self.activated.emit()
        super().mouseReleaseEvent(event)
```

No `mousePressEvent` override is needed here — there's no hold gesture to arm, so the click resolves entirely on release, same as a plain button.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/ajs/RiderProjects/6pack-abs && source .venv/bin/activate && QT_QPA_PLATFORM=offscreen python -m pytest tests/test_ui/test_screens.py -k "chapter_item" -v --no-cov`
Expected: All PASS.

- [ ] **Step 5: Run the full suite and lint, then commit**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest --no-cov -q` — expect all passing.
Run: `ruff check src tests` — expect no findings.

```bash
git add src/sixpack/ui/screens/chapter_select.py tests/test_ui/test_screens.py
git commit -m "Add hover/click signals to ChapterItem"
```

---

## Task 5: `ChapterSelectScreen` — wire `ChapterItem`'s mouse signals

**Files:**
- Modify: `src/sixpack/ui/screens/chapter_select.py:384-421` (`_populate_chapters`)
- Test: `tests/test_ui/test_screens.py`

**Interfaces:**
- Consumes: `ChapterItem.hovered`, `ChapterItem.activated` (Task 4); `ChapterSelectScreen._list.setCurrentRow(int)` and `ChapterSelectScreen._on_item_activated(QListWidgetItem)` (both pre-existing, unchanged).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_ui/test_screens.py`, near `test_chapter_screen_play_signal`:

```python
def test_chapter_screen_card_hover_moves_current_row(qtbot):
    from sixpack.ui.screens.chapter_select import ChapterSelectScreen
    screen = ChapterSelectScreen()
    qtbot.addWidget(screen)
    screen.load(_make_box_set_book(), _make_chapters(), None)

    assert screen._list.currentRow() == 0
    widget = screen._list.itemWidget(screen._list.item(1))
    widget.hovered.emit()

    assert screen._list.currentRow() == 1


def test_chapter_screen_card_click_emits_play_signal(qtbot):
    from sixpack.ui.screens.chapter_select import ChapterSelectScreen
    screen = ChapterSelectScreen()
    qtbot.addWidget(screen)
    book = _make_box_set_book()
    screen.load(book, _make_chapters(), None)

    signals = []
    screen.play_requested.connect(lambda b, t: signals.append((b, t)))
    widget = screen._list.itemWidget(screen._list.item(1))
    widget.activated.emit()

    assert signals == [(book, 1500.0)]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/ajs/RiderProjects/6pack-abs && source .venv/bin/activate && QT_QPA_PLATFORM=offscreen python -m pytest tests/test_ui/test_screens.py -k "chapter_screen_card" -v --no-cov`
Expected: FAIL — `screen._list.currentRow()` stays `0`; `signals` stays empty. Both fail because nothing connects the widget's new signals yet.

- [ ] **Step 3: Wire the signals**

In `src/sixpack/ui/screens/chapter_select.py`, the current `_populate_chapters` loop (currently lines 400-409) is:

```python
        self._list.clear()
        for i, chapter in enumerate(self._chapters):
            status = _chapter_status(chapter, current_time, is_finished)
            fraction = _chapter_fraction(chapter, current_time, status)
            ch_widget = ChapterItem(i, chapter, status, fraction)
            list_item = QListWidgetItem()
            list_item.setSizeHint(QSize(0, 68))
            list_item.setData(Qt.ItemDataRole.UserRole, chapter)
            self._list.addItem(list_item)
            self._list.setItemWidget(list_item, ch_widget)
```

Change it to:

```python
        self._list.clear()
        for i, chapter in enumerate(self._chapters):
            status = _chapter_status(chapter, current_time, is_finished)
            fraction = _chapter_fraction(chapter, current_time, status)
            ch_widget = ChapterItem(i, chapter, status, fraction)
            list_item = QListWidgetItem()
            list_item.setSizeHint(QSize(0, 68))
            list_item.setData(Qt.ItemDataRole.UserRole, chapter)
            self._list.addItem(list_item)
            self._list.setItemWidget(list_item, ch_widget)
            ch_widget.hovered.connect(lambda i=i: self._list.setCurrentRow(i))
            ch_widget.activated.connect(
                lambda li=list_item: self._on_item_activated(li)
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/ajs/RiderProjects/6pack-abs && source .venv/bin/activate && QT_QPA_PLATFORM=offscreen python -m pytest tests/test_ui/test_screens.py -k "chapter_screen" -v --no-cov`
Expected: All PASS.

- [ ] **Step 5: Run the full suite and lint, then commit**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest --no-cov -q` — expect all passing.
Run: `ruff check src tests` — expect no findings.

```bash
git add src/sixpack/ui/screens/chapter_select.py tests/test_ui/test_screens.py
git commit -m "Wire ChapterItem hover/click into ChapterSelectScreen"
```

---

## Task 6: `_SidebarItem` — hover and click signals

**Files:**
- Modify: `src/sixpack/ui/screens/browse.py:61-116` (`_SidebarItem`)
- Test: `tests/test_ui/test_browse_screen.py` (existing `_SidebarItem` section, after `test_sidebar_item_set_state_selected_not_active`)

**Interfaces:**
- Produces: `_SidebarItem.hovered` (`pyqtSignal()`), `_SidebarItem.activated` (`pyqtSignal()`).

`tests/test_ui/test_browse_screen.py` already imports `_SidebarItem` and has a `# ---- _SidebarItem ----`-style section with `test_sidebar_item_creates`/`test_sidebar_item_set_state_*` — add the new tests there, matching that file's existing style (module-level `Qt` import already present at the top of the file).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_ui/test_browse_screen.py`, right after `test_sidebar_item_set_state_selected_not_active`:

```python
def test_sidebar_item_click_emits_activated(qtbot):
    item = _SidebarItem("Audiobooks")
    qtbot.addWidget(item)
    item.show()

    activated = []
    item.activated.connect(lambda: activated.append(True))

    qtbot.mouseClick(item, Qt.MouseButton.LeftButton)

    assert activated == [True]


def test_sidebar_item_enter_emits_hovered(qtbot):
    from PyQt6.QtCore import QEvent

    item = _SidebarItem("Audiobooks")
    qtbot.addWidget(item)

    hovered = []
    item.hovered.connect(lambda: hovered.append(True))

    item.enterEvent(QEvent(QEvent.Type.Enter))

    assert hovered == [True]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/ajs/RiderProjects/6pack-abs && source .venv/bin/activate && QT_QPA_PLATFORM=offscreen python -m pytest tests/test_ui/test_browse_screen.py -k "sidebar_item_click or sidebar_item_enter" -v --no-cov`
Expected: FAIL with `AttributeError: '_SidebarItem' object has no attribute 'activated'` (and `hovered`).

- [ ] **Step 3: Add the signals and mouse handling**

In `src/sixpack/ui/screens/browse.py`, the current `_SidebarItem.__init__` (lines 61-79) is:

```python
class _SidebarItem(QWidget):
    def __init__(
        self, text: str, media_type: str = "book", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QHBoxLayout(self)
```

Change it to:

```python
class _SidebarItem(QWidget):
    hovered = pyqtSignal()
    activated = pyqtSignal()

    def __init__(
        self, text: str, media_type: str = "book", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QHBoxLayout(self)
```

Add these two methods at the end of the `_SidebarItem` class, right after `set_state` (currently ending at line 115):

```python
    def enterEvent(self, event) -> None:
        self.hovered.emit()
        super().enterEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.pos()):
            self.activated.emit()
        super().mouseReleaseEvent(event)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/ajs/RiderProjects/6pack-abs && source .venv/bin/activate && QT_QPA_PLATFORM=offscreen python -m pytest tests/test_ui/test_browse_screen.py -k "sidebar_item" -v --no-cov`
Expected: All PASS.

- [ ] **Step 5: Run the full suite and lint, then commit**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest --no-cov -q` — expect all passing.
Run: `ruff check src tests` — expect no findings.

```bash
git add src/sixpack/ui/screens/browse.py tests/test_ui/test_browse_screen.py
git commit -m "Add hover/click signals to _SidebarItem"
```

---

## Task 7: `BrowseScreen` — extract `_activate_sidebar_item` and wire sidebar mouse signals

**Files:**
- Modify: `src/sixpack/ui/screens/browse.py:1026-1050` (`_handle_sidebar`), `:436-438` (`_build_sidebar`'s Exit item), `:713-734` (`_rebuild_sidebar`)
- Test: `tests/test_ui/test_browse_screen.py` (new section after the sidebar-keyboard-navigation tests, before "Exit sidebar item + confirmation")

**Interfaces:**
- Consumes: `_SidebarItem.hovered`, `_SidebarItem.activated` (Task 6).
- Produces: `BrowseScreen._activate_sidebar_item(idx: int) -> None`, `BrowseScreen._on_sidebar_item_hovered(idx: int) -> None` — both usable by later tasks and by keyboard handling, which this task rewires to call the same extracted method.

`tests/test_ui/test_browse_screen.py` already has `_lib`, `screen.load_libraries([_lib("l1", "A"), _lib("l2", "B")], "http://s", "tok")`, and confirms (in `test_sidebar_down_moves_selection`) that `_sidebar_idx` defaults to `1` (the first library) right after `load_libraries` — reuse that exact setup.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_ui/test_browse_screen.py`, right after `test_sidebar_right_no_libraries_stays_in_sidebar` (the last test in the "sidebar zone keyboard navigation" section, before "Exit sidebar item + confirmation" begins):

```python
def test_sidebar_item_hover_moves_sidebar_index(qtbot):
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "A"), _lib("l2", "B")], "http://s", "tok")
    screen.show()
    screen._zone = "rows"  # start somewhere other than sidebar

    screen._sidebar_items[2].hovered.emit()

    assert screen._zone == "sidebar"
    assert screen._sidebar_idx == 2


def test_sidebar_item_click_on_library_enters_rows(qtbot):
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "A")], "http://s", "tok")
    screen.show()

    screen._sidebar_items[1].activated.emit()

    assert screen._zone == "rows"


def test_sidebar_item_click_on_exit_shows_exit_confirm(qtbot):
    screen = BrowseScreen()
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("l1", "A")], "http://s", "tok")
    screen.show()

    screen._sidebar_items[0].activated.emit()

    assert screen._exit_overlay.isVisible()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/ajs/RiderProjects/6pack-abs && source .venv/bin/activate && QT_QPA_PLATFORM=offscreen python -m pytest tests/test_ui/test_browse_screen.py -k "sidebar_item_hover or sidebar_item_click" -v --no-cov`
Expected: FAIL — `screen._zone`/`screen._sidebar_idx` don't move (nothing connects `hovered` yet); the two `activated.emit()` tests do nothing observable (nothing connects `activated` yet).

- [ ] **Step 3: Extract `_activate_sidebar_item` and add the hover handler**

In `src/sixpack/ui/screens/browse.py`, the current `_handle_sidebar` (lines 1026-1050) is:

```python
    def _handle_sidebar(self, action: InputAction) -> None:
        n = len(self._sidebar_items)
        moved = False

        if action == InputAction.UP and self._sidebar_idx > 0:
            self._sidebar_idx -= 1
            moved = True
        elif action == InputAction.DOWN and self._sidebar_idx < n - 1:
            self._sidebar_idx += 1
            moved = True

        if moved:
            self._update_sidebar_styles()
            if self._sidebar_idx == 0:
                # Landed on Exit — nothing to load, just reflect the blank
                # hero state (_start_loading_selected_library() is what
                # normally reflects a real library, but it never fires here).
                self._reflect_current()
            else:
                self._start_loading_selected_library()
        elif action in (InputAction.RIGHT, InputAction.SELECT):
            if self._sidebar_idx == 0:
                self._show_exit_confirm()
            elif self._libraries:
                self._enter_rows()
```

Change the final `elif` branch to call a new extracted method, and add that method plus the hover handler right after `_handle_sidebar`:

```python
    def _handle_sidebar(self, action: InputAction) -> None:
        n = len(self._sidebar_items)
        moved = False

        if action == InputAction.UP and self._sidebar_idx > 0:
            self._sidebar_idx -= 1
            moved = True
        elif action == InputAction.DOWN and self._sidebar_idx < n - 1:
            self._sidebar_idx += 1
            moved = True

        if moved:
            self._update_sidebar_styles()
            if self._sidebar_idx == 0:
                # Landed on Exit — nothing to load, just reflect the blank
                # hero state (_start_loading_selected_library() is what
                # normally reflects a real library, but it never fires here).
                self._reflect_current()
            else:
                self._start_loading_selected_library()
        elif action in (InputAction.RIGHT, InputAction.SELECT):
            self._activate_sidebar_item(self._sidebar_idx)

    def _activate_sidebar_item(self, idx: int) -> None:
        if idx == 0:
            self._show_exit_confirm()
        elif self._libraries:
            self._enter_rows()

    def _on_sidebar_item_hovered(self, idx: int) -> None:
        if self._zone != "sidebar":
            if self._zone == "rows":
                self._row_widgets[self._focused_row].unfocus()
            self._zone = "sidebar"
            self._update_row_styles()
        self._sidebar_idx = idx
        self._update_sidebar_styles()
        if idx == 0:
            self._reflect_current()
        else:
            self._start_loading_selected_library()
```

Note `_activate_sidebar_item` now takes the index as a parameter instead of always reading `self._sidebar_idx` — so a mouse click (which knows exactly which item was clicked, independent of whatever `_sidebar_idx` currently is) can pass it directly. The call site inside `_handle_sidebar` passes `self._sidebar_idx` to preserve today's exact keyboard behavior.

- [ ] **Step 4: Wire hover/click for each sidebar item**

In `src/sixpack/ui/screens/browse.py`, find where `self._exit_item` is constructed (in `_build_sidebar`, currently):

```python
        self._exit_item = _SidebarItem("Exit", media_type="exit")
        self._sidebar_items.append(self._exit_item)
        self._sidebar_items_layout.addWidget(self._exit_item)
```

Change it to:

```python
        self._exit_item = _SidebarItem("Exit", media_type="exit")
        self._exit_item.hovered.connect(lambda: self._on_sidebar_item_hovered(0))
        self._exit_item.activated.connect(lambda: self._activate_sidebar_item(0))
        self._sidebar_items.append(self._exit_item)
        self._sidebar_items_layout.addWidget(self._exit_item)
```

Now find the current `_rebuild_sidebar` (lines 713-734):

```python
    def _rebuild_sidebar(self) -> None:
        # Index 0 (Exit) is permanent — only library-derived items get
        # torn down and rebuilt here.
        for w in self._sidebar_items[1:]:
            w.deleteLater()
        self._sidebar_items = [self._exit_item]
        # Drop any leftover layout items (e.g. the addStretch() below, or
        # entries left behind by the widgets deleteLater()'d above) so a
        # second load_libraries() call doesn't accumulate stray stretches.
        while self._sidebar_items_layout.count():
            self._sidebar_items_layout.takeAt(0)
        self._sidebar_items_layout.addWidget(self._exit_item)
        self._sidebar_items_layout.addWidget(self._sidebar_divider)
        for lib in self._libraries:
            item = _SidebarItem(lib.name, media_type=getattr(lib, "media_type", "book"))
            self._sidebar_items.append(item)
            self._sidebar_items_layout.addWidget(item)
        # Without this, items expand to fill the column's remaining vertical
        # space — which, combined with the `border-left: 3px solid {bar}`
        # accent styling in _SidebarItem.set_state(), makes the accent bar
        # stretch across the whole column instead of staying item-sized.
        self._sidebar_items_layout.addStretch()
```

Change the per-library loop to wire each new item's signals, capturing its final index in `self._sidebar_items` (library items start at index 1, since Exit occupies index 0):

```python
    def _rebuild_sidebar(self) -> None:
        # Index 0 (Exit) is permanent — only library-derived items get
        # torn down and rebuilt here.
        for w in self._sidebar_items[1:]:
            w.deleteLater()
        self._sidebar_items = [self._exit_item]
        # Drop any leftover layout items (e.g. the addStretch() below, or
        # entries left behind by the widgets deleteLater()'d above) so a
        # second load_libraries() call doesn't accumulate stray stretches.
        while self._sidebar_items_layout.count():
            self._sidebar_items_layout.takeAt(0)
        self._sidebar_items_layout.addWidget(self._exit_item)
        self._sidebar_items_layout.addWidget(self._sidebar_divider)
        for lib in self._libraries:
            item = _SidebarItem(lib.name, media_type=getattr(lib, "media_type", "book"))
            idx = len(self._sidebar_items)
            item.hovered.connect(lambda i=idx: self._on_sidebar_item_hovered(i))
            item.activated.connect(lambda i=idx: self._activate_sidebar_item(i))
            self._sidebar_items.append(item)
            self._sidebar_items_layout.addWidget(item)
        # Without this, items expand to fill the column's remaining vertical
        # space — which, combined with the `border-left: 3px solid {bar}`
        # accent styling in _SidebarItem.set_state(), makes the accent bar
        # stretch across the whole column instead of staying item-sized.
        self._sidebar_items_layout.addStretch()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/ajs/RiderProjects/6pack-abs && source .venv/bin/activate && QT_QPA_PLATFORM=offscreen python -m pytest tests/test_ui/test_browse_screen.py -k "sidebar" -v --no-cov`
Expected: All PASS.

- [ ] **Step 6: Run the full suite and lint, then commit**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest --no-cov -q` — expect all passing.
Run: `ruff check src tests` — expect no findings.

```bash
git add src/sixpack/ui/screens/browse.py tests/test_ui/test_browse_screen.py
git commit -m "Wire sidebar item hover/click in BrowseScreen"
```

---

## Task 8: `_RowWidget` — re-emit card mouse signals, "See all" hover/click

**Files:**
- Modify: `src/sixpack/ui/screens/browse.py:8` (import), `:125-250` (`_RowWidget`)
- Test: `tests/test_ui/test_browse_screen.py` (existing `_RowWidget` section, after `test_row_widget_set_row_focused`)

**Interfaces:**
- Consumes: `MediaCard.hovered`, `MediaCard.activated`, `MediaCard.long_pressed` (Tasks 1-2).
- Produces: `_RowWidget.card_hovered(int)`, `_RowWidget.card_activated(int)`, `_RowWidget.card_long_pressed(int)`, `_RowWidget.see_all_hovered()`, `_RowWidget.see_all_activated()` — all `pyqtSignal`s, consumed by Task 9.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_ui/test_browse_screen.py`, right after `test_row_widget_set_row_focused`:

```python
def test_row_widget_card_hover_reemits_with_index(qtbot):
    from sixpack.ui.widgets.media_card import MediaCard
    row = _RowWidget("Continue Listening")
    qtbot.addWidget(row)
    row.add_card(MediaCard(title="A"))
    row.add_card(MediaCard(title="B"))

    hovered = []
    row.card_hovered.connect(lambda idx: hovered.append(idx))

    row._cards[1].hovered.emit()

    assert hovered == [1]


def test_row_widget_card_activated_reemits_with_index(qtbot):
    from sixpack.ui.widgets.media_card import MediaCard
    row = _RowWidget("Continue Listening")
    qtbot.addWidget(row)
    row.add_card(MediaCard(title="A"))

    activated = []
    row.card_activated.connect(lambda idx: activated.append(idx))

    row._cards[0].activated.emit()

    assert activated == [0]


def test_row_widget_card_long_pressed_reemits_with_index(qtbot):
    from sixpack.ui.widgets.media_card import MediaCard
    row = _RowWidget("Continue Listening")
    qtbot.addWidget(row)
    row.add_card(MediaCard(title="A"))

    long_pressed = []
    row.card_long_pressed.connect(lambda idx: long_pressed.append(idx))

    row._cards[0].long_pressed.emit()

    assert long_pressed == [0]


def test_row_widget_see_all_hover_and_click(qtbot):
    from PyQt6.QtCore import QEvent, QPoint
    from PyQt6.QtGui import QMouseEvent

    row = _RowWidget("Continue Listening")
    qtbot.addWidget(row)
    row.show()

    hovered = []
    activated = []
    row.see_all_hovered.connect(lambda: hovered.append(True))
    row.see_all_activated.connect(lambda: activated.append(True))

    row.eventFilter(row._see_all, QEvent(QEvent.Type.Enter))
    assert hovered == [True]

    release = QMouseEvent(
        QEvent.Type.MouseButtonRelease, QPoint(1, 1), Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    row.eventFilter(row._see_all, release)
    assert activated == [True]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/ajs/RiderProjects/6pack-abs && source .venv/bin/activate && QT_QPA_PLATFORM=offscreen python -m pytest tests/test_ui/test_browse_screen.py -k "row_widget_card or row_widget_see_all" -v --no-cov`
Expected: FAIL — `AttributeError: '_RowWidget' object has no attribute 'card_hovered'` (and similarly for the others).

- [ ] **Step 3: Add re-emission signals to `_RowWidget`**

In `src/sixpack/ui/screens/browse.py`, update the top-of-file import (currently line 8):

```python
from PyQt6.QtCore import QElapsedTimer, QRect, Qt, QTimer, pyqtSignal
```

to:

```python
from PyQt6.QtCore import QElapsedTimer, QEvent, QRect, Qt, QTimer, pyqtSignal
```

Find the current `_RowWidget.__init__` (starts at line 133):

```python
class _RowWidget(QWidget):
    """
    Titled horizontal strip with three body states:
      loading  — shows "Loading…" while content is being fetched
      empty    — shows "Nothing here" when fetch returned no items
      cards    — shows the horizontal scroll of MediaCards
    """

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cards: list[MediaCard] = []
```

Change it to:

```python
class _RowWidget(QWidget):
    """
    Titled horizontal strip with three body states:
      loading  — shows "Loading…" while content is being fetched
      empty    — shows "Nothing here" when fetch returned no items
      cards    — shows the horizontal scroll of MediaCards
    """

    card_hovered = pyqtSignal(int)
    card_activated = pyqtSignal(int)
    card_long_pressed = pyqtSignal(int)
    see_all_hovered = pyqtSignal()
    see_all_activated = pyqtSignal()

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cards: list[MediaCard] = []
```

Find the current `add_card` (lines 201-204):

```python
    def add_card(self, card: MediaCard) -> None:
        card.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._cards.append(card)
        self._strip_layout.insertWidget(self._strip_layout.count() - 1, card)
```

Change it to:

```python
    def add_card(self, card: MediaCard) -> None:
        card.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        idx = len(self._cards)
        card.hovered.connect(lambda i=idx: self.card_hovered.emit(i))
        card.activated.connect(lambda i=idx: self.card_activated.emit(i))
        card.long_pressed.connect(lambda i=idx: self.card_long_pressed.emit(i))
        self._cards.append(card)
        self._strip_layout.insertWidget(self._strip_layout.count() - 1, card)
```

Now find where `self._see_all` is constructed (currently around line 165):

```python
        self._see_all = QLabel("See all →")
        self._see_all.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: {theme.FONT_META}pt;"
        )
        tb_layout.addWidget(self._see_all)
```

Change it to:

```python
        self._see_all = QLabel("See all →")
        self._see_all.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: {theme.FONT_META}pt;"
        )
        self._see_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self._see_all.installEventFilter(self)
        tb_layout.addWidget(self._see_all)
```

Add an `eventFilter` override to `_RowWidget`, right after `__init__` (before `clear`, which is the next method):

```python
    def eventFilter(self, obj, event) -> bool:
        if obj is self._see_all:
            if event.type() == QEvent.Type.Enter:
                self.see_all_hovered.emit()
            elif event.type() == QEvent.Type.MouseButtonRelease:
                self.see_all_activated.emit()
        return super().eventFilter(obj, event)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/ajs/RiderProjects/6pack-abs && source .venv/bin/activate && QT_QPA_PLATFORM=offscreen python -m pytest tests/test_ui/test_browse_screen.py -k "row_widget" -v --no-cov`
Expected: All PASS.

- [ ] **Step 5: Run the full suite and lint, then commit**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest --no-cov -q` — expect all passing.
Run: `ruff check src tests` — expect no findings.

```bash
git add src/sixpack/ui/screens/browse.py tests/test_ui/test_browse_screen.py
git commit -m "Re-emit card and See-all mouse signals from _RowWidget"
```

---

## Task 9: `BrowseScreen` — wire row-card and "See all" mouse signals

**Files:**
- Modify: `src/sixpack/ui/screens/browse.py:543-548` (row construction loop)
- Test: `tests/test_ui/test_browse_screen.py` (new section after the "item activation signals in rows zone" tests)

**Interfaces:**
- Consumes: `_RowWidget.card_hovered`, `card_activated`, `card_long_pressed`, `see_all_hovered`, `see_all_activated` (Task 8); `BrowseScreen._activate_row_item(row_idx, item_idx)`, `_set_see_all_focused(bool)`, `_trigger_see_all()`, `_on_select_long_press()` (all pre-existing, unchanged).
- Produces: `BrowseScreen._on_row_card_hovered(row_idx: int, item_idx: int) -> None`, `BrowseScreen._on_see_all_hovered(row_idx: int) -> None`.

Reuse the existing `_make_screen_with_items(qtbot)` helper already defined in `tests/test_ui/test_browse_screen.py` (it builds a `BrowseScreen` with all four rows populated — `CONTINUE_LISTENING` at row 0 with items `i1`/`i2`, `RECENTLY_ADDED` at row 1 with `i3`, `SERIES` at row 2 with `s1`, `PLAYLISTS` at row 3 with `p1` — and leaves `_zone == "rows"`, `_focused_row == 0`).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_ui/test_browse_screen.py`, right after `test_rows_select_out_of_bounds_does_nothing` (the last test in the "item activation signals in rows zone" section, before "BrowseScreen — grid zone" begins):

```python
def test_row_card_hover_syncs_zone_row_and_item(qtbot):
    screen = _make_screen_with_items(qtbot)
    screen._zone = "sidebar"  # start somewhere other than this row

    screen._row_widgets[1].card_hovered.emit(0)

    assert screen._zone == "rows"
    assert screen._focused_row == 1
    assert screen._row_item_idxs[1] == 0


def test_row_card_click_activates_item(qtbot):
    screen = _make_screen_with_items(qtbot)

    with qtbot.waitSignal(screen.book_selected, timeout=500) as blocker:
        screen._row_widgets[0].card_activated.emit(1)

    assert blocker.args[0].id == "i2"


def test_row_see_all_hover_focuses_see_all(qtbot):
    screen = _make_screen_with_items(qtbot)
    screen._zone = "sidebar"

    screen._row_widgets[0].see_all_hovered.emit()

    assert screen._zone == "rows"
    assert screen._focused_row == 0
    assert screen._see_all_focused is True


def test_row_see_all_click_triggers_see_all(qtbot):
    screen = _make_screen_with_items(qtbot)

    with qtbot.waitSignal(screen.see_all_requested, timeout=500) as blocker:
        screen._row_widgets[0].see_all_activated.emit()

    assert blocker.args[0] == RowType.CONTINUE_LISTENING
    assert screen._zone == "grid"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/ajs/RiderProjects/6pack-abs && source .venv/bin/activate && QT_QPA_PLATFORM=offscreen python -m pytest tests/test_ui/test_browse_screen.py -k "row_card or row_see_all" -v --no-cov`
Expected: FAIL — none of these signals do anything yet (nothing connects them in `BrowseScreen`).

- [ ] **Step 3: Wire the signals and add the two new handlers**

In `src/sixpack/ui/screens/browse.py`, the current row-construction loop (lines 543-548) is:

```python
        self._row_widgets: list[_RowWidget] = []
        for rt in self._row_types:
            rw = _RowWidget(rt.value)
            rw.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self._row_widgets.append(rw)
            rows_layout.addWidget(rw)
```

Change it to:

```python
        self._row_widgets: list[_RowWidget] = []
        for row_idx, rt in enumerate(self._row_types):
            rw = _RowWidget(rt.value)
            rw.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            rw.card_hovered.connect(
                lambda item_idx, ridx=row_idx: self._on_row_card_hovered(ridx, item_idx)
            )
            rw.card_activated.connect(
                lambda item_idx, ridx=row_idx: self._activate_row_item(ridx, item_idx)
            )
            rw.card_long_pressed.connect(lambda _item_idx: self._on_select_long_press())
            rw.see_all_hovered.connect(lambda ridx=row_idx: self._on_see_all_hovered(ridx))
            rw.see_all_activated.connect(self._trigger_see_all)
            self._row_widgets.append(rw)
            rows_layout.addWidget(rw)
```

`card_long_pressed` ignores its own index argument and calls `_on_select_long_press()` directly — that method already reads "whichever item is currently focused" via `_current_focused_item()`, and `_on_row_card_hovered` below guarantees focus is already synced to the hovered card before a hold could complete, so no index needs to travel through this path.

`see_all_activated` connects straight to the bound method `self._trigger_see_all` (no lambda needed) since that method takes no arguments and already operates on `self._focused_row` — but a mouse click on "See all" could arrive without that row ever having been the keyboard-focused one, so `_on_see_all_hovered` must run first (which real mouse usage always does, since a click is preceded by a hover).

Add these two new methods right after `_on_sidebar_item_hovered` (added in Task 7):

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

    def _on_see_all_hovered(self, row_idx: int) -> None:
        if self._zone != "rows" or self._focused_row != row_idx:
            if self._zone == "rows":
                self._row_widgets[self._focused_row].unfocus()
            self._zone = "rows"
            self._focused_row = row_idx
            self._update_row_styles()
        self._set_see_all_focused(True)
        self._reflect_current()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/ajs/RiderProjects/6pack-abs && source .venv/bin/activate && QT_QPA_PLATFORM=offscreen python -m pytest tests/test_ui/test_browse_screen.py -k "row_card or row_see_all" -v --no-cov`
Expected: All PASS.

- [ ] **Step 5: Run the full suite and lint, then commit**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest --no-cov -q` — expect all passing.
Run: `ruff check src tests` — expect no findings.

```bash
git add src/sixpack/ui/screens/browse.py tests/test_ui/test_browse_screen.py
git commit -m "Wire row-card and See-all mouse signals in BrowseScreen"
```

---

## Task 10: `BrowseScreen` — wire grid-card mouse signals

**Files:**
- Modify: `src/sixpack/ui/screens/browse.py:736-753` (new `_add_grid_card` helper, next to `_make_card`), `:1261-1276` (`populate_grid`), `:1287-1312` (`_enter_grid`)
- Test: `tests/test_ui/test_browse_screen.py` (existing "BrowseScreen — grid zone" section)

**Interfaces:**
- Consumes: `MediaCard.hovered`, `activated`, `long_pressed` (Tasks 1-2); `BrowseScreen._set_grid_focus(idx)`, `_activate_grid_item(idx)`, `_on_select_long_press()` (all pre-existing, unchanged).
- Produces: `BrowseScreen._add_grid_card(item, idx) -> None` — a small shared helper factoring out the duplicated card-creation-plus-wiring code from `populate_grid` and `_enter_grid`.

Reuse the existing `_make_screen_in_grid(qtbot, row_idx=2)` helper already defined in `tests/test_ui/test_browse_screen.py` (it calls `_make_screen_with_items(qtbot)` then `screen._enter_grid(row_idx)`). Row 0 is `CONTINUE_LISTENING` with items `i1`/`i2` (see Task 9's description of `_make_screen_with_items`) — `_make_screen_in_grid(qtbot, row_idx=0)` puts `screen._grid_items == [i1, i2]`, matching the existing keyboard test `test_long_press_in_grid_zone_requests_finish_progress`, which this task's new hold test mirrors exactly (same helper, same row, same `finish_progress_requested` signal — just triggered by `long_pressed.emit()` instead of a keyboard hold).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_ui/test_browse_screen.py`, right after `test_grid_page_top_margin_clears_the_hero` (inside the "BrowseScreen — grid zone" section):

```python
def test_grid_card_hover_moves_grid_focus(qtbot):
    screen = _make_screen_in_grid(qtbot, row_idx=2)  # SERIES row -> 1 item

    screen._grid_cards[0].hovered.emit()

    assert screen._grid_focus_idx == 0


def test_grid_card_click_activates_item(qtbot):
    screen = _make_screen_in_grid(qtbot, row_idx=0)  # CONTINUE_LISTENING -> i1, i2

    with qtbot.waitSignal(screen.book_selected, timeout=500) as blocker:
        screen._grid_cards[1].activated.emit()

    assert blocker.args[0].id == "i2"


def test_grid_card_long_press_requests_finish_progress(qtbot):
    screen = _make_screen_in_grid(qtbot, row_idx=0)  # CONTINUE_LISTENING -> i1, i2
    requested = []
    screen.finish_progress_requested.connect(requested.append)

    screen._grid_cards[0].long_pressed.emit()

    assert len(requested) == 1
    assert requested[0].id == "i1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/ajs/RiderProjects/6pack-abs && source .venv/bin/activate && QT_QPA_PLATFORM=offscreen python -m pytest tests/test_ui/test_browse_screen.py -k "grid_card" -v --no-cov`
Expected: FAIL — none of the emitted signals do anything yet.

- [ ] **Step 3: Add `_add_grid_card` and use it in both call sites**

In `src/sixpack/ui/screens/browse.py`, the current `populate_grid` (lines 1261-1276) is:

```python
    def populate_grid(self, items: list[Any]) -> None:
        """Fill the grid with the full dataset returned by app.py."""
        self._grid_items = items
        for card in self._grid_cards:
            self._grid_layout.removeWidget(card)
            card.deleteLater()
        self._grid_cards.clear()
        for i, item in enumerate(items):
            card = self._make_card(item)
            card.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            row, col = divmod(i, _GRID_COLS)
            self._grid_layout.addWidget(card, row, col)
            self._grid_cards.append(card)
        self._grid_body_stack.setCurrentIndex(1)  # content page
        if self._grid_cards:
            self._set_grid_focus(0)
```

and the current `_enter_grid` (lines 1287-1312) contains this identical inner loop:

```python
        for i, item in enumerate(items):
            card = self._make_card(item)
            card.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            row, col = divmod(i, _GRID_COLS)
            self._grid_layout.addWidget(card, row, col)
            self._grid_cards.append(card)
```

Add a new helper method right after `_make_card` (currently ending at line 753):

```python
    def _add_grid_card(self, item: Any, idx: int) -> None:
        card = self._make_card(item)
        card.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        card.hovered.connect(lambda i=idx: self._set_grid_focus(i))
        card.activated.connect(lambda i=idx: self._activate_grid_item(i))
        card.long_pressed.connect(self._on_select_long_press)
        row, col = divmod(idx, _GRID_COLS)
        self._grid_layout.addWidget(card, row, col)
        self._grid_cards.append(card)
```

Then replace the loop body in `populate_grid`:

```python
    def populate_grid(self, items: list[Any]) -> None:
        """Fill the grid with the full dataset returned by app.py."""
        self._grid_items = items
        for card in self._grid_cards:
            self._grid_layout.removeWidget(card)
            card.deleteLater()
        self._grid_cards.clear()
        for i, item in enumerate(items):
            self._add_grid_card(item, i)
        self._grid_body_stack.setCurrentIndex(1)  # content page
        if self._grid_cards:
            self._set_grid_focus(0)
```

And replace the equivalent loop inside `_enter_grid`:

```python
        for i, item in enumerate(items):
            self._add_grid_card(item, i)
```

(Leave the rest of `_enter_grid` — everything before and after that loop — unchanged.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/ajs/RiderProjects/6pack-abs && source .venv/bin/activate && QT_QPA_PLATFORM=offscreen python -m pytest tests/test_ui/test_browse_screen.py -k "grid_card" -v --no-cov`
Expected: All PASS.

- [ ] **Step 5: Run the full suite and lint, then commit**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest --no-cov -q` — expect all passing (this is the last task — this run should cover the whole feature end to end).
Run: `ruff check src tests` — expect no findings.

```bash
git add src/sixpack/ui/screens/browse.py tests/test_ui/test_browse_screen.py
git commit -m "Wire grid-card mouse signals in BrowseScreen"
```


---

## Final verification

- [ ] Run the complete suite once more from a clean state: `cd /Users/ajs/RiderProjects/6pack-abs && source .venv/bin/activate && QT_QPA_PLATFORM=offscreen python -m pytest --no-cov -q` — expect every test passing, no new warnings.
- [ ] Run `ruff check src tests` — expect no findings.
- [ ] Manually smoke-test with a real mouse: relaunch the app (`pkill -9 -f "sixpack.main"`, resync the venv per the project's own "resync venv before relaunch" convention, then `python -m sixpack.main`) and confirm: hovering a Home-row card, a "See all" grid card, a sidebar library, and a chapter-list row moves the highlight; clicking each activates it; click-and-hold on a Continue-Listening/Recently-Added card or a Series/Playlist/Podcast detail card opens the mark-finished popup; arrow-key/gamepad navigation still works unchanged throughout.
