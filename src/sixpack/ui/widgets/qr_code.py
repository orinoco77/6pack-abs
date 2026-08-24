"""QR-code widget — plain QPainter rendering from qrcode's matrix output.

Deliberately not a QGraphicsEffect — see docs/qt-graphics-effect-crash.md.
Renders black-on-white regardless of the app's dark theme: QR scanners
expect strong, standard dark-on-light contrast, and most phone camera
apps are tuned for it — matching the app's theme here would hurt
scannability for no benefit.
"""
from __future__ import annotations

import qrcode
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QWidget


class QRCodeWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._matrix: list[list[bool]] = []

    def set_data(self, data: str) -> None:
        qr = qrcode.QRCode(border=2)
        qr.add_data(data)
        qr.make(fit=True)
        self._matrix = qr.get_matrix()
        self.update()

    def paintEvent(self, event) -> None:
        try:
            painter = QPainter(self)
            painter.fillRect(self.rect(), QColor("white"))
            if self._matrix:
                size = len(self._matrix)
                module_px = min(self.width(), self.height()) / size
                painter.setPen(QColor("black"))
                painter.setBrush(QColor("black"))
                for row_idx, row in enumerate(self._matrix):
                    for col_idx, is_dark in enumerate(row):
                        if is_dark:
                            x = int(col_idx * module_px)
                            y = int(row_idx * module_px)
                            side = int(module_px) + 1  # +1 avoids sub-pixel seams
                            painter.drawRect(x, y, side, side)
            painter.end()
        except RuntimeError:
            # Widget was deleted on the C++ side during teardown; skip painting.
            pass
