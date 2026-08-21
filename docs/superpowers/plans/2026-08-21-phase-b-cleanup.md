# Phase B Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Address the final Phase B whole-plan review's findings before Phase C begins: extract the now-3x-duplicated `Backdrop`+hero shell into one reusable component (used by `DetailGridScreen` and `ChapterSelectScreen`, so Phase C's player screen doesn't make it a 4th copy), fix a real bug where a redundant call defeats the backdrop cross-fade animation, fix a hero-subtitle inconsistency between the two detail screens, and add test coverage for previously-unasserted progress arithmetic.

**Architecture:** A new `HeroBackdrop` composed widget (owns `Backdrop` + hero title/subtitle overlay + their geometry) that `DetailGridScreen`/`ChapterSelectScreen` each instantiate as a child and delegate to — composition, not inheritance, since both are already `QWidget` subclasses with their own `resizeEvent` needs for their own content (`FocusGrid`/`QListWidget`). `browse.py` is deliberately NOT migrated to this component — it has a materially different, already-shipped, already-reviewed design (rows scroll *underneath* a translucent hero, vs. the detail screens' content-starts-below-hero approach) serving a different UX need (many-row browsing vs. a single focused item's grid/list); retrofitting it now would be a bigger, riskier change for a marginal DRY win outside this cleanup's actual purpose.

**Tech Stack:** Python 3.12, PyQt6, pytest + pytest-qt (headless via `QT_QPA_PLATFORM=offscreen`).

**Spec:** `docs/superpowers/specs/2026-08-21-app-wide-cinematic-redesign-design.md` (Phase B section — this plan is a follow-up correcting that phase's own final review findings, not new spec scope)

## Global Constraints

- Python ≥ 3.10 (dev/target uses 3.12). Line length 100 (ruff). `select = ["E","F","I","UP"]`.
- Coverage gate: `--cov-fail-under=80` must keep passing.
- All Qt tests run under `QT_QPA_PLATFORM=offscreen`.
- No `QGraphicsEffect` subclass anywhere, ever — see `docs/qt-graphics-effect-crash.md`.
- Every scroll/container widget between a `Backdrop` and the screen surface needs explicit `background: transparent` styling — verify by construction (an offscreen pixel-sample render, matching this project's own established verification method for this exact bug class), not by assumption.
- `SeriesDetailScreen.load(series, progress, server_url, token)`/`PlaylistDetailScreen.load(playlist, progress, server_url, token)`/`ChapterSelectScreen.load*(...)` signatures must not change — `app.py` calls them as-is.
- Do not touch `browse.py`'s `Backdrop`/hero construction — out of scope for this cleanup, per the Architecture section above.
- Commit after each task. Branch: `feature/app-wide-cinematic-redesign`.

---

## File Structure

| File | Change |
|------|--------|
| `src/sixpack/ui/widgets/hero_backdrop.py` (new) | `HeroBackdrop` composed widget: `Backdrop` + hero title/subtitle overlay |
| `src/sixpack/ui/screens/detail_grid.py` (edit) | Use `HeroBackdrop` instead of its own duplicated construction; fix double-`_reflect_focus`; add missing progress-fraction test |
| `src/sixpack/ui/screens/series_detail.py` (edit) | Fix hero subtitle to include episode title, not just the sequence number |
| `src/sixpack/ui/screens/chapter_select.py` (edit) | Use `HeroBackdrop`; fix unguarded async `show_color` race; fix stale hero/backdrop on empty chapter list |
| `tests/test_ui/test_widgets.py` (edit) | New `HeroBackdrop` tests |
| `tests/test_ui/test_detail_grid.py` (edit) | Add progress-fraction + finished-badge-wiring tests; update for `HeroBackdrop` internals if any test reaches into removed private attributes |
| `tests/test_ui/test_screens.py` (edit) | Add `_chapter_fraction` direct test; update for `HeroBackdrop` internals if needed; fix the one new `F541` lint finding |

---

## Task 1: Extract `HeroBackdrop` shared component

**Files:**
- Create: `src/sixpack/ui/widgets/hero_backdrop.py`
- Test: `tests/test_ui/test_widgets.py`

**Interfaces:**
- Produces: `HeroBackdrop(parent: QWidget | None = None)` — a `QWidget` owning a `Backdrop` (accessible via `.backdrop`, a `Backdrop` instance — callers use `.backdrop.show_color(...)`/`.backdrop.show_image(...)`/`.backdrop.set_expected_key(...)` directly, no new wrapper methods needed for these) and a hero title/subtitle overlay (`.set_title(text: str)`, `.set_subtitle(text: str)`). Class constant `HERO_H = 150`. The owning screen calls `hero_backdrop.setGeometry(self.rect())` from its own `resizeEvent`; `HeroBackdrop`'s own `resizeEvent` positions its `Backdrop` (fills self) and hero overlay (top `HERO_H` px) accordingly.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_ui/test_widgets.py`:

```python
def test_hero_backdrop_creates(qtbot):
    from sixpack.ui.widgets.hero_backdrop import HeroBackdrop
    hb = HeroBackdrop()
    qtbot.addWidget(hb)
    assert hb.backdrop is not None


def test_hero_backdrop_set_title_and_subtitle(qtbot):
    from sixpack.ui.widgets.hero_backdrop import HeroBackdrop
    hb = HeroBackdrop()
    qtbot.addWidget(hb)
    hb.set_title("My Series")
    hb.set_subtitle("Episode 1")
    assert hb._hero_title.text() == "My Series"
    assert hb._hero_sub.text() == "Episode 1"


def test_hero_backdrop_resize_positions_children(qtbot):
    from sixpack.ui.widgets.hero_backdrop import HeroBackdrop
    hb = HeroBackdrop()
    qtbot.addWidget(hb)
    hb.resize(800, 600)
    assert hb.backdrop.geometry() == hb.rect()
    assert hb._hero.geometry().height() == HeroBackdrop.HERO_H
    assert hb._hero.geometry().width() == 800
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_widgets.py -v -k hero_backdrop`
Expected: FAIL — `ModuleNotFoundError: No module named 'sixpack.ui.widgets.hero_backdrop'`.

- [ ] **Step 3: Implement `HeroBackdrop`**

Read `src/sixpack/ui/screens/detail_grid.py`'s current `_build_ui`/`_build_hero`/`_hero_geometry`/`resizeEvent` in full first — this extraction is a near-verbatim move of that code into a new, standalone widget, not a rewrite. Create `src/sixpack/ui/widgets/hero_backdrop.py`:

```python
"""Shared Backdrop+hero shell, composed into detail-style screens.

DetailGridScreen and ChapterSelectScreen both show one Backdrop (blurred
cover-art background) behind their content, with a hero title/subtitle
overlay in the top band. This was duplicated across both files almost
verbatim; this widget is the single implementation both compose instead
of inheriting or re-copying.

Deliberately NOT used by browse.py, which has a materially different
design (rows scroll *underneath* a translucent hero, vs. this widget's
content-starts-below-hero approach used by the single-item detail
screens) — see docs/superpowers/plans/2026-08-21-phase-b-cleanup.md.
"""
from __future__ import annotations

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from sixpack.ui import theme
from sixpack.ui.widgets.backdrop import Backdrop


class HeroBackdrop(QWidget):
    """A Backdrop plus a title/subtitle hero overlay in the top HERO_H px."""

    HERO_H = 150

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.backdrop = Backdrop(self)
        self.backdrop.lower()
        self._build_hero()

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

    def resizeEvent(self, event) -> None:
        self.backdrop.setGeometry(self.rect())
        self._hero.setGeometry(QRect(0, 0, self.width(), self.HERO_H))
        super().resizeEvent(event)

    def set_title(self, text: str) -> None:
        self._hero_title.setText(text)

    def set_subtitle(self, text: str) -> None:
        self._hero_sub.setText(text)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_widgets.py -v -k hero_backdrop`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/sixpack/ui/widgets/hero_backdrop.py tests/test_ui/test_widgets.py
git commit -m "Extract HeroBackdrop: shared Backdrop+hero shell"
```

---

## Task 2: Migrate `DetailGridScreen` and `ChapterSelectScreen` onto `HeroBackdrop`

**Files:**
- Modify: `src/sixpack/ui/screens/detail_grid.py`
- Modify: `src/sixpack/ui/screens/chapter_select.py`
- Test: `tests/test_ui/test_detail_grid.py`, `tests/test_ui/test_screens.py`

**Interfaces:**
- Consumes: `HeroBackdrop` from Task 1.
- `DetailGridScreen`/`ChapterSelectScreen`'s own public API (`_populate`/`_refresh_progress`/`focus_item_by_key`, `load*` methods, signals) — unchanged. Internal attributes `_hero_title`/`_hero_sub`/`_backdrop` are replaced by delegating through `self._hero_backdrop` — if any existing test reaches into these private attributes directly (e.g. `screen._hero_title.text()`), update it to `screen._hero_backdrop._hero_title.text()` (or add a small `hero_title_text()`/`hero_subtitle_text()` test-only accessor if that reads better — your call, but keep it consistent across both files).

- [ ] **Step 1: Read both current files' `_build_ui`/hero/backdrop code in full**, plus every existing test in `test_detail_grid.py` and the `# ---- ChapterSelectScreen ----` block in `test_screens.py` that references `_hero_title`, `_hero_sub`, or `_backdrop` directly.

- [ ] **Step 2: Update the failing/affected tests** to reach through `_hero_backdrop` (or whatever accessor you settle on) instead of the removed direct attributes. Do this for every such test in both files — grep for `_hero_title\|_hero_sub\|\.backdrop\b\|self\._backdrop\b` in the two test files first to find them all.

- [ ] **Step 3: Run tests to verify they fail** (they should fail exactly where the private-attribute access no longer resolves, confirming Step 2's edits are needed):

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_detail_grid.py tests/test_ui/test_screens.py -v -k "detail_grid or chapter_screen"`

- [ ] **Step 4: Migrate `detail_grid.py`**

Replace the `Backdrop`/hero construction in `_build_ui` and the standalone `_build_hero`/`_hero_geometry`/`resizeEvent` methods with:

```python
    def _build_ui(self) -> None:
        self._hero_backdrop = HeroBackdrop(self)

        self._grid = FocusGrid(columns=5)
        self._grid.item_activated.connect(self._on_item_activated)
        self._grid.focus_changed.connect(self._on_grid_focus_changed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, HeroBackdrop.HERO_H, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._grid)

    def resizeEvent(self, event) -> None:
        self._hero_backdrop.setGeometry(self.rect())
        super().resizeEvent(event)
```

Update `_populate`/`_refresh_progress`/`_reflect_focus` to call `self._hero_backdrop.set_title(...)`/`.set_subtitle(...)` and `self._hero_backdrop.backdrop.set_expected_key(...)`/`.show_color(...)`/`.show_image(...)` instead of the removed `self._hero_title`/`self._hero_sub`/`self._backdrop` — a straightforward rename at each call site, not a logic change. Add the import: `from sixpack.ui.widgets.hero_backdrop import HeroBackdrop`. Remove the now-unused `Backdrop`, `QRect`, `QLabel` imports if nothing else in the file still needs them (check first).

- [ ] **Step 5: Migrate `chapter_select.py`** — same pattern as Step 4, adapted: keep `self._list` (the `QListWidget`) in place of `self._grid`, same `layout.setContentsMargins(0, HeroBackdrop.HERO_H, 0, 0)`, same `resizeEvent`/hero-delegation changes. `_load_backdrop`'s calls to `self._backdrop.show_color`/`.show_image`/`.set_expected_key` become `self._hero_backdrop.backdrop.show_color`/etc.

- [ ] **Step 6: Verify no occlusion regression** — this exact bug class (opaque container hiding a `Backdrop`) has shipped multiple times in this project. Write a quick offscreen pixel-sample check (construct each screen, force `hero_backdrop.backdrop` to a known solid color via `show_color`, render, sample a gutter pixel in the content area) — this doesn't need to be a permanent test if Task 1's `HeroBackdrop` tests plus the existing per-screen transparency tests already cover the underlying mechanism, but confirm it directly before moving on, and say in your report whether you added a permanent test or did a one-off verification (either is acceptable, but state which).

- [ ] **Step 7: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_detail_grid.py tests/test_ui/test_screens.py -v -k "detail_grid or chapter_screen"`
Expected: PASS.

- [ ] **Step 8: Run the full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` (3 times)
Expected: all passing, coverage ≥80%, no segfault.

- [ ] **Step 9: Commit**

```bash
git add src/sixpack/ui/screens/detail_grid.py src/sixpack/ui/screens/chapter_select.py tests/test_ui/test_detail_grid.py tests/test_ui/test_screens.py
git commit -m "Migrate DetailGridScreen and ChapterSelectScreen onto HeroBackdrop"
```

---

## Task 3: Fix the double-`_reflect_focus` call that defeats the backdrop cross-fade

**Files:**
- Modify: `src/sixpack/ui/screens/detail_grid.py`

**Interfaces:** No new interfaces — pure removal of redundant calls.

- [ ] **Step 1: Read `_populate`, `_refresh_progress`, and `focus_item_by_key` in the current file.** Each currently ends with an explicit `self._reflect_focus(self._items[idx])`-style call in addition to the reflection that now happens automatically via `FocusGrid.focus_item()` → `focus_changed` signal → `self._on_grid_focus_changed` → `_reflect_focus`. Confirm this by tracing the call chain in the actual code before removing anything.

- [ ] **Step 2: Write a regression test proving the fix** — instrument with a fake `CoverCache` (following the `_FakeCoverCache` pattern already used in `tests/test_ui/test_browse_screen.py` and `tests/test_ui/test_screens.py`'s chapter-screen tests) that counts `fetch_backdrop` calls, and assert `_populate` triggers exactly one call (not two) for the initially-focused item. Add to `tests/test_ui/test_detail_grid.py`.

- [ ] **Step 3: Run the test to verify it fails** (should show 2 calls where 1 is expected).

- [ ] **Step 4: Remove the three redundant explicit `_reflect_focus(...)` calls** in `_populate`/`_refresh_progress`/`focus_item_by_key`, relying solely on `FocusGrid.focus_item()`'s `focus_changed` signal to trigger reflection. Verify `FocusGrid.focus_item()` is still actually called in all three methods (it must be, to move visual focus onto the resume-index/target card) — you're only removing the *separate, explicit* `_reflect_focus` call, not the `focus_item` call that already triggers it via the signal.

- [ ] **Step 5: Run the test to verify it passes**, then run the full suite: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` (2-3 times).

- [ ] **Step 6: Verify the cross-fade actually plays now** — this is the actual point of the fix. Write a quick offscreen check (or extend the Task 2 Step 6 verification) that calls `_populate`, pumps the Qt event loop for slightly less than `Backdrop`'s fade duration (`_FADE_MS = 200`, check `backdrop.py`), and confirms `self._hero_backdrop.backdrop._fade` is mid-transition (`0.0 < fade < 1.0`) rather than having already snapped to settled — before the fix, the second immediate `show_image` call would have reset the animation each time, and depending on timing this could either restart it correctly or produce visibly janky snapping; describe in your report what you found (a settled/instant jump before the fix, if you can reproduce it, versus a genuine transition after).

- [ ] **Step 7: Commit**

```bash
git add src/sixpack/ui/screens/detail_grid.py tests/test_ui/test_detail_grid.py
git commit -m "Fix double _reflect_focus call that was defeating the backdrop cross-fade"
```

---

## Task 4: Fix series-screen hero subtitle to show the episode title

**Files:**
- Modify: `src/sixpack/ui/screens/series_detail.py`
- Test: `tests/test_ui/test_screens.py`

**Interfaces:** `SeriesDetailScreen._item_subtitle(item)` — same signature, changed return value.

- [ ] **Step 1: Write the failing test**

In `tests/test_ui/test_screens.py`, near the existing `SeriesDetailScreen` tests:

```python
def test_detail_screen_hero_subtitle_includes_episode_title(qtbot):
    screen = SeriesDetailScreen()
    qtbot.addWidget(screen)
    series = _make_series()  # existing helper — first book has sequence="1", title="Episode 1"
    screen.load(series, {}, "http://localhost", "tok")
    sub = screen._hero_backdrop._hero_sub.text()
    assert "1" in sub
    assert "Episode 1" in sub
```

(Adjust the exact assertion to match whatever format you implement in Step 3 — the requirement is both the sequence number AND the book's actual title must be present, since today's implementation shows only the number and the title appears nowhere else on this screen.)

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_screens.py -v -k hero_subtitle_includes_episode_title`
Expected: FAIL.

- [ ] **Step 3: Implement**

In `src/sixpack/ui/screens/series_detail.py`, change `_item_subtitle`:

```python
    def _item_subtitle(self, item: SeriesBook) -> str:
        if item.sequence:
            return f"Episode {item.sequence} · {item.title}"
        return item.title
```

This makes the series screen's hero subtitle behavior consistent with the playlist screen's (`PlaylistDetailScreen._item_subtitle` returns `""`, so `DetailGridScreen._reflect_focus`'s `self._item_subtitle(item) or self._item_title(item)` fallback already shows the title there) — both screens' hero subtitle now always shows the focused item's title, with the series screen additionally prefixing the episode number when one exists.

- [ ] **Step 4: Run test to verify it passes**, then the full suite: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` (2-3 times).

- [ ] **Step 5: Commit**

```bash
git add src/sixpack/ui/screens/series_detail.py tests/test_ui/test_screens.py
git commit -m "Show episode title in series-screen hero subtitle, not just the sequence number"
```

---

## Task 5: Add missing test coverage for progress arithmetic

**Files:**
- Modify: `tests/test_ui/test_detail_grid.py`
- Modify: `tests/test_ui/test_screens.py`

**Interfaces:** No production code changes — test-only task.

- [ ] **Step 1: Write a direct test for `SeriesDetailScreen._item_progress`'s fraction branch**

In `tests/test_ui/test_screens.py`:

```python
def test_detail_screen_item_progress_fraction(qtbot):
    screen = SeriesDetailScreen()
    qtbot.addWidget(screen)
    book = _make_series().sorted_books[0]  # duration 1800.0 per _make_series's media1
    prog = MediaProgress(currentTime=900.0, duration=1800.0, isFinished=False)
    fraction, finished = screen._item_progress(book, {book.id: prog})
    assert abs(fraction - 0.5) < 1e-6
    assert finished is False


def test_detail_screen_item_progress_finished_is_zero_fraction(qtbot):
    screen = SeriesDetailScreen()
    qtbot.addWidget(screen)
    book = _make_series().sorted_books[0]
    prog = MediaProgress(currentTime=1800.0, duration=1800.0, isFinished=True)
    fraction, finished = screen._item_progress(book, {book.id: prog})
    assert fraction == 0.0
    assert finished is True
```

Add the equivalent pair for `PlaylistDetailScreen._item_progress` in `tests/test_ui/test_playlist_screens.py`, using that file's existing `_make_item`/playlist-construction helpers.

- [ ] **Step 2: Write a direct test for `_chapter_fraction` in `chapter_select.py`**

Check the actual current signature/location of `_chapter_fraction` in `src/sixpack/ui/screens/chapter_select.py` first (it's a module-level pure function per the final review's finding). In `tests/test_ui/test_screens.py`, near the existing `_chapter_status`/`test_chapter_status_*` tests:

```python
def test_chapter_fraction_not_in_progress_is_zero():
    from sixpack.ui.screens.chapter_select import _chapter_fraction, Chapter
    ch = Chapter(id=0, start=0.0, end=60.0, title="Ch 1")
    assert _chapter_fraction(ch, current_time=0.0, status="unstarted") == 0.0


def test_chapter_fraction_in_progress_computes_correctly():
    from sixpack.ui.screens.chapter_select import _chapter_fraction, Chapter
    ch = Chapter(id=0, start=60.0, end=120.0, title="Ch 2")
    # 15s into a 60s chapter that starts at t=60
    assert abs(_chapter_fraction(ch, current_time=75.0, status="in_progress") - 0.25) < 1e-6


def test_chapter_fraction_zero_span_is_zero():
    from sixpack.ui.screens.chapter_select import _chapter_fraction, Chapter
    ch = Chapter(id=0, start=60.0, end=60.0, title="Ch (zero-length)")
    assert _chapter_fraction(ch, current_time=60.0, status="in_progress") == 0.0
```

Check `Chapter`'s real constructor field names/aliases in `src/sixpack/api/models.py` and `_chapter_fraction`'s actual parameter names before finalizing — adjust to match, this is illustrative of the required coverage (not-in-progress → 0.0, correct fraction when in-progress, zero/negative span → 0.0 without a `ZeroDivisionError`), not literal code to paste unchecked.

- [ ] **Step 3: Write a test connecting `_refresh_progress` to `MediaCard.set_finished`**

In `tests/test_ui/test_detail_grid.py`, using the existing `_TestScreen` test fixture:

```python
def test_detail_grid_refresh_progress_sets_finished_badge(qtbot):
    screen = _TestScreen()
    qtbot.addWidget(screen)
    screen._populate("My Series", _items(), {}, "http://s", "t")
    screen._refresh_progress({"a": {"fraction": 1.0, "finished": True}})
    card = screen._grid._items[0]
    assert card._finished is True
```

(Adjust to whatever the real `MediaCard` attribute/accessor for finished-state is — check `set_finished`'s implementation in `media_card.py`, added in an earlier Phase B task, for the exact internal state to assert against.)

- [ ] **Step 4: Run all new tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_detail_grid.py tests/test_ui/test_screens.py tests/test_ui/test_playlist_screens.py -v -k "progress_fraction or chapter_fraction or finished_badge"`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` (2-3 times)
Expected: all passing, coverage ≥80%, no segfault.

- [ ] **Step 6: Commit**

```bash
git add tests/test_ui/test_detail_grid.py tests/test_ui/test_screens.py tests/test_ui/test_playlist_screens.py
git commit -m "Add test coverage for progress-fraction arithmetic and finished-badge wiring"
```

---

## Task 6: Sweep remaining small fixes

**Files:**
- Modify: `src/sixpack/ui/screens/chapter_select.py`
- Modify: `src/sixpack/ui/screens/detail_grid.py`

**Interfaces:** No new public interfaces.

- [ ] **Step 1: Fix the unguarded async `show_color` race in `chapter_select.py`**

Read `_load_backdrop`'s `_color_cb` in the current file. Unlike `browse.py`/`detail_grid.py` (where `show_color` is called synchronously from an already-cached dominant color, strictly before any async fetch), this file's `_color_cb` is itself an async callback with no staleness guard — it can paint a stale color after navigating to a different book, or clobber an already-shown blurred backdrop with a flat gradient if the raw cover was evicted from `CoverCache` but the backdrop JPEG wasn't (they share `_MAX_ENTRIES`).

Fix: store a `self._backdrop_key` (e.g. the book/item's id, set synchronously in `_load_backdrop` before kicking off the async fetch — same pattern as `Backdrop.set_expected_key`, but at the screen level since this guards which book's *dominant color fetch* is still relevant, a different check than `Backdrop`'s own key guard on the blurred-image fetch). In `_color_cb`, compare against the current `self._backdrop_key` and return early if it no longer matches, mirroring the `sip.isdeleted`-adjacent staleness-guard style already used elsewhere in this file.

- [ ] **Step 2: Fix stale hero/backdrop on an empty chapter/episode/item collection**

In `detail_grid.py`'s `_populate`, the hero subtitle and backdrop are currently only updated inside `if self._grid.item_count:` — meaning opening an empty series/playlist after a populated one leaves the previous item's subtitle text and cover wash visible under the new (correct) hero title. Add an `else` branch that clears the hero subtitle (`self._hero_backdrop.set_subtitle("")`) and resets the backdrop to a neutral/empty state (check what `Backdrop` offers for "show nothing" — likely `show_color` with a neutral `theme` color, or check if there's already a pattern for this elsewhere in the codebase before inventing one).

- [ ] **Step 3: Fix the dead `loading` parameter**

`DetailGridScreen._populate`'s `loading: bool = False` parameter is currently a `# noqa: ARG002`-suppressed no-op — the old "Loading…" label this replaced was removed with no equivalent. Either wire it to a real (even minimal) loading affordance, or remove the parameter entirely from `_populate` and its callers (`show_loading` methods in `series_detail.py`/`playlist_detail.py`/wherever else it's passed) if no loading UI is planned for this phase. Prefer removing it over leaving unused API surface — YAGNI — unless you find a cheap, clearly-justified way to make it do something real in the time this task allows; don't force a design decision beyond this cleanup's scope.

- [ ] **Step 4: Fix the inaccurate code comment**

Both `detail_grid.py` and `chapter_select.py` currently have a comment claiming their top-margin fix "matches browse.py's `rows_layout` treatment" — per the final review, this isn't accurate: browse.py applies the margin *inside* a scroll area (content scrolls under a translucent hero), these two apply it to the outer layout (content is clipped at the hero's bottom edge, never passes underneath it) — a different, arguably better mechanism for a focused item's glow never being hidden under the scrim, but not the same mechanism. Correct the comment to describe what this code actually does, without claiming parity with browse.py's approach.

- [ ] **Step 5: Fix the `F541` lint finding**

In `chapter_select.py`, the `QListWidget` stylesheet (touched during Task 2's `HeroBackdrop` migration) — check whether it still uses an f-string prefix (`f"""..."""`) with no actual `{...}` interpolation left inside it (per the final review, `{theme.BG}` was removed but the `f` prefix and its resulting `{{`/`}}` escaping weren't cleaned up). Drop the `f` prefix and un-escape the braces if so.

- [ ] **Step 6: Run the full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` (3 times)
Expected: all passing, coverage ≥80%, no segfault. Also run `ruff check src/sixpack/ui/screens/chapter_select.py src/sixpack/ui/screens/detail_grid.py` and confirm the `F541` finding (and nothing new) — compare against the pre-Task-6 baseline to confirm you haven't introduced anything new, matching this project's established practice of a diff-based ruff check (see `docs/superpowers/plans/2026-08-20-home-cinematic-redesign.md`'s own history for this pattern) rather than requiring the whole file to be lint-clean.

- [ ] **Step 7: Commit**

```bash
git add src/sixpack/ui/screens/chapter_select.py src/sixpack/ui/screens/detail_grid.py
git commit -m "Fix stale async color race, empty-collection hero state, dead loading param, and comment accuracy"
```

---

## Self-Review

**Spec coverage:** All 3 Important findings from the final Phase B review addressed (Task 1-2 for the shell duplication, Task 3 for the cross-fade defeat, Task 4 for the hero-subtitle inconsistency, Task 5 for the missing arithmetic coverage). 5 of the 10 Minor findings addressed in Task 6 (the ones with clear, contained fixes); the remaining minors (alignment-pixel drift, chapter screen's backdrop visibility given opaque rows, encapsulation nits around `FocusGrid._items` access, `PlaylistDetailScreen.__init__`'s pass-through override) are cosmetic/stylistic enough to leave for a future pass rather than bundling into this cleanup — flagging this explicitly rather than silently dropping them. ✓

**Placeholder scan:** No TBDs. Where exact current-file content couldn't be pasted verbatim (Task 2's test-attribute-access updates, Task 5's `Chapter`/`_chapter_fraction` field-name confirmation), each step explicitly instructs reading the current file first and states what to verify, rather than leaving a vague instruction.

**Type consistency:** `HeroBackdrop(parent=None)`, `.backdrop`, `.set_title(str)`, `.set_subtitle(str)`, `.HERO_H` are defined once in Task 1 and consumed identically by `DetailGridScreen` (Task 2) and `ChapterSelectScreen` (Task 2) — no divergent naming introduced.
