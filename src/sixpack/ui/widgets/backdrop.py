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
