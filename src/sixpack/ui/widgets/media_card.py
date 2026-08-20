"""Focusable media card widget for grid browsing."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal, QSize, QPropertyAnimation
from PyQt6.QtGui import QPixmap, QPainter, QColor, QFont
from PyQt6.QtWidgets import (
    QFrame, QLabel, QVBoxLayout, QGraphicsDropShadowEffect, QGraphicsOpacityEffect,
)


class _ElideLabel(QLabel):
    """QLabel that elides text with '...' to fit its own width."""

    def paintEvent(self, event) -> None:
        try:
            painter = QPainter(self)
            elided = self.fontMetrics().elidedText(
                self.text(), Qt.TextElideMode.ElideRight, self.width()
            )
            painter.setPen(self.palette().windowText().color())
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                elided,
            )
        except RuntimeError:
            # Widget was deleted on the C++ side during teardown; skip painting.
            pass

from sixpack.ui import theme


class MediaCard(QFrame):
    """
    A focusable card showing cover art, title, and an optional subtitle.
    Emits activated() when Enter/Space is pressed while focused.
    """

    activated = pyqtSignal()

    _PLACEHOLDER_GLYPH = {"book": "📖", "podcast": "🎙"}

    def __init__(
        self,
        title: str,
        subtitle: str = "",
        meta: str = "",
        media_type: str = "book",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setFixedSize(theme.CARD_WIDTH + 2 * theme.FOCUS_BORDER, theme.CARD_HEIGHT)
        self.setObjectName("media_card")
        # NoFocus: keyboard focus stays on FocusGrid; set_focused() controls the border.
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._title = title
        self._subtitle = subtitle
        self._meta = meta
        self._media_type = media_type
        self._pixmap: QPixmap | None = None
        self._focused = False
        self._glow_anim: QPropertyAnimation | None = None

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._art_label = QLabel()
        self._art_label.setFixedSize(theme.CARD_WIDTH, theme.CARD_ART_HEIGHT)
        self._art_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._art_label.setStyleSheet(
            f"background-color: {theme.SURFACE_HIGH}; border-radius: {theme.CARD_RADIUS}px {theme.CARD_RADIUS}px 0 0;"
        )
        self._render_placeholder()

        info_frame = QFrame()
        info_frame.setFixedHeight(theme.CARD_HEIGHT - theme.CARD_ART_HEIGHT)
        info_frame.setStyleSheet(
            f"background-color: {theme.SURFACE};"
            f"border-radius: 0 0 {theme.CARD_RADIUS}px {theme.CARD_RADIUS}px;"
        )
        info_layout = QVBoxLayout(info_frame)
        info_layout.setContentsMargins(8, 6, 8, 6)
        info_layout.setSpacing(2)

        title_label = _ElideLabel(self._title)
        title_label.setStyleSheet(
            f"color: {theme.TEXT_PRIMARY}; font-size: {theme.FONT_META}pt; font-weight: bold;"
            f"background: transparent;"
        )

        info_layout.addWidget(title_label)

        if self._subtitle:
            sub_label = QLabel(self._subtitle)
            sub_label.setStyleSheet(
                f"color: {theme.TEXT_SECONDARY}; font-size: {theme.FONT_META - 2}pt; background: transparent;"
            )
            sub_label.setMaximumHeight(20)
            info_layout.addWidget(sub_label)

        layout.addWidget(self._art_label)
        layout.addWidget(info_frame)

        self.setStyleSheet(
            f"#media_card {{ border-radius: {theme.CARD_RADIUS}px; border: {theme.FOCUS_BORDER}px solid transparent; }}"
        )

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

    def set_cover(self, pixmap: QPixmap) -> None:
        scaled = pixmap.scaled(
            QSize(theme.CARD_WIDTH, theme.CARD_ART_HEIGHT),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._art_label.setPixmap(scaled)
        self._pixmap = pixmap

    def set_progress(self, fraction: float) -> None:
        """Overlay a thin progress bar at the bottom of the art area."""
        if self._pixmap:
            base = self._pixmap.scaled(
                QSize(theme.CARD_WIDTH, theme.CARD_ART_HEIGHT),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
        else:
            base = QPixmap(theme.CARD_WIDTH, theme.CARD_ART_HEIGHT)
            base.fill(QColor(theme.SURFACE_HIGH))

        painter = QPainter(base)
        bar_h = 5
        y = theme.CARD_ART_HEIGHT - bar_h
        painter.fillRect(0, y, theme.CARD_WIDTH, bar_h, QColor(theme.SURFACE))
        bar_w = int(theme.CARD_WIDTH * max(0.0, min(1.0, fraction)))
        painter.fillRect(0, y, bar_w, bar_h, QColor(theme.ACCENT))
        painter.end()
        self._art_label.setPixmap(base)

    # ------------------------------------------------------------------
    # Focus state (driven by FocusGrid, not Qt keyboard focus)
    # ------------------------------------------------------------------

    def set_focused(self, focused: bool) -> None:
        was_focused = self._focused
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
        elif was_focused:
            # Only dim when transitioning away from focused state.
            self._glow_anim = None
            dim = QGraphicsOpacityEffect(self)
            dim.setOpacity(theme.UNFOCUSED_OPACITY)
            self.setGraphicsEffect(dim)
        else:
            # Card was never focused; clear any leftover effect.
            self._glow_anim = None
            self.setGraphicsEffect(None)

    def keyPressEvent(self, event) -> None:
        from sixpack.input.keyboard import key_to_action
        from sixpack.input.actions import InputAction

        if key_to_action(event.key()) == InputAction.SELECT:
            self.activated.emit()
        else:
            super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        self.activated.emit()
