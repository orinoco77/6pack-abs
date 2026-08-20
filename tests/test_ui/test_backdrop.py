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
