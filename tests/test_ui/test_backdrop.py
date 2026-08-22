from PyQt6.QtCore import QVariantAnimation
from PyQt6.QtGui import QColor, QPixmap
from PyQt6.QtWidgets import QGraphicsEffect, QWidget
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
    assert b._incoming_pixmap is not None and not b._incoming_pixmap.isNull()


def test_backdrop_uses_no_graphics_effect(qtbot):
    """Regression guard: Backdrop's cross-fade must never route through
    QGraphicsEffect (QGraphicsOpacityEffect etc.) — that mechanism has been
    root-caused to a Qt6.11/PyQt6 compositor segfault elsewhere in this
    codebase. The cross-fade must be pure paint-level compositing instead.
    """
    b = Backdrop()
    qtbot.addWidget(b)
    b.resize(640, 360)

    b.show_color(QColor(40, 80, 160))
    assert b.graphicsEffect() is None

    pix = QPixmap(640, 360)
    pix.fill(QColor(10, 10, 10))
    b.show_image(pix)
    assert b.graphicsEffect() is None

    # No child widget anywhere carries a QGraphicsEffect either.
    for child in b.findChildren(QWidget):
        assert child.graphicsEffect() is None

    # And nothing on the instance is a QGraphicsEffect subclass.
    for value in vars(b).values():
        assert not isinstance(value, QGraphicsEffect)


def test_backdrop_paints_across_multiple_cycles(qtbot):
    """Exercise the real paintEvent path (not just internal state) across
    several show_color/show_image cycles, including a repaint forced while
    a cross-fade is mid-flight. Must not raise or crash.
    """
    b = Backdrop()
    qtbot.addWidget(b)
    b.resize(640, 360)
    b.show()

    b.show_color(QColor(20, 60, 120))
    b.repaint()
    grabbed = b.grab()
    assert not grabbed.isNull()

    pix1 = QPixmap(640, 360)
    pix1.fill(QColor(200, 50, 50))
    b.show_image(pix1)
    b.repaint()  # mid-fade repaint

    pix2 = QPixmap(640, 360)
    pix2.fill(QColor(50, 200, 50))
    b.show_image(pix2)  # start a new fade while the previous is in-flight
    b.repaint()

    grabbed2 = b.grab()
    assert not grabbed2.isNull()


def test_backdrop_anim_reused_not_leaked(qtbot):
    """Regression guard: Backdrop must reuse a single QVariantAnimation for
    its cross-fade rather than constructing a new one on every
    show_image() call. Backdrop is a single long-lived widget for the
    whole app session (hours, on a TV client), so recreating one per call
    would leak a live QObject child on every focus change for the entire
    session (dropping the Python reference doesn't delete the underlying
    C++ object while `b` still parents it)."""
    b = Backdrop()
    qtbot.addWidget(b)
    b.resize(640, 360)
    for i in range(50):
        pix = QPixmap(640, 360)
        pix.fill(QColor(i, i, i))
        b.show_image(pix)
    assert len(b.findChildren(QVariantAnimation)) == 1
    assert b._anim is not None


def test_backdrop_show_image_drops_stale_key(qtbot):
    """A show_image() callback tagged with a key that no longer matches
    what Backdrop was told to expect (via set_expected_key) must be
    dropped rather than clobbering the currently displayed content —
    guards against the stale-backdrop race where an old item's async
    fetch resolves after focus already moved on to a new item."""
    b = Backdrop()
    qtbot.addWidget(b)
    b.resize(640, 360)

    b.set_expected_key("item-a")
    pix_a = QPixmap(640, 360)
    pix_a.fill(QColor(200, 0, 0))
    b.show_image(pix_a, key="item-a")
    assert b._incoming_pixmap is pix_a

    # Focus moves on to a different item before A's callback would have
    # arrived in the real race.
    b.set_expected_key("item-b")
    pix_b = QPixmap(640, 360)
    pix_b.fill(QColor(0, 200, 0))
    b.show_image(pix_b, key="item-b")
    assert b._incoming_pixmap is pix_b

    # A's now-stale callback finally resolves — must be dropped silently.
    stale_pix = QPixmap(640, 360)
    stale_pix.fill(QColor(0, 0, 200))
    b.show_image(stale_pix, key="item-a")
    assert b._incoming_pixmap is pix_b


def test_backdrop_show_image_without_key_always_applies(qtbot):
    """Callers that don't pass a key (e.g. existing direct/test callers)
    are unaffected by the staleness guard — key=None always applies."""
    b = Backdrop()
    qtbot.addWidget(b)
    b.resize(640, 360)
    b.set_expected_key("some-key")
    pix = QPixmap(640, 360)
    pix.fill(QColor(1, 2, 3))
    b.show_image(pix)  # no key passed
    assert b._incoming_pixmap is pix


def test_backdrop_show_image_skips_redundant_fade_for_same_settled_key(qtbot):
    """Regression test: a background data refresh that re-reflects the SAME
    still-focused item must not re-trigger the cross-fade — the backdrop is
    already showing this item's blurred image, so a second show_image()
    for the same key would just fade the image onto itself: a visible
    flicker with zero actual visual change. Root-caused live: the app's
    browse-content cache-then-refresh flow calls _reflect_focus twice for
    a still-focused item (once from the cache-primed first paint, once
    when the real network result lands)."""
    b = Backdrop()
    qtbot.addWidget(b)
    b.resize(640, 360)

    b.set_expected_key("item-a")
    pix_a = QPixmap(640, 360)
    pix_a.fill(QColor(200, 0, 0))
    b.show_image(pix_a, key="item-a")
    assert b._incoming_pixmap is pix_a
    b._on_fade_finished()  # simulate the cross-fade animation completing
    assert b._current_pixmap is pix_a
    assert b._incoming_pixmap is None

    # Same key, called again (e.g. a background refresh re-reflecting the
    # same still-focused item) — must be a no-op, not a new fade.
    pix_a_again = QPixmap(640, 360)
    pix_a_again.fill(QColor(200, 0, 0))
    b.show_image(pix_a_again, key="item-a")

    assert b._incoming_pixmap is None  # no new fade was started
    assert b._current_pixmap is pix_a  # still showing the original settled pixmap


def test_backdrop_show_color_skips_regression_to_gradient_for_same_settled_key(qtbot):
    """Same root cause as the show_image case, for show_color(): once the
    blurred image for a key is fully settled, a later show_color() call for
    that SAME key (e.g. _reflect_focus's own synchronous show_color call,
    which always runs right before the fetch_backdrop callback) must not
    instantly regress the display back to a flat gradient."""
    b = Backdrop()
    qtbot.addWidget(b)
    b.resize(640, 360)

    b.set_expected_key("item-a")
    pix_a = QPixmap(640, 360)
    pix_a.fill(QColor(200, 0, 0))
    b.show_image(pix_a, key="item-a")
    b._on_fade_finished()
    assert b._current_pixmap is pix_a

    b.show_color(QColor(10, 10, 10), key="item-a")

    assert b._current_pixmap is pix_a  # unchanged — no regression to gradient


def test_backdrop_show_color_and_show_image_still_apply_for_a_new_key(qtbot):
    """Sanity check: the dedup guard is per-key, not global — focusing a
    genuinely different item must still show its gradient placeholder and
    then fade in its real image normally."""
    b = Backdrop()
    qtbot.addWidget(b)
    b.resize(640, 360)

    b.set_expected_key("item-a")
    pix_a = QPixmap(640, 360)
    pix_a.fill(QColor(200, 0, 0))
    b.show_image(pix_a, key="item-a")
    b._on_fade_finished()

    b.set_expected_key("item-b")
    b.show_color(QColor(10, 10, 10), key="item-b")
    assert b._current_pixmap is not pix_a  # gradient replaced it

    pix_b = QPixmap(640, 360)
    pix_b.fill(QColor(0, 200, 0))
    b.show_image(pix_b, key="item-b")
    assert b._incoming_pixmap is pix_b  # new fade started normally
