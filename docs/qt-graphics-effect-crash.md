# Why this codebase never uses `QGraphicsEffect`

If you're reading this because you want to add a drop shadow, opacity fade,
blur, or other `QGraphicsEffect` subclass somewhere in `src/sixpack/ui/` —
don't. Use a plain `QWidget` with a custom `paintEvent` instead. This file
explains why, so the rule doesn't look arbitrary.

## The bug

PyQt6 6.11.0 / Qt 6.11.1, on this project's `QT_QPA_PLATFORM=offscreen`
test setup (and suspected, though not confirmed with equal certainty, on
real displays too): installing a `QGraphicsEffect` subclass
(`QGraphicsDropShadowEffect`, `QGraphicsOpacityEffect`) on a widget and
compositing it — especially at fractional opacity, and especially across
many distinct widget instances being created/painted/destroyed within one
process — segfaults inside Qt's own C++ code. Root-caused via `lldb`
backtraces (not guessed at): the fault is deep inside
`QGraphicsEffectSource::pixmap()` → `QWidget::render()`, the re-entrant
machinery Qt uses internally to composite a widget through an effect.
Matching, longstanding external Qt bug reports describe the same code path,
still open as of this Qt version.

This is a real Qt/PyQt6 bug, not a mistake in this codebase's application
logic. No amount of careful usage of `QGraphicsEffect` was found to avoid it
reliably — see "What didn't work" below.

## What triggers it

Across several rounds of investigation on this branch:

- A **cross-type effect swap** on the same widget instance (e.g. installing
  a `QGraphicsDropShadowEffect`, later replacing it with a
  `QGraphicsOpacityEffect` on that same widget) reliably crashed within
  ~100-150 iterations of create/paint/swap/destroy churn.
- Eliminating the type-swap (each widget permanently owning one effect
  *type* for its whole life, only mutating scalar properties like
  `blurRadius` or `opacity`) reduced the crash rate but did not eliminate
  it — a `QGraphicsOpacityEffect` at **fractional opacity** was independently
  enough to trigger the same fault, given enough simultaneously-composited
  instances (e.g. a fully populated browse screen, many cards visible and
  painting at once).
- `QGraphicsDropShadowEffect` alone (no opacity effect involved) proved
  crash-free even at meaningful volume in isolated testing — but once a
  screen combining it with other effects, real navigation, and realistic
  card counts was exercised end-to-end, it also became implicated. The
  practical lesson: don't trust an isolated "N iterations, no crash" result
  as proof any `QGraphicsEffect` usage is safe at real-application scale.

In short: the "safe" boundary kept moving as more of the real application
exercised the code more realistically. That pattern — not a single clean
root cause with a single clean fix — is itself the reason this codebase's
policy is "don't use `QGraphicsEffect` at all," rather than "use it
carefully."

## What didn't work

Investigated and ruled out, each via a dedicated isolated repro:

- Not parenting effect objects to `self`.
- Explicit `effect.deleteLater()` / `anim.deleteLater()` instead of relying
  on Qt's implicit cleanup.
- Disabling the old effect (`setEnabled(False)`) before replacing it.
- Clearing the effect proactively in an overridden `hideEvent`.
- Skipping redundant same-state calls (avoiding re-installing an effect
  when nothing actually changed).
- Deferring a fractional-opacity transition to a later event-loop tick via
  `QTimer.singleShot(0, ...)`.
- "Reusing" an effect object across a type change — not actually possible:
  `QWidget.setGraphicsEffect()` synchronously C++-deletes the previously
  installed effect the instant it's replaced, regardless of any Python-side
  reference.

None of these shifted the crash point.

## The fix: paint-level effects only

Every visual effect this codebase needs (focus glow, unfocused-card dim,
backdrop cross-fade) is implemented as plain `QPainter` drawing inside a
`paintEvent`, never via `QGraphicsEffect`:

- **`MediaCard`'s dim** (`src/sixpack/ui/widgets/media_card.py`, `_Scrim`) —
  a non-interactive overlay widget that fills a translucent black rect.
- **`MediaCard`'s focus glow** (`_Glow` in the same file) — an inward
  radial-gradient overlay, since the card has essentially no spare margin
  to bleed a halo outward past its own fixed bounds.
- **`Backdrop`'s cross-fade** (`src/sixpack/ui/widgets/backdrop.py`) — two
  cached pixmaps composited manually via `QPainter.setOpacity()` inside one
  `paintEvent`, driven by a `QVariantAnimation` that only touches a plain
  Python float, never a `QGraphicsEffect` property.

`QPainter.setOpacity()` used this way composites within a single paint call
on one widget — it never touches `QGraphicsEffectSource`/`QWidget::render()`
re-entrancy, so it sidesteps this whole bug class.

**Invariant to preserve:** `graphicsEffect()` must return `None` at all
times on every widget in `src/sixpack/ui/`. This is checked directly by
tests (grep for `graphicsEffect() is None` in `tests/test_ui/`) and by a
permanent high-churn regression test
(`test_media_card_high_churn_no_crash` in `tests/test_ui/test_widgets.py`)
that exercises hundreds of focus-change cycles across many card instances
and asserts no crash.

## If you think you need `QGraphicsEffect` for something new

You probably don't — a hand-painted overlay or a manually-composited
`QPainter.setOpacity()` pass can produce the same visual result. If you
genuinely believe you've found a case where only `QGraphicsEffect` will do,
at minimum: test it under the exact conditions that actually exposed this
bug (many instances, real navigation, a realistic populated screen — not
just a handful of iterations in isolation), and expect it to eventually
resurface even if an isolated test looks clean.
