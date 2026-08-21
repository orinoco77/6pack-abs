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
