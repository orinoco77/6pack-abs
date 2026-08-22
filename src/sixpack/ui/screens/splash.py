"""Startup splash screen shown while autologin is in progress."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from sixpack.ui import theme


class SplashScreen(QWidget):
    """Full-screen splash displayed during startup autologin check."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(8)

        title = QLabel("SixPack")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            f"font-size: {theme.FONT_HUGE}pt; font-weight: bold; "
            f"color: {theme.ACCENT}; letter-spacing: 4px;"
        )
        layout.addWidget(title)

        subtitle = QLabel("Audiobookshelf")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet(
            f"font-size: {theme.FONT_HEADING}pt; color: {theme.TEXT_SECONDARY};"
        )
        layout.addWidget(subtitle)

        layout.addSpacing(48)

        self._status_label = QLabel("Connecting…")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setStyleSheet(
            f"font-size: {theme.FONT_META}pt; color: {theme.TEXT_MUTED}; font-style: italic;"
        )
        layout.addWidget(self._status_label)

    def set_status(self, text: str) -> None:
        self._status_label.setText(text)
