"""Focusable media card widget for grid browsing."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal, QSize, QEvent
from PyQt6.QtGui import QPixmap, QPainter, QColor, QFont
from PyQt6.QtWidgets import (
    QFrame, QLabel, QVBoxLayout, QWidget,
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


class _Scrim(QWidget):
    """A non-interactive translucent black overlay used to dim a card.

    Deliberately paint-level, not a ``QGraphicsOpacityEffect`` — see
    ``docs/qt-graphics-effect-crash.md`` for why no widget in this package
    ever uses ``QGraphicsEffect``.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Never steal clicks/hover from the card underneath, never take focus.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setColor(_Scrim.color_for_opacity(theme.UNFOCUSED_OPACITY))

    @staticmethod
    def color_for_opacity(opacity: float) -> QColor:
        """Black with the alpha that visually matches rendering at `opacity`."""
        alpha = int(round(255 * (1.0 - max(0.0, min(1.0, opacity)))))
        return QColor(0, 0, 0, alpha)

    def setColor(self, color: QColor) -> None:
        self._color = color
        self.update()

    def color(self) -> QColor:
        return self._color

    def paintEvent(self, event) -> None:
        try:
            if self._color.alpha() == 0:
                return
            painter = QPainter(self)
            painter.fillRect(self.rect(), self._color)
            painter.end()
        except RuntimeError:
            # Widget was deleted on the C++ side during teardown; skip painting.
            pass


class _FinishedBadge(QWidget):
    """A small checkmark badge shown in the top-right corner of a card's
    art when the item is finished.

    Deliberately paint-level, not a ``QGraphicsEffect`` — see
    ``docs/qt-graphics-effect-crash.md``.
    """

    _SIZE = 28
    _MARGIN = 6

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedSize(self._SIZE, self._SIZE)

    def paintEvent(self, event) -> None:  # noqa: ARG002
        try:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setBrush(QColor(theme.SUCCESS))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(0, 0, self._SIZE, self._SIZE)
            painter.setPen(QColor(theme.TEXT_PRIMARY))
            font = painter.font()
            font.setPointSize(14)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "✓")
            painter.end()
        except RuntimeError:
            # Widget was deleted on the C++ side during teardown; skip painting.
            pass


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

        self._build_ui()

        # Dim is a paint-level scrim, NOT a QGraphicsOpacityEffect — see
        # docs/qt-graphics-effect-crash.md.
        #
        # It starts visible, matching `self._focused = False`. Sibling cards
        # in a freshly populated grid never receive an explicit set_focused()
        # call (FocusGrid/BrowseScreen only ever call it on the previously-
        # and newly-focused cards), so the construction-time default must
        # already reflect the unfocused look.
        self._scrim = _Scrim(self._body)
        self._scrim.setGeometry(self._body.rect())
        self._scrim.raise_()
        self._scrim.show()

        # Finished-state badge — a small checkmark overlay in the top-right
        # corner of the art, shown only when set_finished(True) is called.
        # Paint-level, not a QGraphicsEffect (see docs/qt-graphics-effect-crash.md).
        self._finished = False
        self._finished_badge = _FinishedBadge(self._body)
        self._position_finished_badge()
        self._finished_badge.raise_()
        self._finished_badge.hide()

        # Keep the scrim/badge exactly positioned as layout resizes the body.
        self._body.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        if obj is self._body and event.type() in (
            QEvent.Type.Resize,
            QEvent.Type.ChildAdded,
        ):
            self._scrim.setGeometry(self._body.rect())
            self._scrim.raise_()
            self._position_finished_badge()
            self._finished_badge.raise_()
        return super().eventFilter(obj, event)

    def _position_finished_badge(self) -> None:
        self._finished_badge.move(
            self._body.width() - self._finished_badge.width() - _FinishedBadge._MARGIN,
            _FinishedBadge._MARGIN,
        )

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._body = QWidget(self)
        outer.addWidget(self._body)

        layout = QVBoxLayout(self._body)
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

    def set_finished(self, finished: bool) -> None:
        """Show/hide the paint-level checkmark badge (see `_FinishedBadge`)."""
        self._finished = finished
        self._finished_badge.setVisible(finished)

    # ------------------------------------------------------------------
    # Focus state (driven by FocusGrid, not Qt keyboard focus)
    # ------------------------------------------------------------------

    def set_focused(self, focused: bool) -> None:
        self._focused = focused
        border = theme.ACCENT if focused else "transparent"
        self.setStyleSheet(
            f"#media_card {{ border-radius: {theme.CARD_RADIUS}px; "
            f"border: {theme.FOCUS_BORDER}px solid {border}; }}"
        )

        # Dim is the paint-level scrim overlaying `self._body`. Applied
        # unconditionally on every call, regardless of prior focus state —
        # this is what fixes the sibling-dimming spec gap. No QGraphicsEffect
        # is involved, so this never enters Qt's fragile compositor path.
        self._scrim.setColor(
            _Scrim.color_for_opacity(1.0 if focused else theme.UNFOCUSED_OPACITY)
        )
        self._scrim.setVisible(not focused)

    def keyPressEvent(self, event) -> None:
        from sixpack.input.keyboard import key_to_action
        from sixpack.input.actions import InputAction

        if key_to_action(event.key()) == InputAction.SELECT:
            self.activated.emit()
        else:
            super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        self.activated.emit()
