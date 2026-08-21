"""Full-screen cinematic backdrop: cross-fades gradient ↔ blurred cover."""
from __future__ import annotations

from PyQt6.QtCore import Qt, QVariantAnimation
from PyQt6.QtGui import QColor, QPixmap, QPainter, QLinearGradient, QBrush
from PyQt6.QtWidgets import QWidget

from sixpack.ui import theme

_FADE_MS = 200


class Backdrop(QWidget):
    """Fully-settled "current" content with an optional cross-fading
    "incoming" pixmap painted on top.

    Cross-fading is implemented as manual pixmap compositing in
    ``paintEvent`` (two ``drawPixmap`` calls, the second under
    ``QPainter.setOpacity``) rather than via ``QGraphicsOpacityEffect``.
    That effect mechanism routes through ``QGraphicsEffectSource.pixmap()``
    / ``QWidget.render()`` to composite, which has been root-caused (via
    lldb) as the source of a Qt6.11/PyQt6 compositor segfault elsewhere in
    this codebase (see ``MediaCard``'s ``_Scrim`` for the sibling fix).
    Plain ``QPainter.setOpacity`` compositing within a single paint call
    never touches that machinery, so it sidesteps the crash class entirely.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._current_pixmap: QPixmap | None = None   # fully-settled content
        self._incoming_pixmap: QPixmap | None = None  # cross-fading in
        self._fade: float = 0.0                        # 0.0..1.0 of incoming
        self._anim: QVariantAnimation | None = None
        self._current_key: str = ""

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: ARG002
        painter = QPainter(self)
        if self._current_pixmap is not None and not self._current_pixmap.isNull():
            painter.drawPixmap(self.rect(), self._current_pixmap)
        if (
            self._incoming_pixmap is not None
            and not self._incoming_pixmap.isNull()
            and self._fade > 0.0
        ):
            painter.setOpacity(self._fade)
            painter.drawPixmap(self.rect(), self._incoming_pixmap)
            painter.setOpacity(1.0)
        painter.end()

    def show_color(self, color: QColor) -> None:
        pix = QPixmap(max(1, self.width()), max(1, self.height()))
        grad = QLinearGradient(0, 0, 0, pix.height())
        grad.setColorAt(0.0, color.darker(150))
        grad.setColorAt(1.0, QColor(theme.BG))
        painter = QPainter(pix)
        painter.fillRect(pix.rect(), QBrush(grad))
        painter.end()
        if self._anim is not None:
            self._anim.stop()
            self._anim = None
        self._current_pixmap = pix
        self._incoming_pixmap = None
        self._fade = 0.0
        self.update()

    def show_image(self, pixmap: QPixmap) -> None:
        # Promote whatever was mid-fade-in to the settled layer, then fade
        # the new pixmap in on top of it.
        if self._incoming_pixmap is not None and not self._incoming_pixmap.isNull():
            self._current_pixmap = self._incoming_pixmap
        if self._anim is not None:
            self._anim.stop()
            self._anim = None
        self._incoming_pixmap = pixmap
        self._fade = 0.0

        anim = QVariantAnimation(self)
        anim.setDuration(_FADE_MS)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.valueChanged.connect(self._on_fade_value)
        anim.finished.connect(self._on_fade_finished)
        anim.start()
        self._anim = anim  # keep ref

    def _on_fade_value(self, value) -> None:
        self._fade = float(value)
        self.update()

    def _on_fade_finished(self) -> None:
        if self._incoming_pixmap is not None:
            self._current_pixmap = self._incoming_pixmap
        self._incoming_pixmap = None
        self._fade = 0.0
        self._anim = None
        self.update()
