# Cinematic Home/Browse Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give SixPack's Home/Browse screen a "cinematic dark" look — layered palette, tactile focus glow, a blurred cover-art backdrop with a dominant-color fallback, and a reflective hero overlay — without changing the remote-navigation model.

**Architecture:** Five edited/new UI units plus a dev screenshot harness. `theme.py` gains palette/animation tokens. `cover_cache.py` gains dominant-color extraction and a blurred-backdrop variant. `media_card.py` gains an animated accent glow (focused) and dimming (unfocused). A new `backdrop.py` widget cross-fades between dominant-color gradients and blurred cover images. `browse.py` wires a backdrop layer + a non-focusable reflective hero + sidebar/icon polish into the existing screen, adding only calls at existing focus-change points.

**Tech Stack:** Python 3.12, PyQt6, pytest + pytest-qt (headless via `QT_QPA_PLATFORM=offscreen`), httpx/pydantic (data), disk-backed cover cache.

**Spec:** `docs/superpowers/specs/2026-08-20-home-cinematic-redesign-design.md`

## Global Constraints

- Python ≥ 3.10 (dev/target uses 3.12). Line length 100 (ruff). `select = ["E","F","I","UP"]`.
- Coverage gate: `--cov-fail-under=80` must keep passing (pyproject `addopts`).
- All Qt tests run under `QT_QPA_PLATFORM=offscreen`; new code must construct and behave correctly headless (effects/animations set up but never block; state changes are synchronous).
- Do NOT change `browse.py`'s navigation model: zones (`sidebar`/`rows`/`grid`), key handling, focus indices. Only add calls at existing focus-change points.
- Preserve existing public names/sizes in `theme.py` and `MediaCard` so current tests pass unchanged. In particular: `MediaCard.set_focused(True)` must still put `theme.ACCENT` in `self.styleSheet()`, and `set_focused(False)` must still put `"transparent"` there; card fixed size stays `CARD_WIDTH + 2*FOCUS_BORDER` × `CARD_HEIGHT`.
- Accent stays `#4a9eff`; add a glow variant, don't replace.
- The screenshot harness (`tools/shots.py`) is dev-only: not under `src/`, not packaged (wheel packages only `src/sixpack`), not counted toward coverage.
- Commit after each task. Branch: `feature/home-cinematic-redesign` (already created).

---

## File Structure

| File | Responsibility |
|------|----------------|
| `tools/shots.py` (new) | Dev-only offscreen renderer: build browse screen with real merton covers → 1920×1080 PNG. |
| `src/sixpack/ui/theme.py` (edit) | Palette elevations, bg/scrim gradients, glow color, focus/anim/backdrop tokens. |
| `src/sixpack/ui/cover_cache.py` (edit) | `dominant_color()`, `make_backdrop()`, `CoverCache.fetch_backdrop()`. |
| `src/sixpack/ui/widgets/media_card.py` (edit) | Animated accent glow (focused) + dim (unfocused) + type-aware placeholder. |
| `src/sixpack/ui/widgets/backdrop.py` (new) | Full-screen cross-fading backdrop (gradient ↔ blurred image). |
| `src/sixpack/ui/screens/browse.py` (edit) | Backdrop layer + reflective hero + sidebar icons/active bar + see-all chip. |
| `tests/test_ui/test_cover_cache.py` (edit) | Tests for dominant color + backdrop cache key/processing. |
| `tests/test_ui/test_widgets.py` (edit) | Tests for glow/dim focus + placeholder. |
| `tests/test_ui/test_backdrop.py` (new) | Tests for the backdrop widget. |
| `tests/test_ui/test_browse_screen.py` (edit) | Tests for hero reflection + sidebar icon/active state. |

---

## Task 1: Dev environment + screenshot harness

**Files:**
- Create: `tools/shots.py`
- Create: `tools/README.md`

**Interfaces:**
- Produces: a runnable command `python tools/shots.py <out_dir>` that writes `browse.png` rendered from real merton data using the token at `~/.config/sixpack/token`.

- [ ] **Step 1: Create the Python 3.12 environment and install the project**

```bash
brew install python@3.12 mpv        # mpv provides libmpv for python-mpv at runtime
/opt/homebrew/bin/python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[dev]"
```

- [ ] **Step 2: Verify the toolchain and full existing suite pass**

Run: `.venv/bin/python -m pytest -q`
Expected: all existing tests PASS, coverage ≥ 80%. (If `import mpv` fails, confirm `brew install mpv` succeeded and `mpv` is on PATH.)

- [ ] **Step 3: Write the screenshot harness**

Create `tools/shots.py`:

```python
"""Dev-only: render SixPack screens to PNG using real merton.home data.

Not packaged, not tested. Usage:
    .venv/bin/python tools/shots.py out/            # renders out/browse.png
Requires an ABS API token at ~/.config/sixpack/token and reachable merton.home.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QApplication

from sixpack.api.client import ABSClient
from sixpack.ui import theme
from sixpack.ui.cover_cache import CoverCache
from sixpack.ui.screens.browse import BrowseScreen, RowType

SERVER = "http://merton.home:13378"
SIZE = QSize(1920, 1080)


def _token() -> str:
    return (Path.home() / ".config" / "sixpack" / "token").read_text().strip()


async def _load(token: str):
    async with ABSClient(SERVER, token=token) as c:
        libs = await c.get_libraries()
        lib = next((l for l in libs if l.name == "Audiobooks"), libs[0])
        recent = await c.get_library_items_recent(lib.id, 20)
        series = await c.get_series(lib.id)
        playlists = await c.get_playlists(lib.id)
        shelves = await c.get_personalized_shelves(lib.id)
    cont = []
    for s in shelves:
        if "continue" in s.label.lower():
            cont = s.entities[:20]
            break
    return libs, {
        RowType.CONTINUE_LISTENING: cont,
        RowType.RECENTLY_ADDED: recent,
        RowType.SERIES: series[:20],
        RowType.PLAYLISTS: playlists[:20],
    }


def _grab(widget, path: Path) -> None:
    pix = QPixmap(SIZE)
    pix.fill(Qt.GlobalColor.black)
    widget.render(pix)
    pix.save(str(path), "PNG")


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "out")
    out.mkdir(parents=True, exist_ok=True)
    token = _token()

    app = QApplication(sys.argv)
    theme.apply(app)
    loop = asyncio.new_event_loop()
    libs, rows = loop.run_until_complete(_load(token))

    cache = CoverCache()
    screen = BrowseScreen(cover_cache=cache)
    screen.resize(SIZE)
    screen.load_libraries(libs, SERVER, token)
    for rt, items in rows.items():
        screen.set_row_items(rt, items)
    screen.show_content()
    screen.show()

    # Let cover downloads + focus effects settle, then grab.
    app.processEvents()
    loop.run_until_complete(asyncio.sleep(2.0))
    app.processEvents()
    _grab(screen, out / "browse.png")
    print(f"wrote {out / 'browse.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Create `tools/README.md`**

```markdown
# tools/ (dev-only)

`shots.py` renders SixPack screens to PNG using real data from merton.home for
visual iteration. Not shipped in the package, not covered by tests.

    .venv/bin/python tools/shots.py out/

Requires an ABS API token at `~/.config/sixpack/token`.
```

- [ ] **Step 5: Capture "before" screenshots**

Run: `.venv/bin/python tools/shots.py out/before`
Expected: `out/before/browse.png` exists and shows the current flat browse screen with real covers. Open and eyeball it as the baseline.

- [ ] **Step 6: Commit**

```bash
git add tools/ .gitignore
git commit -m "Add dev screenshot harness for visual iteration"
```
(Ensure `out/` is git-ignored — add `out/` to `.gitignore` in this commit.)

---

## Task 2: theme.py palette & tokens

**Files:**
- Modify: `src/sixpack/ui/theme.py`
- Test: `tests/test_ui/test_theme.py` (new)

**Interfaces:**
- Produces new module constants (all `str` unless noted):
  - `SURFACE_LOW = "#151515"`, keeps `SURFACE`, `SURFACE_HIGH`.
  - `ACCENT_GLOW = "#4a9eff"` (glow color; same hue as accent).
  - `BACKDROP_W = 1920`, `BACKDROP_H = 1080` (int).
  - `BACKDROP_SCRIM_TOP = "#00000000"`, `BACKDROP_SCRIM_BOTTOM = "#e6000000"` (ARGB hex for gradient).
  - `BACKDROP_DARKEN = 0.45` (float; 0–1 fraction of black overlaid on the blurred image).
  - `FOCUS_GLOW_RADIUS = 28` (int, px), `FOCUS_ANIM_MS = 130` (int), `UNFOCUSED_OPACITY = 0.55` (float).
  - `GRADIENT_BG` (str) — a `qlineargradient(...)` fragment used as the window background.

- [ ] **Step 1: Write the failing test**

Create `tests/test_ui/test_theme.py`:

```python
from sixpack.ui import theme


def test_new_tokens_exist():
    assert theme.SURFACE_LOW.startswith("#")
    assert theme.ACCENT_GLOW.startswith("#")
    assert isinstance(theme.BACKDROP_W, int) and theme.BACKDROP_W > 0
    assert isinstance(theme.BACKDROP_H, int) and theme.BACKDROP_H > 0
    assert isinstance(theme.FOCUS_GLOW_RADIUS, int)
    assert isinstance(theme.FOCUS_ANIM_MS, int)
    assert 0.0 < theme.UNFOCUSED_OPACITY <= 1.0
    assert 0.0 <= theme.BACKDROP_DARKEN <= 1.0


def test_accent_unchanged():
    assert theme.ACCENT == "#4a9eff"


def test_stylesheet_builds():
    # STYLESHEET is an f-string; referencing any missing token would raise at import.
    assert "QWidget" in theme.STYLESHEET
    assert theme.SURFACE_LOW in theme.STYLESHEET or theme.GRADIENT_BG in theme.STYLESHEET
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_ui/test_theme.py -v`
Expected: FAIL — `AttributeError: module 'sixpack.ui.theme' has no attribute 'SURFACE_LOW'`.

- [ ] **Step 3: Add the tokens and use the gradient background**

In `src/sixpack/ui/theme.py`, after the existing colour palette block, add:

```python
SURFACE_LOW = "#151515"
ACCENT_GLOW = "#4a9eff"

# Cinematic backdrop
BACKDROP_W = 1920
BACKDROP_H = 1080
BACKDROP_DARKEN = 0.45           # fraction of black overlaid on blurred cover
BACKDROP_SCRIM_TOP = "#00000000"     # transparent
BACKDROP_SCRIM_BOTTOM = "#e6000000"  # near-opaque black at the bottom

# Focus feedback
FOCUS_GLOW_RADIUS = 28
FOCUS_ANIM_MS = 130
UNFOCUSED_OPACITY = 0.55

# Subtle top→bottom window gradient (used as the base background)
GRADIENT_BG = (
    f"qlineargradient(x1:0, y1:0, x2:0, y2:1, "
    f"stop:0 {SURFACE_LOW}, stop:1 {BG})"
)
```

Then change the `QWidget` rule at the top of `STYLESHEET` from
`background-color: {BG};` to `background-color: {BG};` unchanged for generic
widgets, but add a dedicated top-level rule so the window uses the gradient:

```python
QMainWindow, #screen_root {{
    background: {GRADIENT_BG};
}}
```

(Insert this block right after the `QWidget {{ ... }}` block. Widgets that need the gradient set `objectName("screen_root")`; browse will use it in Task 6.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_ui/test_theme.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite (no regressions)**

Run: `.venv/bin/python -m pytest -q`
Expected: all PASS, coverage ≥ 80%.

- [ ] **Step 6: Commit**

```bash
git add src/sixpack/ui/theme.py tests/test_ui/test_theme.py
git commit -m "Add cinematic palette, gradient, glow and focus tokens to theme"
```

---

## Task 3: cover_cache — dominant color + blurred backdrop

**Files:**
- Modify: `src/sixpack/ui/cover_cache.py`
- Test: `tests/test_ui/test_cover_cache.py`

**Interfaces:**
- Produces:
  - `dominant_color(pixmap: QPixmap) -> QColor` — module-level; average color of the image (downscale-to-1px). Returns `QColor(theme.SURFACE_HIGH)` for a null pixmap.
  - `make_backdrop(pixmap: QPixmap, size: QSize) -> QPixmap` — module-level; scale-to-fill `size`, box-blur (downscale/upscale), darken by `theme.BACKDROP_DARKEN`, apply vertical scrim. Never returns null for a non-null input.
  - `CoverCache.fetch_backdrop(self, url: str, token: str, callback: Callable[[QPixmap], None]) -> None` — delivers a processed backdrop pixmap (sized `theme.BACKDROP_W×BACKDROP_H`), cached on disk under a key distinct from the raw cover; reuses `fetch()` for the raw download.
  - `CoverCache._backdrop_path(self, url: str) -> Path` — distinct from `_cache_path(url)`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_ui/test_cover_cache.py`:

```python
from PyQt6.QtCore import QSize
from PyQt6.QtGui import QColor, QPixmap

from sixpack.ui.cover_cache import CoverCache, dominant_color, make_backdrop


def _solid(w, h, color) -> QPixmap:
    pix = QPixmap(w, h)
    pix.fill(color)
    return pix


def test_dominant_color_of_solid_red():
    c = dominant_color(_solid(64, 64, QColor(200, 30, 30)))
    assert c.red() > 150 and c.green() < 80 and c.blue() < 80


def test_dominant_color_null_pixmap_is_safe():
    c = dominant_color(QPixmap())
    assert isinstance(c, QColor) and c.isValid()


def test_make_backdrop_returns_sized_non_null():
    out = make_backdrop(_solid(300, 300, QColor(120, 60, 200)), QSize(640, 360))
    assert not out.isNull()
    assert out.width() == 640 and out.height() == 360


def test_backdrop_path_distinct_from_cover_path(tmp_path):
    cache = CoverCache(cache_dir=tmp_path)
    url = "http://abs.test/api/items/x/cover?token=t"
    assert cache._backdrop_path(url) != cache._cache_path(url)


def test_fetch_backdrop_uses_disk_cache(tmp_path, qtbot):
    cache = CoverCache(cache_dir=tmp_path)
    url = "http://abs.test/api/items/x/cover?token=t"
    # Pre-seed the backdrop cache file so no network is needed.
    make_backdrop(_solid(300, 300, QColor(10, 120, 90)), QSize(64, 36)).save(
        str(cache._backdrop_path(url)), "PNG"
    )
    got = {}
    cache.fetch_backdrop(url, "t", lambda pm: got.setdefault("pm", pm))
    assert "pm" in got and not got["pm"].isNull()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_ui/test_cover_cache.py -v -k "dominant or backdrop"`
Expected: FAIL — `ImportError: cannot import name 'dominant_color'`.

- [ ] **Step 3: Implement the functions**

In `src/sixpack/ui/cover_cache.py`, add imports and functions:

```python
from PyQt6.QtCore import QObject, QUrl, QSize, Qt
from PyQt6.QtGui import QPixmap, QColor, QPainter, QLinearGradient, QBrush

from sixpack.ui import theme


def dominant_color(pixmap: QPixmap) -> QColor:
    """Average colour of the image, via a 1x1 smooth downscale."""
    if pixmap.isNull():
        return QColor(theme.SURFACE_HIGH)
    small = pixmap.scaled(
        1, 1, Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    return QColor(small.toImage().pixel(0, 0))


def make_backdrop(pixmap: QPixmap, size: QSize) -> QPixmap:
    """Scale-to-fill, cheap box blur, darken, and apply a bottom scrim."""
    filled = pixmap.scaled(
        size, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    # Crop the overspill to exactly `size`.
    x = max(0, (filled.width() - size.width()) // 2)
    y = max(0, (filled.height() - size.height()) // 2)
    filled = filled.copy(x, y, size.width(), size.height())
    # Cheap blur: downscale then upscale smoothly.
    small = filled.scaled(
        max(1, size.width() // 16), max(1, size.height() // 16),
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    blurred = small.scaled(
        size, Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    painter = QPainter(blurred)
    # Darken.
    painter.fillRect(
        blurred.rect(),
        QColor(0, 0, 0, int(255 * theme.BACKDROP_DARKEN)),
    )
    # Bottom scrim so text/cards stay legible.
    grad = QLinearGradient(0, 0, 0, size.height())
    grad.setColorAt(0.0, QColor(theme.BACKDROP_SCRIM_TOP))
    grad.setColorAt(1.0, QColor(theme.BACKDROP_SCRIM_BOTTOM))
    painter.fillRect(blurred.rect(), QBrush(grad))
    painter.end()
    return blurred
```

Note: `QColor("#aarrggbb")` parses 8-digit ARGB in Qt6, so `BACKDROP_SCRIM_*` work directly.

Add the cache methods inside `CoverCache`:

```python
    def _backdrop_path(self, url: str) -> Path:
        return self._cache_dir / hashlib.md5(("backdrop:" + url).encode()).hexdigest()

    def fetch_backdrop(self, url: str, token: str, callback) -> None:
        bpath = self._backdrop_path(url)
        if bpath.exists():
            pix = QPixmap()
            if pix.load(str(bpath)) and not pix.isNull():
                callback(pix)
                return
            bpath.unlink(missing_ok=True)

        size = QSize(theme.BACKDROP_W, theme.BACKDROP_H)

        def _process(raw: QPixmap) -> None:
            out = make_backdrop(raw, size)
            out.save(str(bpath), "PNG")
            callback(out)

        # Reuse the raw-cover fetch (caches raw on disk, coalesces in-flight).
        self.fetch(url, token, _process)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_ui/test_cover_cache.py -v`
Expected: PASS (existing cover_cache tests included).

- [ ] **Step 5: Commit**

```bash
git add src/sixpack/ui/cover_cache.py tests/test_ui/test_cover_cache.py
git commit -m "Add dominant-color and blurred-backdrop support to CoverCache"
```

---

## Task 4: media_card — animated glow + dim + placeholder

**Files:**
- Modify: `src/sixpack/ui/widgets/media_card.py`
- Test: `tests/test_ui/test_widgets.py`

**Interfaces:**
- Consumes: `theme.ACCENT_GLOW`, `theme.FOCUS_GLOW_RADIUS`, `theme.FOCUS_ANIM_MS`, `theme.UNFOCUSED_OPACITY`.
- Produces (behavioural, same public API):
  - `MediaCard(title, subtitle="", meta="", media_type="book", parent=None)` — new optional `media_type` param; back-compatible.
  - `set_focused(True)` still puts `theme.ACCENT` in `styleSheet()`, installs a `QGraphicsDropShadowEffect` (accent glow) on the card, and animates its `blurRadius` 0→`FOCUS_GLOW_RADIUS`.
  - `set_focused(False)` still puts `"transparent"` in `styleSheet()` and installs a `QGraphicsOpacityEffect` at `UNFOCUSED_OPACITY`.
  - Placeholder glyph depends on `media_type` (`book`→`📖`, `podcast`→`🎙`, else `♪`).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_ui/test_widgets.py` (MediaCard section):

```python
def test_media_card_media_type_param(qtbot):
    card = MediaCard(title="Pod", media_type="podcast")
    qtbot.addWidget(card)
    assert card._media_type == "podcast"


def test_media_card_focus_installs_glow(qtbot):
    from PyQt6.QtWidgets import QGraphicsDropShadowEffect
    card = MediaCard(title="Test")
    qtbot.addWidget(card)
    card.set_focused(True)
    eff = card.graphicsEffect()
    assert isinstance(eff, QGraphicsDropShadowEffect)


def test_media_card_unfocus_installs_dim(qtbot):
    from PyQt6.QtWidgets import QGraphicsOpacityEffect
    card = MediaCard(title="Test")
    qtbot.addWidget(card)
    card.set_focused(True)
    card.set_focused(False)
    eff = card.graphicsEffect()
    assert isinstance(eff, QGraphicsOpacityEffect)
    assert abs(eff.opacity() - __import__("sixpack.ui.theme", fromlist=["x"]).UNFOCUSED_OPACITY) < 1e-6
```

(The existing `test_media_card_set_focused_style` must still pass — do not remove the stylesheet border logic.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_ui/test_widgets.py -v -k "media_type or glow or dim"`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'media_type'` / missing effects.

- [ ] **Step 3: Implement**

In `media_card.py`, update imports:

```python
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QPropertyAnimation
from PyQt6.QtGui import QPixmap, QPainter, QColor, QFont
from PyQt6.QtWidgets import (
    QFrame, QLabel, QVBoxLayout, QGraphicsDropShadowEffect, QGraphicsOpacityEffect,
)
```

Add `media_type` to `__init__`:

```python
    def __init__(self, title, subtitle="", meta="", media_type="book", parent=None):
        super().__init__(parent)
        ...
        self._media_type = media_type
        self._glow_anim: QPropertyAnimation | None = None
        ...
```

Make the placeholder type-aware:

```python
    _PLACEHOLDER_GLYPH = {"book": "📖", "podcast": "🎙"}

    def _render_placeholder(self) -> None:
        pix = QPixmap(theme.CARD_WIDTH, theme.CARD_ART_HEIGHT)
        pix.fill(QColor(theme.SURFACE_HIGH))
        painter = QPainter(pix)
        painter.setPen(QColor(theme.TEXT_MUTED))
        font = QFont()
        font.setPointSize(32)
        painter.setFont(font)
        glyph = self._PLACEHOLDER_GLYPH.get(self._media_type, "♪")
        painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, glyph)
        painter.end()
        self._art_label.setPixmap(pix)
```

Replace `set_focused`:

```python
    def set_focused(self, focused: bool) -> None:
        self._focused = focused
        border = theme.ACCENT if focused else "transparent"
        self.setStyleSheet(
            f"#media_card {{ border-radius: {theme.CARD_RADIUS}px; "
            f"border: {theme.FOCUS_BORDER}px solid {border}; }}"
        )
        if focused:
            glow = QGraphicsDropShadowEffect(self)
            glow.setColor(QColor(theme.ACCENT_GLOW))
            glow.setOffset(0, 0)
            glow.setBlurRadius(0)
            self.setGraphicsEffect(glow)
            anim = QPropertyAnimation(glow, b"blurRadius", self)
            anim.setDuration(theme.FOCUS_ANIM_MS)
            anim.setStartValue(0)
            anim.setEndValue(theme.FOCUS_GLOW_RADIUS)
            anim.start()
            self._glow_anim = anim  # keep a ref so it isn't GC'd mid-animation
        else:
            self._glow_anim = None
            dim = QGraphicsOpacityEffect(self)
            dim.setOpacity(theme.UNFOCUSED_OPACITY)
            self.setGraphicsEffect(dim)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_ui/test_widgets.py -v`
Expected: PASS (including the unchanged `test_media_card_set_focused_style` and `test_media_card_fixed_size`).

- [ ] **Step 5: Commit**

```bash
git add src/sixpack/ui/widgets/media_card.py tests/test_ui/test_widgets.py
git commit -m "Add animated accent glow, sibling dimming and type-aware placeholder to MediaCard"
```

---

## Task 5: backdrop.py — cross-fading backdrop widget

**Files:**
- Create: `src/sixpack/ui/widgets/backdrop.py`
- Test: `tests/test_ui/test_backdrop.py` (new)

**Interfaces:**
- Consumes: `theme` tokens.
- Produces:
  - `class Backdrop(QWidget)`.
  - `show_color(self, color: QColor) -> None` — paint an instant radial/linear gradient from `color` (fallback / pre-blur state).
  - `show_image(self, pixmap: QPixmap) -> None` — cross-fade from the current layer to `pixmap` over ~200ms.
  - Internal `_current_key` guard so repeated calls for the same target are no-ops (avoids redundant fades). Uses `QColor`/`QPixmap` only; owns no navigation state.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ui/test_backdrop.py`:

```python
from PyQt6.QtGui import QColor, QPixmap
from sixpack.ui.widgets.backdrop import Backdrop


def test_backdrop_creates(qtbot):
    b = Backdrop()
    qtbot.addWidget(b)
    assert b.width() >= 0


def test_backdrop_show_color_no_crash(qtbot):
    b = Backdrop()
    qtbot.addWidget(b)
    b.resize(640, 360)
    b.show_color(QColor(40, 80, 160))  # must not raise


def test_backdrop_show_image_sets_pixmap(qtbot):
    b = Backdrop()
    qtbot.addWidget(b)
    b.resize(640, 360)
    pix = QPixmap(640, 360)
    pix.fill(QColor(10, 10, 10))
    b.show_image(pix)
    assert b._top.pixmap() is not None and not b._top.pixmap().isNull()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_ui/test_backdrop.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sixpack.ui.widgets.backdrop'`.

- [ ] **Step 3: Implement the widget**

Create `src/sixpack/ui/widgets/backdrop.py`:

```python
"""Full-screen cinematic backdrop: cross-fades gradient ↔ blurred cover."""
from __future__ import annotations

from PyQt6.QtCore import Qt, QPropertyAnimation
from PyQt6.QtGui import QColor, QPixmap, QPainter, QLinearGradient, QBrush
from PyQt6.QtWidgets import QLabel, QWidget, QGraphicsOpacityEffect

from sixpack.ui import theme

_FADE_MS = 200


class Backdrop(QWidget):
    """Two stacked full-bleed layers; new content fades in over the old."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._base = QLabel(self)   # gradient / outgoing
        self._top = QLabel(self)    # incoming image
        for lbl in (self._base, self._top):
            lbl.setScaledContents(True)
        self._top_effect = QGraphicsOpacityEffect(self._top)
        self._top_effect.setOpacity(0.0)
        self._top.setGraphicsEffect(self._top_effect)
        self._anim: QPropertyAnimation | None = None
        self._current_key: str = ""

    def resizeEvent(self, event) -> None:
        for lbl in (self._base, self._top):
            lbl.setGeometry(self.rect())
        super().resizeEvent(event)

    def show_color(self, color: QColor) -> None:
        pix = QPixmap(max(1, self.width()), max(1, self.height()))
        grad = QLinearGradient(0, 0, 0, pix.height())
        grad.setColorAt(0.0, color.darker(150))
        grad.setColorAt(1.0, QColor(theme.BG))
        painter = QPainter(pix)
        painter.fillRect(pix.rect(), QBrush(grad))
        painter.end()
        self._base.setPixmap(pix)
        self._top_effect.setOpacity(0.0)

    def show_image(self, pixmap: QPixmap) -> None:
        # Move whatever is currently on top down to base, then fade the new in.
        if self._top.pixmap() is not None and not self._top.pixmap().isNull():
            self._base.setPixmap(self._top.pixmap())
        self._top.setPixmap(pixmap)
        anim = QPropertyAnimation(self._top_effect, b"opacity", self)
        anim.setDuration(_FADE_MS)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.start()
        self._anim = anim  # keep ref
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_ui/test_backdrop.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/sixpack/ui/widgets/backdrop.py tests/test_ui/test_backdrop.py
git commit -m "Add cross-fading cinematic Backdrop widget"
```

---

## Task 6: browse.py — backdrop + reflective hero + sidebar/icon polish

**Files:**
- Modify: `src/sixpack/ui/screens/browse.py`
- Test: `tests/test_ui/test_browse_screen.py`

**Interfaces:**
- Consumes: `Backdrop` (Task 5), `dominant_color`/`fetch_backdrop` (Task 3), `theme` tokens.
- Produces (new, on `BrowseScreen`):
  - `_reflect_focus(self, item) -> None` — sets hero `title`/`subtitle` labels from `item.title` / `item.subtitle` (empty strings if `item is None`); triggers backdrop update via the focused item's `cover_url`.
  - `_current_focused_item(self) -> object | None` — returns the item currently under focus for the active zone (`rows` → focused card in focused row; `grid` → focused grid item; `sidebar` → top item of first non-empty row, or None).
  - `_reflect_current(self) -> None` — convenience: `_reflect_focus(self._current_focused_item())`.
  - Hero labels `self._hero_title`, `self._hero_sub`; icon-bearing `_SidebarItem`.
- Navigation model unchanged: `_reflect_current()` is only *called* from existing focus-move points.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_ui/test_browse_screen.py`:

```python
def test_hero_reflects_library_item(qtbot):
    screen = BrowseScreen(row_types=list(DEFAULT_ROW_TYPES))
    qtbot.addWidget(screen)
    item = _li("i1", "The Sandman", author="Neil Gaiman")
    screen._reflect_focus(item)
    assert screen._hero_title.text() == "The Sandman"
    assert "Neil Gaiman" in screen._hero_sub.text()


def test_hero_reflects_series(qtbot):
    screen = BrowseScreen(row_types=list(DEFAULT_ROW_TYPES))
    qtbot.addWidget(screen)
    s = _series("s1", "Discworld", n_books=3)
    screen._reflect_focus(s)
    assert screen._hero_title.text() == "Discworld"
    assert "3 books" in screen._hero_sub.text()


def test_hero_clears_on_none(qtbot):
    screen = BrowseScreen(row_types=list(DEFAULT_ROW_TYPES))
    qtbot.addWidget(screen)
    screen._reflect_focus(None)
    assert screen._hero_title.text() == ""
    assert screen._hero_sub.text() == ""


def test_row_focus_updates_hero(qtbot):
    screen = BrowseScreen(row_types=list(DEFAULT_ROW_TYPES))
    qtbot.addWidget(screen)
    screen.load_libraries([_lib("lib1", "Audiobooks")], "http://abs.test", "t")
    screen.set_row_items(RowType.RECENTLY_ADDED, [_li("i1", "Book One"), _li("i2", "Book Two")])
    screen.show_content()
    screen._enter_rows()
    # focused row defaults to 0 (Continue Listening, empty) — move down to Recently Added
    screen._handle_rows(__import__("sixpack.input.actions", fromlist=["InputAction"]).InputAction.DOWN)
    assert screen._hero_title.text() in ("Book One", "Book Two", "")  # reflects focused card


def test_sidebar_item_has_icon_and_active_state(qtbot):
    from sixpack.ui.screens.browse import _SidebarItem
    item = _SidebarItem("Podcasts", media_type="podcast")
    qtbot.addWidget(item)
    item.set_state(selected=True, zone_active=True)
    assert item._icon.text() != ""  # an icon glyph is shown
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_ui/test_browse_screen.py -v -k "hero or sidebar_item_has_icon"`
Expected: FAIL — `AttributeError: 'BrowseScreen' object has no attribute '_reflect_focus'` / `_SidebarItem` has no `media_type`.

- [ ] **Step 3: Add the backdrop + hero to construction**

In `browse.py` imports add:

```python
from PyQt6.QtWidgets import QGraphicsOpacityEffect  # (if needed)
from sixpack.ui.cover_cache import CoverCache, dominant_color
from sixpack.ui.widgets.backdrop import Backdrop
```

In `_build_ui`, give the root an object name and add a backdrop child behind everything:

```python
    def _build_ui(self) -> None:
        self.setObjectName("screen_root")
        self._backdrop = Backdrop(self)
        self._backdrop.lower()
        self._dom_colors: dict[str, QColor] = {}

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_sidebar())
        root.addWidget(self._build_content(), stretch=1)
        self._build_hero()   # overlay child on the content pane

    def resizeEvent(self, event):
        self._backdrop.setGeometry(self.rect())
        if hasattr(self, "_hero"):
            self._hero.setGeometry(self._hero_geometry())
        super().resizeEvent(event)
```

Make the sidebar semi-transparent so the backdrop shows through: in `_build_sidebar` change
`sidebar.setStyleSheet(f"background-color: {theme.SURFACE};")` to
`sidebar.setStyleSheet(f"background-color: rgba(21,21,21,200);")`.

Add the hero builder and geometry helper:

```python
    _HERO_H = 150

    def _build_hero(self) -> None:
        self._hero = QWidget(self)
        self._hero.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
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

    def _hero_geometry(self):
        from PyQt6.QtCore import QRect
        return QRect(_SIDEBAR_W, 0, max(0, self.width() - _SIDEBAR_W), self._HERO_H)
```

Push the rows down so they don't sit under the hero: in `_build_content`, change the rows page `rows_layout.setContentsMargins(32, 24, 32, 24)` to `rows_layout.setContentsMargins(32, self._HERO_H, 32, 24)`.

- [ ] **Step 4: Implement hero reflection + focus wiring**

Add methods to `BrowseScreen`:

```python
    def _reflect_focus(self, item) -> None:
        title = getattr(item, "title", "") if item is not None else ""
        sub = getattr(item, "subtitle", "") if item is not None else ""
        self._hero_title.setText(title or "")
        self._hero_sub.setText(sub or "")
        if item is None or self._cover_cache is None:
            return
        cover = item.cover_url(self._server_url, self._token) if callable(
            getattr(item, "cover_url", None)
        ) else None
        if not cover:
            return
        key = getattr(item, "id", "") or cover
        color = self._dom_colors.get(key)
        if color is not None:
            self._backdrop.show_color(color)
        self._cover_cache.fetch_backdrop(
            cover, self._token, self._backdrop.show_image
        )

    def _current_focused_item(self):
        if self._zone == "grid":
            if self._grid_items and 0 <= self._grid_focus_idx < len(self._grid_items):
                return self._grid_items[self._grid_focus_idx]
            return None
        if self._zone == "rows":
            items = self._row_items[self._focused_row]
            idx = self._row_item_idxs[self._focused_row]
            if items and 0 <= idx < len(items):
                return items[idx]
            return None
        # sidebar zone: preview the first item of the first non-empty row
        for items in self._row_items:
            if items:
                return items[0]
        return None

    def _reflect_current(self) -> None:
        self._reflect_focus(self._current_focused_item())
```

Record dominant colors when covers arrive: in `_populate_row` and `populate_grid` and `_enter_grid`, where a card is created with a cover, wrap the callback. Replace:

```python
            if cover and self._cover_cache is not None:
                self._cover_cache.fetch(cover, self._token, card.set_cover)
```

with a helper call:

```python
            if cover and self._cover_cache is not None:
                self._fetch_cover(card, cover, getattr(item, "id", "") or cover)
```

and add:

```python
    def _fetch_cover(self, card, cover_url: str, key: str) -> None:
        def _cb(pm):
            card.set_cover(pm)
            if key not in self._dom_colors:
                self._dom_colors[key] = dominant_color(pm)
        self._cover_cache.fetch(cover_url, self._token, _cb)
```

Now add `self._reflect_current()` calls at the END of each existing focus-move branch (no other logic changes):
- in `_handle_rows`: after each `focus_card(...)` / row change / `_enter_sidebar()` path, and after `_set_see_all_focused(True)`.
- in `_enter_rows`: after focusing the card.
- in `_set_grid_focus`: at the end.
- in `_enter_sidebar`: at the end (will preview first row item).

The simplest robust approach: call `self._reflect_current()` as the last line of `_handle_rows`, `_handle_grid`, `_enter_rows`, `_enter_sidebar`, and `_set_grid_focus`. These are all already-existing methods; adding a trailing call does not alter navigation.

- [ ] **Step 5: Add icons + active bar to the sidebar**

Replace `_SidebarItem` with an icon-bearing version:

```python
_LIB_ICONS = {"book": "📚", "podcast": "🎙", "ebook": "📖"}


class _SidebarItem(QWidget):
    def __init__(self, text: str, media_type: str = "book", parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 12, 20, 12)
        layout.setSpacing(10)
        self._icon = QLabel(_LIB_ICONS.get(media_type, "📚"))
        self._icon.setStyleSheet("background: transparent;")
        self._label = QLabel(text)
        self._label.setStyleSheet("background: transparent;")
        layout.addWidget(self._icon)
        layout.addWidget(self._label)
        layout.addStretch()
        self.set_state(selected=False, zone_active=False)

    def set_state(self, *, selected: bool, zone_active: bool) -> None:
        if selected and zone_active:
            bg, fg, bar = theme.ACCENT, theme.TEXT_PRIMARY, theme.ACCENT
        elif selected:
            bg, fg, bar = theme.SURFACE_HIGH, theme.ACCENT, theme.ACCENT
        else:
            bg, fg, bar = "transparent", theme.TEXT_SECONDARY, "transparent"
        self.setStyleSheet(
            f"QWidget {{ background-color: {bg}; border-radius: 4px; "
            f"border-left: 3px solid {bar}; }}"
        )
        self._label.setStyleSheet(
            f"color: {fg}; font-size: {theme.FONT_BODY}pt; background: transparent; border: none;"
        )
        self._icon.setStyleSheet("background: transparent; border: none;")
```

Update `_rebuild_sidebar` to pass the media type:

```python
        for lib in self._libraries:
            item = _SidebarItem(lib.name, media_type=getattr(lib, "media_type", "book"))
            self._sidebar_items.append(item)
            self._sidebar_items_layout.addWidget(item)
```

Style the `See all` label as a chip when idle too (in `_RowWidget._refresh_see_all_style`, the unfocused branch): give it a subtle rounded background:

```python
        else:
            self._see_all.setStyleSheet(
                f"color: {theme.TEXT_SECONDARY}; background-color: {theme.SURFACE_HIGH}; "
                f"font-size: {theme.FONT_META}pt; border-radius: 4px; padding: 2px 8px;"
            )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_ui/test_browse_screen.py -v`
Expected: PASS (new hero/sidebar tests + all existing browse tests).

- [ ] **Step 7: Run the full suite + coverage**

Run: `.venv/bin/python -m pytest -q`
Expected: all PASS, coverage ≥ 80%.

- [ ] **Step 8: Commit**

```bash
git add src/sixpack/ui/screens/browse.py tests/test_ui/test_browse_screen.py
git commit -m "Add cinematic backdrop, reflective hero and sidebar polish to browse"
```

---

## Task 7: Visual verification + iteration

**Files:** none (verification only; small follow-up commits allowed for tuning `theme.py`/`browse.py` values).

- [ ] **Step 1: Capture "after" screenshots**

Run: `.venv/bin/python tools/shots.py out/after`
Expected: `out/after/browse.png` exists.

- [ ] **Step 2: Compare before/after and eyeball at 10ft scale**

Open `out/before/browse.png` and `out/after/browse.png`. Check: backdrop reads as depth without hurting legibility; focused card clearly "pops" via glow; hero title/author legible top-left; sidebar active item has accent bar + icon; nothing clipped at 1920×1080.

- [ ] **Step 3: Tune if needed**

If the backdrop is too strong/weak, adjust `theme.BACKDROP_DARKEN` / scrim; if glow is too subtle, adjust `FOCUS_GLOW_RADIUS`. Re-run `tools/shots.py` after each change. Commit tuning separately:

```bash
git add src/sixpack/ui/theme.py
git commit -m "Tune backdrop darkness and focus glow after visual review"
```

- [ ] **Step 4: Final full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all PASS, coverage ≥ 80%.

- [ ] **Step 5: Hand back to user with before/after PNGs for sign-off before merge.**

---

## Self-Review

**Spec coverage:**
- Layered palette & tokens → Task 2. ✓
- Tactile focus (glow + dim) → Task 4. ✓ (literal scale intentionally replaced by glow+dim per the fixed-size test constraint; noted in Global Constraints.)
- Blurred backdrop + dominant-color fallback → Tasks 3 (processing) + 5 (widget) + 6 (wiring). ✓
- Reflective non-focusable hero → Task 6 (`_reflect_focus`, `_build_hero`). ✓
- Sidebar/icon/see-all polish → Task 6. ✓
- Dev screenshot harness → Task 1. ✓
- Existing tests keep passing / coverage gate → asserted in Tasks 1–7. ✓
- Navigation model unchanged → Task 6 adds only trailing `_reflect_current()` calls. ✓
- Non-goal (no progress in hero) → hero uses only `.title`/`.subtitle`; no progress fetch added. ✓

**Placeholder scan:** No TBD/TODO; every code step has concrete code. ✓

**Type consistency:** `dominant_color`/`make_backdrop`/`fetch_backdrop`/`_backdrop_path` names match across Tasks 3 and 6; `Backdrop.show_color`/`show_image` match across Tasks 5 and 6; `_SidebarItem(text, media_type=...)` matches its test and `_rebuild_sidebar` call; `MediaCard(..., media_type=...)` optional and back-compatible with existing callers. ✓
