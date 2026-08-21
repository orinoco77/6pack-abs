# Phase A: Remove Dead Screens Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove `LibraryScreen`, `SeriesScreen` (grid), and `PlaylistsScreen` (grid) — confirmed unreachable in the current app since the Kodi-style `BrowseScreen` (commit `e5002d6`) replaced their navigation flow — along with all `app.py` wiring and tests that only exist to exercise them.

**Architecture:** A single atomic removal: three screen files, their `app.py` construction/wiring/handlers, and the specific test blocks that only cover those three screens (test files are shared with screens that are staying, so this is targeted removal, not whole-file deletion).

**Tech Stack:** Python 3.12, PyQt6, pytest + pytest-qt (headless via `QT_QPA_PLATFORM=offscreen`).

**Spec:** `docs/superpowers/specs/2026-08-21-app-wide-cinematic-redesign-design.md` (Phase A section)

## Global Constraints

- Python ≥ 3.10 (dev/target uses 3.12). Line length 100 (ruff). `select = ["E","F","I","UP"]`.
- Coverage gate: `--cov-fail-under=80` must keep passing (pyproject `addopts`).
- All Qt tests run under `QT_QPA_PLATFORM=offscreen`.
- `_current_library` (an `app.py` instance attribute) is used by reachable code paths (Browse's library switching) as well as by the dead code being removed — only remove the specific dead-code *consumers*, never the attribute itself or its reachable uses.
- Commit after the task. Branch: `feature/app-wide-cinematic-redesign` (already created, based on current `main`).

---

## File Structure

| File | Change |
|------|--------|
| `src/sixpack/ui/screens/library.py` | Delete |
| `src/sixpack/ui/screens/series.py` | Delete |
| `src/sixpack/ui/screens/playlists.py` | Delete |
| `src/sixpack/ui/app.py` | Remove dead-screen construction, wiring, and handlers |
| `tests/test_ui/test_screens.py` | Remove `LibraryScreen` and `SeriesScreen` (grid) test blocks + their imports |
| `tests/test_ui/test_playlist_screens.py` | Remove `PlaylistsScreen` test block + its import + its dedicated fixtures |
| `tests/test_ui/test_widgets.py` | Remove `SeriesScreen` (grid) test block + its module docstring mention |

---

## Task 1: Remove the three dead screens and all references

**Files:**
- Delete: `src/sixpack/ui/screens/library.py`
- Delete: `src/sixpack/ui/screens/series.py`
- Delete: `src/sixpack/ui/screens/playlists.py`
- Modify: `src/sixpack/ui/app.py`
- Modify: `tests/test_ui/test_screens.py`
- Modify: `tests/test_ui/test_playlist_screens.py`
- Modify: `tests/test_ui/test_widgets.py`

**Interfaces:** None — pure removal, no new interfaces produced or consumed. `SeriesDetailScreen`, `PlaylistDetailScreen`, `ChapterSelectScreen`, `LoginScreen`, `SplashScreen`, and `BrowseScreen` (all staying, all reachable) are untouched by this task.

- [ ] **Step 1: Confirm current baseline passes**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`
Expected: all tests pass, coverage ≥80%. Record the pass count — you'll compare after removal.

- [ ] **Step 2: Delete the three dead screen files**

```bash
git rm src/sixpack/ui/screens/library.py
git rm src/sixpack/ui/screens/series.py
git rm src/sixpack/ui/screens/playlists.py
```

- [ ] **Step 3: Remove dead-screen wiring from `app.py`**

In `src/sixpack/ui/app.py`:

Remove these three import lines:
```python
from sixpack.ui.screens.library import LibraryScreen
from sixpack.ui.screens.series import SeriesScreen
from sixpack.ui.screens.playlists import PlaylistsScreen
```

Remove construction (in `__init__`, near the other screen constructions):
```python
        self._library_screen = LibraryScreen()
        self._series_screen = SeriesScreen(cover_cache=self._cover_cache)
        self._playlists_screen = PlaylistsScreen(cover_cache=self._cover_cache)
```

Remove stack registration:
```python
        self._stack.addWidget(self._library_screen)
        self._stack.addWidget(self._series_screen)
        self._stack.addWidget(self._playlists_screen)
```

Remove signal wiring:
```python
        self._library_screen.library_selected.connect(self._on_library_selected)
```
```python
        self._series_screen.back_requested.connect(self._show_libraries)
        self._series_screen.library_switch_requested.connect(self._on_library_selected)
        self._series_screen.view_switch_requested.connect(self._on_view_switch_requested)
```
```python
        self._playlists_screen.back_requested.connect(self._show_libraries)
        self._playlists_screen.library_switch_requested.connect(self._on_playlist_library_selected)
        self._playlists_screen.view_switch_requested.connect(self._on_view_switch_requested)
```

Remove these three navigation methods entirely:
```python
    def _show_libraries(self) -> None:
        self._stack.setCurrentWidget(self._library_screen)

    def _show_series(self) -> None:
        self._stack.setCurrentWidget(self._series_screen)

    def _show_playlists(self) -> None:
        self._stack.setCurrentWidget(self._playlists_screen)
```

Remove the `_on_view_switch_requested` handler entirely:
```python
    def _on_view_switch_requested(self, view_name: str) -> None:
        """Handle switching between Series and Playlists views."""
        if view_name == "playlists":
            # Switch to playlists view for current library
            lib = getattr(self, "_current_library", None)
            self._worker.run("playlists", self._async_get_playlists(lib.id if lib else None))
        elif view_name == "series":
            # Switch back to series view
            lib = getattr(self, "_current_library", None)
            if lib:
                self._worker.run("series_list", self._async_get_series(lib.id))
```

Remove the `_on_library_selected` method entirely (its only caller was `self._library_screen.library_selected`, just removed):
```python
    def _on_library_selected(self, library: Library) -> None:
        self._current_library = library
        server = self._config.active_server
        if server and server.last_library_id != library.id:
            server.last_library_id = library.id
            self._config.save()
        self._worker.run("series_list", self._async_get_series(library.id))
```

Remove the `_on_playlist_library_selected` method entirely (its only caller was `self._playlists_screen.library_switch_requested`, just removed) — read the surrounding lines in the actual file first (around what was line 399-410 before this edit) to get its exact current body, since line numbers will have shifted from earlier edits in this same task; remove the whole method.

In `_on_result`, remove the `"series_list"` and `"playlists"` branches entirely:
```python
        elif tag == "series_list":
            if hasattr(self, "_current_library"):
                self._series_screen.load(
                    self._current_library, result, self._server_url, self._token,
                    all_libraries=self._libraries,
                )
                self._show_series()

        elif tag == "playlists":
            self._playlists_screen.load(
                getattr(self, "_current_library", None), result, self._server_url, self._token,
                all_libraries=self._libraries,
            )
            self._show_playlists()
```

Do **not** remove `_current_library` itself, its other assignments, or its other reads — it's used by reachable Browse-related code elsewhere in the file (confirmed via `grep -n "_current_library" src/sixpack/ui/app.py` before this task — the occurrences NOT listed above must remain untouched).

- [ ] **Step 4: Remove the dead-screen test blocks from `tests/test_ui/test_screens.py`**

Remove these two import lines:
```python
from sixpack.ui.screens.library import LibraryScreen
from sixpack.ui.screens.series import SeriesScreen
```

Remove the entire `# ---- LibraryScreen ----` block — everything from that comment line up to (but not including) the following `# ---- SeriesDetailScreen ----` comment line. This includes the `_make_libraries()` helper and all `test_library_screen_*` functions.

Remove the entire `# ---- SeriesScreen library combo ----` block — everything from that comment line to the end of the file. This includes the `_make_three_libraries()` helper and all `test_series_screen_combo_*`/`test_series_screen_load_without_all_libraries` functions.

- [ ] **Step 5: Remove the dead-screen test block from `tests/test_ui/test_playlist_screens.py`**

Remove this import line:
```python
from sixpack.ui.screens.playlists import PlaylistsScreen
```

Remove the `_make_playlists()` and `_make_libraries()` helper functions (both defined under the `# ---- Fixtures ----` comment) — but **keep** `_make_item()`, which `PlaylistDetailScreen` tests (staying) also depend on.

Remove the entire `# ---- PlaylistsScreen ----` block — everything from that comment line up to (but not including) the following `# ---- PlaylistDetailScreen ----` comment line.

- [ ] **Step 6: Remove the dead-screen test block from `tests/test_ui/test_widgets.py`**

Update the module docstring from:
```python
"""Tests for FocusGrid, MediaCard, SeriesScreen, and PlayerScreen."""
```
to:
```python
"""Tests for FocusGrid, MediaCard, and PlayerScreen."""
```

Remove the entire `# SeriesScreen tests` block — everything from that comment line up to (but not including) the following `# PlayerScreen tests` comment line.

- [ ] **Step 7: Grep for anything missed**

Run:
```bash
grep -rn "LibraryScreen\|SeriesScreen\|PlaylistsScreen\|screens\.library\|screens\.series\b\|screens\.playlists\b" src/ tests/
```
Expected: no output. (Note: `screens.series_detail`, `screens.playlist_detail`, and identifiers like `PlaylistDetailScreen` must NOT match this pattern and are fine to still exist — if the grep flags any of those, your pattern is too broad, not a real hit.) If anything real turns up, remove it before continuing.

- [ ] **Step 8: Run the full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`
Expected: all tests pass (fewer than the Step 1 baseline — the removed test functions are gone), coverage ≥80%, no segfault. Run it 2-3 times given this codebase's history with Qt-level flakiness (this task doesn't touch any Qt effect/paint code, so risk is low, but verify anyway).

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "Remove dead LibraryScreen, SeriesScreen (grid), and PlaylistsScreen"
```

---

## Self-Review

**Spec coverage:** Phase A's spec section (removal of the three dead screens + their `app.py` wiring, verification via grep + full suite) is fully covered by this single task. ✓

**Placeholder scan:** No TBDs. The one instruction that isn't a literal before/after code block (`_on_playlist_library_selected` removal) explicitly tells the implementer to read the current file first rather than trusting stale line numbers — this is deliberate, not a placeholder, since earlier edits in the same task shift line numbers and pasting a possibly-stale exact body would be worse than pointing at the method by name with a clear instruction. ✓

**Type consistency:** N/A — no new interfaces introduced. ✓
