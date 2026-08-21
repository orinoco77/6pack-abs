# Phase B: Unified Detail Screens Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the near-duplicate, pre-redesign `SeriesDetailScreen`/`PlaylistDetailScreen` (flat `QListWidget`s) with one shared `DetailGridScreen` base — `Backdrop` + hero + a wrapping `FocusGrid` of `MediaCard`s — and give `ChapterSelectScreen` a matching cinematic list redesign. Remove "Play All" and the dead code its removal leaves behind.

**Architecture:** A new reusable `DetailGridScreen` base widget (Backdrop, static-title/dynamic-subtitle hero, `FocusGrid`-backed card grid, generic load/progress-refresh/focus-by-key API) that `SeriesDetailScreen` and `PlaylistDetailScreen` become thin subclasses of, preserving their existing public signals/method signatures so `app.py`'s wiring needs minimal changes. `ChapterSelectScreen` gets its own cinematic list redesign (same shell, list rows instead of cards, since chapters share one cover). `FocusGrid` gains the transparent-background treatment it needs now that something is finally using it behind a `Backdrop` — this exact bug (opaque `QScrollArea` hiding the backdrop) already happened once in the Home/Browse redesign; see `docs/qt-graphics-effect-crash.md`'s sibling lesson and the fix pattern in `browse.py`.

**Tech Stack:** Python 3.12, PyQt6, pytest + pytest-qt (headless via `QT_QPA_PLATFORM=offscreen`).

**Spec:** `docs/superpowers/specs/2026-08-21-app-wide-cinematic-redesign-design.md` (Phase B section)

## Global Constraints

- Python ≥ 3.10 (dev/target uses 3.12). Line length 100 (ruff). `select = ["E","F","I","UP"]`.
- Coverage gate: `--cov-fail-under=80` must keep passing.
- All Qt tests run under `QT_QPA_PLATFORM=offscreen`.
- **No `QGraphicsEffect` subclass anywhere, ever** — see `docs/qt-graphics-effect-crash.md`. Every new visual effect (finished badge, chapter-row focus feedback) is plain `QPainter`/stylesheet work.
- Every stacked container between a `Backdrop` and the screen surface needs explicit `background: transparent` styling — the global `QWidget`/`QScrollArea` stylesheet rules in `theme.py` are opaque by default (`background-color: {BG}`). Verify by construction, not by assumption — this exact bug already shipped once (see `docs/superpowers/plans/2026-08-20-home-cinematic-redesign.md`'s Task 6 fix history) and reappears anywhere a new scroll container gets added.
- `SeriesDetailScreen.load(series, progress, server_url, token)` and `PlaylistDetailScreen.load(playlist, progress, server_url, token)` — these exact signatures, taking the domain object directly — must not change; `app.py` calls them as-is (`self._detail_screen.load(series, progress, self._server_url, self._token)` etc.) and this plan does not touch `app.py`'s call sites for `load`/`show_loading`/`update_progress`.
- `_on_next_item`/`_on_prev_item`'s current auto-play behavior in `app.py` is **intentionally left unchanged in this phase** — Phase C changes the player-side signal that drives it. This phase only adds the `focus_item_by_key` capability Phase C will call; wiring it in now would leave the app in a half-finished state (auto-play still firing immediately after the new focus call, with no visible effect). Do not attempt to fix this in Phase B.
- Commit after each task. Branch: `feature/app-wide-cinematic-redesign`.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `src/sixpack/ui/widgets/focus_grid.py` (edit) | Add transparent-background treatment to its internal `QScrollArea`/container |
| `src/sixpack/ui/widgets/media_card.py` (edit) | Add `set_finished(bool)` — paint-level checkmark badge |
| `src/sixpack/ui/screens/detail_grid.py` (new) | `DetailGridScreen` base: Backdrop + hero + FocusGrid shell |
| `src/sixpack/ui/screens/series_detail.py` (rewrite) | Thin `DetailGridScreen` subclass for series episodes |
| `src/sixpack/ui/screens/playlist_detail.py` (rewrite) | Thin `DetailGridScreen` subclass for playlist items |
| `src/sixpack/ui/screens/chapter_select.py` (rewrite) | Cinematic list redesign (same shell, list rows not cards) |
| `src/sixpack/ui/app.py` (edit) | Remove dead Play-All wiring; nothing else in this phase |
| `tests/test_ui/test_widgets.py` (edit) | `FocusGrid` transparency test, `MediaCard.set_finished` tests |
| `tests/test_ui/test_detail_grid.py` (new) | `DetailGridScreen` base behavior tests |
| `tests/test_ui/test_screens.py` (edit) | Update `SeriesDetailScreen`/`ChapterSelectScreen` tests for the new implementation |
| `tests/test_ui/test_playlist_screens.py` (edit) | Update `PlaylistDetailScreen` tests for the new implementation |

---

## Task 1: FocusGrid transparent-background fix

**Files:**
- Modify: `src/sixpack/ui/widgets/focus_grid.py`
- Test: `tests/test_ui/test_widgets.py`

**Interfaces:** No API change — `FocusGrid.__init__(columns, h_spacing, v_spacing, parent)`, `add_item`, `clear`, `focus_item`, `set_focus_first`, `item_count` all keep their exact existing signatures. This task only changes internal styling.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_ui/test_widgets.py` (near the existing FocusGrid tests section):

```python
def test_focus_grid_scroll_area_is_transparent(qtbot):
    """Regression guard: FocusGrid's internal QScrollArea/container must be
    explicitly transparent, or a Backdrop placed behind it (DetailGridScreen)
    gets fully occluded — the exact bug that shipped once already in the
    Home/Browse redesign (theme.py's global QWidget/QScrollArea rules are
    opaque by default)."""
    grid = FocusGrid(columns=2)
    qtbot.addWidget(grid)
    assert "transparent" in grid._scroll.styleSheet()
    assert "transparent" in grid._scroll.viewport().styleSheet()
    assert "transparent" in grid._container.styleSheet()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_widgets.py -v -k test_focus_grid_scroll_area_is_transparent`
Expected: FAIL — `assert "transparent" in ''` (styleSheet is empty by default).

- [ ] **Step 3: Add the transparent styling**

In `src/sixpack/ui/widgets/focus_grid.py`, in `__init__`, immediately after the `scroll = QScrollArea()` block's existing `setFocusPolicy` call and before `self._container = QWidget()`, and after `self._container`/`self._grid` are built, add:

```python
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.viewport().setStyleSheet("background: transparent;")
```

and immediately after `self._container = QWidget()`:

```python
        self._container.setStyleSheet("background: transparent;")
```

(Place each line right after the widget it styles is constructed, matching the existing code's construction order — don't reorder existing lines, just insert these three.)

- [ ] **Step 4: Run test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_widgets.py -v -k test_focus_grid_scroll_area_is_transparent`
Expected: PASS.

- [ ] **Step 5: Run the full FocusGrid test section to confirm no regression**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_widgets.py -v -k FocusGrid or focus_grid`
Expected: all PASS (this is a pure styling addition, existing navigation/add/clear tests are unaffected).

- [ ] **Step 6: Commit**

```bash
git add src/sixpack/ui/widgets/focus_grid.py tests/test_ui/test_widgets.py
git commit -m "Make FocusGrid's internal scroll area transparent for Backdrop use"
```

---

## Task 2: MediaCard finished-state badge

**Files:**
- Modify: `src/sixpack/ui/widgets/media_card.py`
- Test: `tests/test_ui/test_widgets.py`

**Interfaces:**
- Produces: `MediaCard.set_finished(finished: bool) -> None` — paint-level checkmark badge shown in a corner of the card art when `finished=True`. Consistent with `_Scrim`/`_Glow`'s existing paint-level pattern (see `docs/qt-graphics-effect-crash.md`) — **no `QGraphicsEffect`**.
- Consumes: `theme.SUCCESS` (`"#4caf50"`, already defined) for the badge color.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_ui/test_widgets.py` (MediaCard section):

```python
def test_media_card_set_finished_shows_badge(qtbot):
    card = MediaCard(title="Test")
    qtbot.addWidget(card)
    assert card._finished is False
    card.set_finished(True)
    assert card._finished is True
    card.set_finished(False)
    assert card._finished is False


def test_media_card_finished_badge_paints_without_crash(qtbot):
    """Real paint, not just state — matches this codebase's pattern of
    verifying paint-level effects actually render (see task-glow-fix-report
    history in git log for why state-only assertions weren't enough once
    before)."""
    card = MediaCard(title="Test")
    qtbot.addWidget(card)
    card.set_finished(True)
    card.show()
    qtbot.waitExposed(card)
    pix = card.grab()
    assert not pix.isNull()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_widgets.py -v -k finished`
Expected: FAIL — `AttributeError: 'MediaCard' object has no attribute '_finished'` / no `set_finished` method.

- [ ] **Step 3: Implement**

In `src/sixpack/ui/widgets/media_card.py`, add a `_FinishedBadge` class following the exact same shape as `_Scrim`/`_Glow` (both already in this file — read them first for the pattern: `WA_TransparentForMouseEvents`, `WA_NoSystemBackground`, `NoFocus`, a `paintEvent` guarded by `try/except RuntimeError` for teardown races):

```python
class _FinishedBadge(QWidget):
    """A small checkmark badge shown in the top-right corner of a card's
    art when the item is finished. Paint-level, not a QGraphicsEffect —
    see docs/qt-graphics-effect-crash.md.
    """

    _SIZE = 28
    _MARGIN = 6

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedSize(self._SIZE, self._SIZE)

    def paintEvent(self, event) -> None:  # noqa: ARG002
        try:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setBrush(QColor(theme.SUCCESS))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(0, 0, self._SIZE, self._SIZE)
            painter.setPen(QColor(theme.TEXT_PRIMARY))
            font = painter.font()
            font.setPointSize(14)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "✓")
            painter.end()
        except RuntimeError:
            pass
```

In `MediaCard.__init__`, after `self._scrim`/`self._glow` are constructed (find that block — search for `self._scrim = _Scrim(self._body)`), add:

```python
        self._finished = False
        self._finished_badge = _FinishedBadge(self._body)
        self._finished_badge.move(
            self._body.width() - self._finished_badge.width() - _FinishedBadge._MARGIN,
            _FinishedBadge._MARGIN,
        )
        self._finished_badge.raise_()
        self._finished_badge.hide()
```

Add the public method (near `set_progress`):

```python
    def set_finished(self, finished: bool) -> None:
        self._finished = finished
        self._finished_badge.setVisible(finished)
```

Since `self._body`'s size is fixed at construction (`theme.CARD_WIDTH` × `theme.CARD_ART_HEIGHT`-derived, already fixed elsewhere in this file), the badge's `move()` position set once in `__init__` doesn't need to track resizes — confirm this by checking how `_scrim`/`_glow` handle (or don't handle) resizing in the existing code before assuming; if they use the `eventFilter`-based resize tracking pattern already in this file, follow the same pattern for the badge's position instead of a one-time `move()`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_widgets.py -v -k "finished or media_card"`
Expected: PASS (including all pre-existing MediaCard tests, unaffected).

- [ ] **Step 5: Run the full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` (2-3 times)
Expected: all passing, coverage ≥80%, no segfault.

- [ ] **Step 6: Commit**

```bash
git add src/sixpack/ui/widgets/media_card.py tests/test_ui/test_widgets.py
git commit -m "Add MediaCard.set_finished() paint-level checkmark badge"
```

---

## Task 3: `DetailGridScreen` base component

**Files:**
- Create: `src/sixpack/ui/screens/detail_grid.py`
- Test: `tests/test_ui/test_detail_grid.py` (new)

**Interfaces:**
- Consumes: `Backdrop` (`show_color`, `show_image`, `set_expected_key`), `FocusGrid` (`add_item`, `clear`, `focus_item`, `item_count`, `item_activated` signal), `MediaCard` (`set_cover`, `set_progress`, `set_finished`), `CoverCache` (`fetch`, `fetch_backdrop`), `dominant_color` from `sixpack.ui.cover_cache`.
- Produces (for `series_detail.py`/`playlist_detail.py` to subclass):
  - `DetailGridScreen(cover_cache: CoverCache | None = None, parent=None)`.
  - `item_activated = pyqtSignal(object)` — emits the raw domain item (a `SeriesBook` or `PlaylistItem`) when its card is activated.
  - `back_requested = pyqtSignal()`.
  - `_populate(self, title: str, items: list, progress: dict, server_url: str, token: str, loading: bool = False) -> None` — protected method subclasses' `load()`/`show_loading()` delegate to. Sets hero title (static) to `title`, builds a `MediaCard` per item via `_make_card`, focuses the resume index, reflects the focused item into hero-subtitle/backdrop.
  - `_refresh_progress(self, progress: dict) -> None` — protected method subclasses' `update_progress()` delegates to. Updates existing cards' `set_progress`/`set_finished` in place (no rebuild) and re-focuses the resume index.
  - `focus_item_by_key(self, key: str) -> None` — public; finds the item whose `_item_key(item)` matches `key` and focuses its card. No-op if not found (e.g. key belongs to an item no longer in this list).
  - Subclass contract (must override): `_item_key(self, item) -> str`, `_item_progress(self, item, progress: dict) -> tuple[float, bool]` (returns `(fraction, is_finished)`), `_item_title(self, item) -> str`, `_item_subtitle(self, item) -> str`, `_item_cover_url(self, item, server_url: str, token: str) -> str | None`, `_item_media_type(self, item) -> str` (default `"book"` if not overridden — implement as a regular method returning `"book"` in the base so subclasses only override it if they need something else).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ui/test_detail_grid.py`:

```python
"""Tests for the DetailGridScreen base (series/playlist item grid shell)."""
from __future__ import annotations

from sixpack.ui.screens.detail_grid import DetailGridScreen


class _FakeItem:
    def __init__(self, key, title, subtitle=""):
        self.key = key
        self.title_ = title
        self.subtitle_ = subtitle


class _TestScreen(DetailGridScreen):
    """Minimal concrete subclass for testing the base in isolation."""

    def _item_key(self, item):
        return item.key

    def _item_progress(self, item, progress):
        p = progress.get(item.key)
        if p is None:
            return 0.0, False
        return p.get("fraction", 0.0), p.get("finished", False)

    def _item_title(self, item):
        return item.title_

    def _item_subtitle(self, item):
        return item.subtitle_

    def _item_cover_url(self, item, server_url, token):
        return None  # no cover fetch needed for these tests


def _items():
    return [_FakeItem("a", "Item A"), _FakeItem("b", "Item B"), _FakeItem("c", "Item C")]


def test_detail_grid_populate_sets_hero_title_and_cards(qtbot):
    screen = _TestScreen()
    qtbot.addWidget(screen)
    screen._populate("My Series", _items(), {}, "http://s", "t")
    assert screen._hero_title.text() == "My Series"
    assert screen._grid.item_count == 3


def test_detail_grid_populate_focuses_resume_index(qtbot):
    screen = _TestScreen()
    qtbot.addWidget(screen)
    progress = {"a": {"fraction": 1.0, "finished": True}}
    screen._populate("My Series", _items(), progress, "http://s", "t")
    # item "a" is finished, "b" should be the resume point
    assert screen._grid._focused_index == 1


def test_detail_grid_populate_reflects_focused_item_in_hero_subtitle(qtbot):
    screen = _TestScreen()
    qtbot.addWidget(screen)
    screen._populate("My Series", _items(), {}, "http://s", "t")
    assert screen._hero_sub.text() == "Item A"


def test_detail_grid_item_activated_emits_raw_item(qtbot):
    screen = _TestScreen()
    qtbot.addWidget(screen)
    screen._populate("My Series", _items(), {}, "http://s", "t")
    with qtbot.waitSignal(screen.item_activated, timeout=1000) as blocker:
        screen._grid.item_activated.emit(1)
    assert blocker.args[0].key == "b"


def test_detail_grid_refresh_progress_updates_in_place_without_rebuild(qtbot):
    screen = _TestScreen()
    qtbot.addWidget(screen)
    screen._populate("My Series", _items(), {}, "http://s", "t")
    card_before = screen._grid._items[0]
    screen._refresh_progress({"a": {"fraction": 1.0, "finished": True}})
    assert screen._grid._items[0] is card_before  # same card instances, not rebuilt
    assert screen._grid.item_count == 3


def test_detail_grid_focus_item_by_key(qtbot):
    screen = _TestScreen()
    qtbot.addWidget(screen)
    screen._populate("My Series", _items(), {}, "http://s", "t")
    screen.focus_item_by_key("c")
    assert screen._grid._focused_index == 2


def test_detail_grid_focus_item_by_key_missing_is_noop(qtbot):
    screen = _TestScreen()
    qtbot.addWidget(screen)
    screen._populate("My Series", _items(), {}, "http://s", "t")
    screen.focus_item_by_key("does-not-exist")
    assert screen._grid._focused_index == 0  # unchanged


def test_detail_grid_back_key_emits_back_requested(qtbot):
    from PyQt6.QtCore import Qt
    screen = _TestScreen()
    qtbot.addWidget(screen)
    screen._populate("My Series", _items(), {}, "http://s", "t")
    screen.show()
    with qtbot.waitSignal(screen.back_requested, timeout=1000):
        qtbot.keyClick(screen, Qt.Key.Key_Backspace)
```

(If `InputAction.BACK` isn't bound to `Key_Backspace` in `sixpack.input.keyboard`, check `src/sixpack/input/keyboard.py` for the actual key and use that instead — every other screen's existing `test_..._back_signal` test in `tests/test_ui/test_screens.py` shows the correct key to use, copy its pattern.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_detail_grid.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sixpack.ui.screens.detail_grid'`.

- [ ] **Step 3: Implement `DetailGridScreen`**

Create `src/sixpack/ui/screens/detail_grid.py`. Model its `Backdrop`/hero construction directly on `BrowseScreen._build_ui`/`_build_hero`/`_hero_geometry`/`resizeEvent` in `src/sixpack/ui/screens/browse.py` (read that code first — reuse the exact same `theme.GRADIENT_HERO_SCRIM` pattern, `Backdrop(self)` + `.lower()`, hero as a `QWidget(self)` overlay with `WA_TransparentForMouseEvents`). Differences from Browse's hero: this hero's title is set once by `_populate` (static — the series/playlist name) and never changes on focus move; only the subtitle updates per focused item.

```python
"""Shared shell for series-episode and playlist-item grid screens.

Backdrop + a static-title/dynamic-subtitle hero + a FocusGrid of
MediaCards. Subclasses (SeriesDetailScreen, PlaylistDetailScreen) supply
how to read title/subtitle/cover/progress from their own item type;
this class owns the shell, card construction, cover fetching, and focus
reflection, all of which are otherwise near-identical between the two.
"""
from __future__ import annotations

from typing import Any

from PyQt6 import sip
from PyQt6.QtCore import QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from sixpack.ui import theme
from sixpack.ui.cover_cache import CoverCache, dominant_color
from sixpack.ui.widgets.backdrop import Backdrop
from sixpack.ui.widgets.focus_grid import FocusGrid
from sixpack.ui.widgets.media_card import MediaCard

_HERO_H = 150


class DetailGridScreen(QWidget):
    """Base shell for a Backdrop + hero + FocusGrid detail screen.

    Subclasses must override _item_key, _item_progress, _item_title,
    _item_subtitle, _item_cover_url. _item_media_type has a "book"
    default and is optional to override.
    """

    item_activated = pyqtSignal(object)
    back_requested = pyqtSignal()

    def __init__(self, cover_cache: CoverCache | None = None, parent=None) -> None:
        super().__init__(parent)
        self._cover_cache = cover_cache
        self._items: list[Any] = []
        self._progress: dict = {}
        self._server_url = ""
        self._token = ""
        self._dom_colors: dict[str, QColor] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        self._backdrop = Backdrop(self)
        self._backdrop.lower()

        self._grid = FocusGrid(columns=5)
        self._grid.item_activated.connect(self._on_item_activated)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._grid)

        self._build_hero()

    def resizeEvent(self, event) -> None:
        self._backdrop.setGeometry(self.rect())
        if hasattr(self, "_hero"):
            self._hero.setGeometry(self._hero_geometry())
        super().resizeEvent(event)

    def _build_hero(self) -> None:
        self._hero = QWidget(self)
        self._hero.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._hero.setStyleSheet(f"background: {theme.GRADIENT_HERO_SCRIM};")
        lay = QVBoxLayout(self._hero)
        lay.setContentsMargins(36, 24, 36, 8)
        lay.setSpacing(4)
        self._hero_title = QLabel("")
        self._hero_title.setStyleSheet(
            f"font-size: {theme.FONT_HUGE}pt; font-weight: bold; "
            f"color: {theme.TEXT_PRIMARY}; background: transparent;"
        )
        self._hero_sub = QLabel("")
        self._hero_sub.setStyleSheet(
            f"font-size: {theme.FONT_HEADING}pt; color: {theme.TEXT_SECONDARY}; "
            f"background: transparent;"
        )
        lay.addWidget(self._hero_title)
        lay.addWidget(self._hero_sub)
        self._hero.raise_()

    def _hero_geometry(self) -> QRect:
        return QRect(0, 0, self.width(), _HERO_H)

    # ------------------------------------------------------------------
    # Subclass contract
    # ------------------------------------------------------------------

    def _item_key(self, item: Any) -> str:
        raise NotImplementedError

    def _item_progress(self, item: Any, progress: dict) -> tuple[float, bool]:
        raise NotImplementedError

    def _item_title(self, item: Any) -> str:
        raise NotImplementedError

    def _item_subtitle(self, item: Any) -> str:
        raise NotImplementedError

    def _item_cover_url(self, item: Any, server_url: str, token: str) -> str | None:
        raise NotImplementedError

    def _item_media_type(self, item: Any) -> str:
        return "book"

    # ------------------------------------------------------------------
    # Population
    # ------------------------------------------------------------------

    def _populate(
        self,
        title: str,
        items: list[Any],
        progress: dict,
        server_url: str,
        token: str,
        loading: bool = False,  # noqa: ARG002 — reserved for a future loading indicator; unused for now
    ) -> None:
        self._items = items
        self._progress = progress
        self._server_url = server_url
        self._token = token
        self._hero_title.setText(title)

        self._grid.clear()
        for item in items:
            self._grid.add_item(self._make_card(item))

        if self._grid.item_count:
            idx = self._find_resume_index()
            self._grid.focus_item(idx)
            self._reflect_focus(items[idx])

    def _refresh_progress(self, progress: dict) -> None:
        self._progress = progress
        for item, card in zip(self._items, self._grid._items):
            fraction, finished = self._item_progress(item, progress)
            card.set_progress(fraction)
            card.set_finished(finished)
        if self._grid.item_count:
            idx = self._find_resume_index()
            self._grid.focus_item(idx)
            self._reflect_focus(self._items[idx])

    def _find_resume_index(self) -> int:
        for i, item in enumerate(self._items):
            _fraction, finished = self._item_progress(item, self._progress)
            if not finished:
                return i
        return 0

    def _make_card(self, item: Any) -> MediaCard:
        card = MediaCard(
            title=self._item_title(item),
            subtitle=self._item_subtitle(item),
            media_type=self._item_media_type(item),
        )
        fraction, finished = self._item_progress(item, self._progress)
        card.set_progress(fraction)
        card.set_finished(finished)
        cover = self._item_cover_url(item, self._server_url, self._token)
        if cover and self._cover_cache is not None:
            key = self._item_key(item)
            self._fetch_cover(card, cover, key)
        return card

    def _fetch_cover(self, card: MediaCard, cover_url: str, key: str) -> None:
        def _cb(pm):
            # See browse.py's identical guard: a card can be deleted (grid
            # rebuild) before an in-flight cover fetch resolves.
            if sip.isdeleted(card):
                return
            card.set_cover(pm)
            if key not in self._dom_colors:
                self._dom_colors[key] = dominant_color(pm)

        self._cover_cache.fetch(cover_url, self._token, _cb)

    # ------------------------------------------------------------------
    # Focus reflection (hero subtitle + backdrop)
    # ------------------------------------------------------------------

    def _on_item_activated(self, index: int) -> None:
        if 0 <= index < len(self._items):
            self.item_activated.emit(self._items[index])

    def _reflect_focus(self, item: Any) -> None:
        self._hero_sub.setText(self._item_subtitle(item) or self._item_title(item))
        if self._cover_cache is None:
            return
        cover = self._item_cover_url(item, self._server_url, self._token)
        if not cover:
            return
        key = self._item_key(item)
        color = self._dom_colors.get(key)
        self._backdrop.set_expected_key(key)
        if color is not None:
            self._backdrop.show_color(color)
        self._cover_cache.fetch_backdrop(
            cover, self._token,
            lambda pm, k=key: self._backdrop.show_image(pm, key=k),
        )

    def focus_item_by_key(self, key: str) -> None:
        for i, item in enumerate(self._items):
            if self._item_key(item) == key:
                self._grid.focus_item(i)
                self._reflect_focus(item)
                return

    # ------------------------------------------------------------------
    # Keyboard
    # ------------------------------------------------------------------

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._grid.setFocus()

    def keyPressEvent(self, event) -> None:
        from sixpack.input.keyboard import key_to_action
        from sixpack.input.actions import InputAction

        action = key_to_action(event.key())
        if action == InputAction.BACK:
            self.back_requested.emit()
        else:
            super().keyPressEvent(event)
```

Note: `_reflect_focus` doesn't fire on `FocusGrid`'s own arrow-key navigation yet — `FocusGrid.focus_item()` only handles visual card focus, it has no hook for "focus changed" the screen can observe. Add one: in `src/sixpack/ui/widgets/focus_grid.py`, give `FocusGrid` a new signal `focus_changed = pyqtSignal(int)`, emitted at the end of `focus_item()` (after the existing body, right before the method returns — after `self._scroll.ensureWidgetVisible(widget)`). This is a small, backward-compatible addition (existing callers that don't connect to it are unaffected). Then in `DetailGridScreen._build_ui`, connect it:

```python
        self._grid.focus_changed.connect(self._on_grid_focus_changed)
```

and add:

```python
    def _on_grid_focus_changed(self, index: int) -> None:
        if 0 <= index < len(self._items):
            self._reflect_focus(self._items[index])
```

Update Task 1's `FocusGrid` change set to include this signal (it's a natural extension of that same file — if Task 1 already landed without it, add it now as part of this task instead; either placement is fine, just don't leave it out).

- [ ] **Step 4: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_detail_grid.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` (2-3 times)
Expected: all passing, coverage ≥80%, no segfault.

- [ ] **Step 6: Commit**

```bash
git add src/sixpack/ui/screens/detail_grid.py src/sixpack/ui/widgets/focus_grid.py tests/test_ui/test_detail_grid.py
git commit -m "Add DetailGridScreen: shared Backdrop+hero+FocusGrid shell"
```

---

## Task 4: Rewrite `SeriesDetailScreen` on `DetailGridScreen`

**Files:**
- Modify: `src/sixpack/ui/screens/series_detail.py` (full rewrite)
- Modify: `tests/test_ui/test_screens.py`

**Interfaces:**
- Preserves exactly: `SeriesDetailScreen(cover_cache=None, parent=None)`, `episode_activated = pyqtSignal(object)` (SeriesBook), `back_requested = pyqtSignal()`, `show_loading(series, server_url="", token="")`, `load(series, progress, server_url="", token="")`, `update_progress(progress)`.
- Removes: `play_requested` signal, `EpisodeItem` class, `_on_play_all`, the "Play All" button — all now-dead now that Play All is gone (confirm via `grep -rn "detail_screen.play_requested\|_detail_screen\._play_all" src/` that nothing else references them before removing; `app.py`'s cleanup is Task 6, not this task — this task only removes what's internal to this file).
- New: `focus_item_by_key(key: str) -> None` (inherited from `DetailGridScreen`, no override needed) — exposed for Phase C's later use.

- [ ] **Step 1: Read the current file and its tests first**

Read `src/sixpack/ui/screens/series_detail.py` and the `# ---- SeriesDetailScreen ----` block in `tests/test_ui/test_screens.py` (find it via `grep -n "SeriesDetailScreen\|# ---- SeriesDetailScreen" tests/test_ui/test_screens.py`) in full before making any change — several existing tests exercise behavior this rewrite must still satisfy (`test_detail_screen_creates`, `test_detail_screen_load`, `test_detail_screen_back_signal`, `test_detail_screen_item_emits_episode_activated`, `test_detail_show_loading_renders_episodes`, `test_detail_update_progress_hides_loading`, `test_detail_resume_index_all_finished`, `test_detail_episode_activated_any_book`). Tests specifically about the now-removed `EpisodeItem`/Play-All behavior (`test_detail_screen_item_does_not_emit_play_requested`, `test_detail_play_all_resumes_from_progress`, `test_detail_play_all_finished_restarts`, `test_detail_screen_play_all_finds_resume`, `test_detail_episode_item_update_progress`, `test_detail_episode_item_has_cover_label`, `test_detail_episode_item_chapter_badge`, `test_detail_update_progress_dot_colour`) must be removed — they test behavior that no longer exists (a "dot" progress indicator, `EpisodeItem`'s own cover label, Play All itself).

- [ ] **Step 2: Write/update the failing tests**

In `tests/test_ui/test_screens.py`, replace the `# ---- SeriesDetailScreen ----` block with:

```python
# ---- SeriesDetailScreen ----

def _make_series() -> Series:
    media1 = LibraryItemMedia(metadata={"title": "Episode 1"}, duration=1800.0)
    media2 = LibraryItemMedia(metadata={"title": "Episode 2"}, duration=3600.0)
    b1 = SeriesBook(id="b1", libraryId="lib1", media=media1, sequence="1")
    b2 = SeriesBook(id="b2", libraryId="lib1", media=media2, sequence="2")
    return Series(id="s1", name="My Drama Series", books=[b1, b2])


def test_detail_screen_creates(qtbot):
    screen = SeriesDetailScreen()
    qtbot.addWidget(screen)
    assert screen._grid is not None


def test_detail_screen_load(qtbot):
    screen = SeriesDetailScreen()
    qtbot.addWidget(screen)
    series = _make_series()
    screen.load(series, {}, "http://localhost", "tok")
    assert screen._hero_title.text() == "My Drama Series"
    assert screen._grid.item_count == 2


def test_detail_screen_back_signal(qtbot):
    from sixpack.input.keyboard import key_to_action  # noqa: F401 — confirm import path used by screen
    screen = SeriesDetailScreen()
    qtbot.addWidget(screen)
    screen.load(_make_series(), {}, "http://localhost", "tok")
    screen.show()
    with qtbot.waitSignal(screen.back_requested, timeout=1000):
        qtbot.keyClick(screen, Qt.Key.Key_Backspace)


def test_detail_screen_item_emits_episode_activated(qtbot):
    screen = SeriesDetailScreen()
    qtbot.addWidget(screen)
    series = _make_series()
    screen.load(series, {}, "http://localhost", "tok")
    with qtbot.waitSignal(screen.episode_activated, timeout=1000) as blocker:
        screen._grid.item_activated.emit(0)
    assert blocker.args[0].id == "b1"


def test_detail_show_loading_renders_episodes(qtbot):
    screen = SeriesDetailScreen()
    qtbot.addWidget(screen)
    screen.show_loading(_make_series(), "http://localhost", "tok")
    assert screen._grid.item_count == 2


def test_detail_update_progress_refreshes_in_place(qtbot):
    screen = SeriesDetailScreen()
    qtbot.addWidget(screen)
    series = _make_series()
    screen.load(series, {}, "http://localhost", "tok")
    card_before = screen._grid._items[0]
    screen.update_progress({"b1": MediaProgress(currentTime=1800.0, duration=1800.0, isFinished=True)})
    assert screen._grid._items[0] is card_before


def test_detail_resume_index_all_finished(qtbot):
    screen = SeriesDetailScreen()
    qtbot.addWidget(screen)
    series = _make_series()
    progress = {
        "b1": MediaProgress(currentTime=1800.0, duration=1800.0, isFinished=True),
        "b2": MediaProgress(currentTime=3600.0, duration=3600.0, isFinished=True),
    }
    screen.load(series, progress, "http://localhost", "tok")
    assert screen._grid._focused_index == 0  # _find_resume_index falls back to 0


def test_detail_screen_focus_item_by_key(qtbot):
    screen = SeriesDetailScreen()
    qtbot.addWidget(screen)
    screen.load(_make_series(), {}, "http://localhost", "tok")
    screen.focus_item_by_key("b2")
    assert screen._grid._focused_index == 1
```

Check the real `MediaProgress` model's field names (`currentTime`/`duration`/`isFinished` or similar — grep `src/sixpack/api/models.py` for `class MediaProgress`) before finalizing these test bodies; use whatever the actual field names are, the above is illustrative of the shape, not necessarily exact.

- [ ] **Step 3: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_screens.py -v -k detail_screen`
Expected: FAIL (old implementation doesn't have `_grid`, `focus_item_by_key`, etc.)

- [ ] **Step 4: Rewrite `series_detail.py`**

```python
"""Series detail screen — episode grid with progress indicators."""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal

from sixpack.api.models import MediaProgress, Series, SeriesBook
from sixpack.ui.cover_cache import CoverCache
from sixpack.ui.screens.detail_grid import DetailGridScreen


class SeriesDetailScreen(DetailGridScreen):
    """
    Shows the episode grid for a series. Emits episode_activated(book) —
    the caller (app.py) decides whether to play directly or route through
    chapter selection, exactly as before this rewrite. Emits
    back_requested() on Back.
    """

    episode_activated = pyqtSignal(object)  # SeriesBook

    def __init__(self, cover_cache: CoverCache | None = None, parent=None) -> None:
        super().__init__(cover_cache=cover_cache, parent=parent)
        self.item_activated.connect(self.episode_activated)

    def _item_key(self, item: SeriesBook) -> str:
        return item.id

    def _item_progress(self, item: SeriesBook, progress: dict) -> tuple[float, bool]:
        prog: MediaProgress | None = progress.get(item.id)
        if prog is None or not item.duration:
            return 0.0, False
        finished = bool(prog.is_finished)
        fraction = 0.0 if finished else max(0.0, min(1.0, prog.current_time / item.duration))
        return fraction, finished

    def _item_title(self, item: SeriesBook) -> str:
        return item.title

    def _item_subtitle(self, item: SeriesBook) -> str:
        return f"Episode {item.sequence}" if item.sequence else ""

    def _item_cover_url(self, item: SeriesBook, server_url: str, token: str) -> str | None:
        return item.cover_url(server_url, token)

    def show_loading(self, series: Series, server_url: str = "", token: str = "") -> None:
        self._populate(series.name, series.sorted_books, {}, server_url, token, loading=True)

    def load(
        self,
        series: Series,
        progress: dict[str, MediaProgress],
        server_url: str = "",
        token: str = "",
    ) -> None:
        self._populate(series.name, series.sorted_books, progress, server_url, token)

    def update_progress(self, progress: dict[str, MediaProgress]) -> None:
        self._refresh_progress(progress)
```

Check `SeriesBook`'s actual fields (`id`, `sequence`, `duration`, `title`, `cover_url`) against `src/sixpack/api/models.py` before finalizing — this plan's earlier research confirmed `SeriesBook.title`/`.cover_url()` exist as properties; confirm `.duration` and `.sequence` similarly (the pre-rewrite `EpisodeItem._build_ui` already used `book.sequence`, `book.duration`, `len(book.media.chapters)` — use whatever the real attribute access pattern was there, adjusting the code above if it differs from what's shown).

- [ ] **Step 5: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_screens.py -v -k detail_screen`
Expected: PASS.

- [ ] **Step 6: Run the full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` (2-3 times)
Expected: all passing except tests that reference now-removed `play_requested` wiring in `app.py` — those are fixed in Task 6, not this task. If `app.py`-level tests fail because of this task's signal removal, note it in your report but do not fix `app.py` yet (that's Task 6's job — fixing it here would be doing Task 6's work out of order and losing the checkpoint). Coverage ≥80% is still required overall.

- [ ] **Step 7: Commit**

```bash
git add src/sixpack/ui/screens/series_detail.py tests/test_ui/test_screens.py
git commit -m "Rewrite SeriesDetailScreen on DetailGridScreen, remove Play All"
```

---

## Task 5: Rewrite `PlaylistDetailScreen` on `DetailGridScreen`

**Files:**
- Modify: `src/sixpack/ui/screens/playlist_detail.py` (full rewrite)
- Modify: `tests/test_ui/test_playlist_screens.py`

**Interfaces:** Mirrors Task 4 exactly, for `PlaylistItem`/`Playlist` instead of `SeriesBook`/`Series`. Preserves: `PlaylistDetailScreen(cover_cache=None, parent=None)`, `item_activated = pyqtSignal(object)` (PlaylistItem — note: the base class already has an `item_activated` signal with this exact name/signature, so unlike `SeriesDetailScreen` — which renames it to `episode_activated` for its own domain vocabulary — `PlaylistDetailScreen` can just use the inherited `item_activated` directly, no re-emit wrapper needed), `back_requested` (inherited), `show_loading(playlist, server_url="", token="")`, `load(playlist, progress, server_url="", token="")`, `update_progress(progress)`.

- [ ] **Step 1: Read the current file and its tests first**

Read `src/sixpack/ui/screens/playlist_detail.py` and the `# ---- PlaylistDetailScreen ----` block in `tests/test_ui/test_playlist_screens.py` in full. Tests to keep (adapting to the new implementation, same way Task 4 did): `test_playlist_detail_screen_creates`, `test_playlist_detail_screen_load`, `test_playlist_detail_screen_back_signal`, `test_playlist_detail_screen_item_emits_activated`, `test_playlist_detail_show_loading_renders_items`, `test_playlist_detail_update_progress_hides_loading` (rename/adapt to "refreshes in place", matching Task 4's `test_detail_update_progress_refreshes_in_place`), `test_playlist_detail_resume_index_all_finished`. Tests to remove (Play-All/`PlaylistItemWidget`-specific, no longer applicable): `test_playlist_detail_screen_play_all`, `test_playlist_detail_screen_play_all_skips_finished`, `test_playlist_detail_update_progress_dot_colour`, `test_playlist_item_widget_update_progress`, `test_playlist_detail_item_count_label` (only remove this last one if the count label itself is being dropped — check Step 4 below first; if the rewritten screen keeps some form of item count display, keep an adapted version of this test instead of deleting it).

- [ ] **Step 2: Write/update the failing tests**

Follow the exact same adaptation pattern Task 4 used for `test_screens.py`, applied to `test_playlist_screens.py`'s `PlaylistDetailScreen` block. Use `_make_item`/`_make_playlists`-equivalent fixtures already in that file (confirm `_make_item` still exists post-Phase-A — it should, Phase A only removed `_make_playlists`/`_make_libraries`, not `_make_item`, per Phase A's own plan). Add the same `test_playlist_detail_focus_item_by_key` test Task 4 added for the series screen.

- [ ] **Step 3: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_playlist_screens.py -v -k playlist_detail`
Expected: FAIL.

- [ ] **Step 4: Rewrite `playlist_detail.py`**

```python
"""Playlist detail screen — item grid with progress indicators."""
from __future__ import annotations

from sixpack.api.models import MediaProgress, Playlist, PlaylistItem
from sixpack.ui.cover_cache import CoverCache
from sixpack.ui.screens.detail_grid import DetailGridScreen


class PlaylistDetailScreen(DetailGridScreen):
    """
    Shows the item grid for a playlist. Emits item_activated(item) —
    the caller (app.py) decides whether to play directly or route through
    chapter selection. Emits back_requested() on Back.
    """

    def __init__(self, cover_cache: CoverCache | None = None, parent=None) -> None:
        super().__init__(cover_cache=cover_cache, parent=parent)

    def _item_key(self, item: PlaylistItem) -> str:
        return item.library_item_id

    def _item_progress(self, item: PlaylistItem, progress: dict) -> tuple[float, bool]:
        prog: MediaProgress | None = progress.get(item.library_item_id)
        if prog is None or not item.duration:
            return 0.0, False
        finished = bool(prog.is_finished)
        fraction = 0.0 if finished else max(0.0, min(1.0, prog.current_time / item.duration))
        return fraction, finished

    def _item_title(self, item: PlaylistItem) -> str:
        return item.title

    def _item_subtitle(self, item: PlaylistItem) -> str:
        return ""

    def _item_cover_url(self, item: PlaylistItem, server_url: str, token: str) -> str | None:
        return item.cover_url(server_url, token)

    def _item_media_type(self, item: PlaylistItem) -> str:
        return item.media_type

    def show_loading(self, playlist: Playlist, server_url: str = "", token: str = "") -> None:
        self._populate(playlist.name, playlist.items, {}, server_url, token, loading=True)

    def load(
        self,
        playlist: Playlist,
        progress: dict[str, MediaProgress],
        server_url: str = "",
        token: str = "",
    ) -> None:
        self._populate(playlist.name, playlist.items, progress, server_url, token)

    def update_progress(self, progress: dict[str, MediaProgress]) -> None:
        self._refresh_progress(progress)
```

Note `PlaylistDetailScreen` does **not** need an `episode_activated`-style re-emit wrapper the way `SeriesDetailScreen` does — the base's `item_activated` signal already matches what `app.py` expects to connect to (`self._playlist_detail_screen.item_activated.connect(self._on_playlist_item_activated)`). Confirm this against `app.py`'s actual current wiring (`grep -n "playlist_detail_screen\." src/sixpack/ui/app.py`) before assuming — if the real signal name/expectation differs from what's described here, match what `app.py` actually expects, since Task 6 is scoped to only removing the dead Play-All wiring, not renaming anything else.

- [ ] **Step 5: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_playlist_screens.py -v -k playlist_detail`
Expected: PASS.

- [ ] **Step 6: Run the full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` (2-3 times)
Expected: as with Task 4's Step 6 — `app.py`-level failures from dead Play-All wiring are expected and fixed in Task 6.

- [ ] **Step 7: Commit**

```bash
git add src/sixpack/ui/screens/playlist_detail.py tests/test_ui/test_playlist_screens.py
git commit -m "Rewrite PlaylistDetailScreen on DetailGridScreen, remove Play All"
```

---

## Task 6: `app.py` cleanup — remove dead Play-All wiring

**Files:**
- Modify: `src/sixpack/ui/app.py`

**Interfaces:** None new. Pure removal of now-unreachable code, mirroring Phase A's approach (grep-verified, targeted removal, not a rewrite).

- [ ] **Step 1: Confirm what's actually dead**

Run these and read the results before changing anything:
```bash
grep -n "detail_screen\.play_requested\|playlist_detail_screen\.play_requested\|_on_detail_play_requested\|_on_playlist_item_play_requested\|_on_play_requested\b" src/sixpack/ui/app.py
```

You should find: `self._detail_screen.play_requested.connect(self._on_detail_play_requested)` and `self._playlist_detail_screen.play_requested.connect(self._on_playlist_item_play_requested)` (now-dead — `SeriesDetailScreen`/`PlaylistDetailScreen` no longer have a `play_requested` signal after Tasks 4-5). Also confirm whether `_on_detail_play_requested` has any OTHER caller besides the wiring line just found (it shouldn't — it existed only to handle the Play-All button's signal) — if it has no other caller, it's dead too. Separately confirm `_on_playlist_item_play_requested` and `_on_play_requested` **do** have other live callers (`self._chapter_screen.playlist_item_play_requested.connect(self._on_playlist_item_play_requested)` and `self._chapter_screen.play_requested.connect(self._on_play_requested)`) — these two methods must be **kept**, only the now-dead wiring line feeding into `_on_playlist_item_play_requested` from `playlist_detail_screen` should be removed, not the method itself.

- [ ] **Step 2: Remove the dead wiring**

Remove these two lines (find their current location — Phase A's own task shifted nearby line numbers, don't trust old numbers):
```python
        self._detail_screen.play_requested.connect(self._on_detail_play_requested)
```
```python
        self._playlist_detail_screen.play_requested.connect(self._on_playlist_item_play_requested)
```

If Step 1 confirmed `_on_detail_play_requested` has no other caller, remove the method itself too:
```python
    def _on_detail_play_requested(self, book: SeriesBook, start_time: float) -> None:
        self._on_play_requested(book, start_time)
```

Do **not** remove `_on_play_requested` or `_on_playlist_item_play_requested` — both are still called from `_chapter_screen`'s signals (confirmed live in Step 1).

- [ ] **Step 3: Grep for anything else stale**

```bash
grep -rn "play_requested" src/sixpack/ui/screens/series_detail.py src/sixpack/ui/screens/playlist_detail.py
```
Expected: no output (both files no longer define or emit `play_requested` after Tasks 4-5).

- [ ] **Step 4: Run the full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` (2-3 times)
Expected: all passing now (the `app.py`-level failures noted as expected in Tasks 4/5 should be resolved), coverage ≥80%, no segfault.

- [ ] **Step 5: Commit**

```bash
git add src/sixpack/ui/app.py
git commit -m "Remove app.py wiring for the now-removed Play All signal"
```

---

## Task 7: `ChapterSelectScreen` cinematic list redesign

**Files:**
- Modify: `src/sixpack/ui/screens/chapter_select.py` (full rewrite)
- Modify: `tests/test_ui/test_screens.py`

**Interfaces:** Preserves exactly: `ChapterSelectScreen(cover_cache=None, parent=None)`, `play_requested = pyqtSignal(object, float)`, `playlist_item_play_requested = pyqtSignal(object, float)`, `library_item_play_requested = pyqtSignal(object, float)`, `back_requested = pyqtSignal()`, `load_from_library_item(item, chapters, progress, server_url="", token="")`, `load(book, chapters, progress, server_url="", token="")`, `load_from_playlist_item(item, chapters, progress, server_url="", token="")`. This screen does **not** subclass `DetailGridScreen` (chapters are a list, not a card grid, per the spec's explicit exception) but reuses the same `Backdrop` + hero visual shell directly.

- [ ] **Step 1: Read the current file and its tests first**

Read `src/sixpack/ui/screens/chapter_select.py` and the `# ---- ChapterSelectScreen ----` block in `tests/test_ui/test_screens.py` in full. This screen has no "Play All" to remove (chapters activate directly, always have) — this task is a pure visual/structural redesign, not a behavior-removal task like Tasks 4-5. Keep the existing `_chapter_status` helper function and `_fmt_duration` as-is (pure functions, not part of the visual redesign).

- [ ] **Step 2: Write/update the failing tests**

Adapt the existing chapter-screen tests (`test_chapter_screen_creates`, `test_chapter_screen_load`, `test_chapter_screen_play_signal`, `test_chapter_screen_back_signal`, `test_chapter_screen_resume_index_in_progress`, `test_chapter_screen_resume_index_finished`, `test_chapter_status_finished_book`, `test_chapter_status_in_progress`, `test_chapter_screen_load_from_library_item`, `test_chapter_screen_library_item_play_signal`, `test_chapter_screen_load_clears_library_item`, `test_chapter_screen_load_from_library_item_resume`) to whatever the new internal structure exposes (e.g. if chapters are now rendered as a `QListWidget` still, but with restyled `ChapterItem` rows carrying a progress bar + checkmark instead of a dot, most of these tests need only their assertions about visual internals updated, not their overall shape — read each one and adjust the specific lines that poke at now-changed internals). `test_chapter_status_finished_book`/`test_chapter_status_in_progress` test the pure `_chapter_status` helper directly and need no changes if that helper is unchanged.

Add:
```python
def test_chapter_screen_hero_shows_book_title(qtbot):
    from sixpack.ui.screens.chapter_select import ChapterSelectScreen
    screen = ChapterSelectScreen()
    qtbot.addWidget(screen)
    book = ...  # build via the same helper the existing tests already use
    screen.load(book, [...], None, "http://localhost", "tok")
    assert screen._hero_title.text() == book.title
```
(Fill in the `...` using this file's existing `_make_series`/book-construction helpers — do not invent new fixture shapes when an existing one already builds a compatible object.)

- [ ] **Step 3: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_screens.py -v -k chapter_screen`
Expected: FAIL on whatever assertions target now-changed internals.

- [ ] **Step 4: Implement the redesign**

Rewrite `ChapterItem` to match `MediaCard`'s progress language: replace the small colored `dot` with a thin progress bar (same visual weight as `MediaCard.set_progress`'s bar — reuse the same drawing approach, adapted to a full-width row rather than a card-bottom overlay) plus a small checkmark (reuse the `_FinishedBadge` painting logic from Task 2, or a simpler inline equivalent sized for a list row — your call, but keep the same `theme.SUCCESS` checkmark visual language, not a new one) when `status == "finished"`. Give focused rows the same `ACCENT`-bordered treatment they already have (`set_focused` already exists and is fine as-is structurally) but confirm the border/background values still match current `theme` tokens (no other change needed there).

Wrap the existing `QListWidget` (keep it — a `QListWidget` is the right structural choice for a single-column list, `FocusGrid` is for wrapping multi-column grids and doesn't fit here) in the same `Backdrop` + hero shell `DetailGridScreen` uses — but since `ChapterSelectScreen` isn't a `DetailGridScreen` subclass, build this shell directly in `_build_ui` (copy the `Backdrop`/hero construction pattern from `detail_grid.py`, adapted: no `FocusGrid`, just the existing `QListWidget` in its place, and give the `QListWidget` + its viewport the same transparent-background treatment `browse.py`'s `_rows_scroll`/`_grid_scroll` needed — `QListWidget` inherits from `QAbstractScrollArea`, so it needs the identical treatment: `self._list.setStyleSheet(...)` including `background: transparent` merged into its existing stylesheet rules, plus `self._list.viewport().setStyleSheet("background: transparent;")`).

Hero title = book/item title (static, matches the existing top-bar title label's content, just visually upgraded to the hero treatment). Hero subtitle: chapter count (e.g. `f"{len(chapters)} chapters"`, matching the existing `_count_label`'s content). No per-chapter backdrop cross-fade — the backdrop shows the ONE cover for this book, set once via `show_color`/`show_image` in each `load*` method (fetch the cover through `self._cover_cache` the same way `_populate`/`_make_card` do elsewhere, but call `self._backdrop.show_color(...)`/`show_image(...)` directly rather than per-focused-item, since focus moving between chapters shouldn't retrigger a cover fetch for art that hasn't changed).

- [ ] **Step 5: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_screens.py -v -k chapter_screen`
Expected: PASS.

- [ ] **Step 6: Run the full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` (2-3 times)
Expected: all passing, coverage ≥80%, no segfault.

- [ ] **Step 7: Commit**

```bash
git add src/sixpack/ui/screens/chapter_select.py tests/test_ui/test_screens.py
git commit -m "Redesign ChapterSelectScreen with cinematic Backdrop+hero shell"
```

---

## Task 8: Visual verification

**Files:** none (verification only; small follow-up commits allowed for tuning).

- [ ] **Step 1: Real-data screenshot check**

Using the pattern already established in `tools/shots.py` (extend it, or write a throwaway variant — this file is dev-only, not tested/packaged, per its own header comment), render `SeriesDetailScreen` and `PlaylistDetailScreen` populated with real data from a merton.home library that has a series/playlist with several episodes, and `ChapterSelectScreen` for a multi-chapter book. Confirm: backdrop is visible (not occluded — the exact failure mode Task 1 exists to prevent), focused card/row shows a clear glow, unfocused cards/rows are dimmed, progress bars and finished checkmarks render correctly, hero title/subtitle are legible.

- [ ] **Step 2: Tune if needed**

If anything looks visually wrong (spacing, contrast, a badge overlapping text), fix it directly and re-verify with another screenshot. Commit tuning separately if any is needed:
```bash
git add -A
git commit -m "Tune Phase B detail-screen visuals after real-data review"
```

- [ ] **Step 3: Final full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` (3 times)
Expected: all passing, coverage ≥80%, no segfault.

---

## Self-Review

**Spec coverage:**
- Shared `DetailGridScreen` base replacing duplicated code → Tasks 3-5. ✓
- `MediaCard` reuse with progress bar + finished checkmark → Tasks 2-5. ✓
- Chapters stay a list (not cards), same shell → Task 7. ✓
- "Play All" removed → Tasks 4-6. ✓
- End-of-book behavior: this phase adds `focus_item_by_key` (the capability) but explicitly does not wire it into `_on_next_item`/end-of-track — documented as an intentional phase boundary in Global Constraints, completed in Phase C. ✓
- `FocusGrid` transparent-background fix (a bug this phase would otherwise reintroduce) → Task 1. ✓

**Placeholder scan:** No TBDs. Where exact current-file content couldn't be pasted verbatim (things Phase A's own edits, or this plan's own earlier tasks, will have shifted), each step explicitly says to read the current file and gives a precise description of what to find/remove, rather than leaving a vague "handle this" instruction.

**Type consistency:** `DetailGridScreen`'s subclass contract (`_item_key`, `_item_progress`, `_item_title`, `_item_subtitle`, `_item_cover_url`, `_item_media_type`) is used identically by both `SeriesDetailScreen` (Task 4) and `PlaylistDetailScreen` (Task 5) with matching signatures. `focus_item_by_key(key: str)` is defined once in Task 3 and consumed without an override in both Task 4/5's subclasses — verified the base's generic implementation (search by `_item_key(item) == key`) needs no per-subclass customization. `MediaCard.set_finished(bool)` (Task 2) is called identically from `DetailGridScreen._make_card`/`_refresh_progress` (Task 3).
