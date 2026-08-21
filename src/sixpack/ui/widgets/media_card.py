"""Focusable media card widget for grid browsing."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal, QSize, QVariantAnimation, QEvent
from PyQt6.QtGui import QBrush, QPixmap, QPainter, QColor, QFont, QRadialGradient
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


class _Glow(QWidget):
    """A non-interactive accent-tinted overlay used to make MediaCard's
    focus glow actually visible.

    The card is fixed-size with essentially no spare margin around its own
    body (``self`` is only ``2 * theme.FOCUS_BORDER`` larger than
    ``self._body`` — 3px per side), so there is no room to bleed a soft
    halo *outward* past the card's own bounds the way a drop-shadow
    normally would. Instead this paints an inward vignette — transparent at
    the body's center, brightening toward its edges — directly over the
    body/art area, the same way ``_Scrim`` paints its dim overlay. Strength
    is driven by ``MediaCard._glow_strength`` (0.0 unfocused .. 1.0 fully
    focused).

    Deliberately paint-level, not a ``QGraphicsEffect`` — see
    ``docs/qt-graphics-effect-crash.md``.
    """

    _MAX_ALPHA = 150  # alpha (0..255) at the body's edge when strength == 1.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._strength = 0.0

    def set_strength(self, strength: float) -> None:
        strength = max(0.0, min(1.0, strength))
        if strength == self._strength:
            return
        self._strength = strength
        self.update()

    def paintEvent(self, event) -> None:  # noqa: ARG002
        try:
            if self._strength <= 0.0:
                return
            rect = self.rect()
            if rect.isEmpty():
                return
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            center = rect.center()
            radius = max(rect.width(), rect.height()) * 0.75
            gradient = QRadialGradient(center.x(), center.y(), radius)
            accent = QColor(theme.ACCENT_GLOW)
            inner = QColor(accent)
            inner.setAlpha(0)
            outer = QColor(accent)
            outer.setAlpha(int(self._MAX_ALPHA * self._strength))
            gradient.setColorAt(0.0, inner)
            gradient.setColorAt(1.0, outer)
            painter.fillRect(rect, QBrush(gradient))
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
        # Paint-level focus glow: a small strength value (0.0..1.0) animated
        # via QVariantAnimation and rendered by `self._glow` (a `_Glow`
        # overlay sitting on top of `self._body`, see its docstring for why
        # it has to be an overlay rather than a halo bled outward past the
        # card's own bounds). No QGraphicsEffect involved — see
        # docs/qt-graphics-effect-crash.md. `self.graphicsEffect()` must be
        # `None` at all times.
        self._glow_strength: float = 0.0
        # One long-lived QVariantAnimation, reused (stopped/reconfigured/
        # restarted) on every focus change rather than recreated per call.
        # Recreating one on every set_focused() call leaks a live QObject
        # child each time (200 focus changes -> 200 live QVariantAnimation
        # children) since dropping the Python reference doesn't delete the
        # underlying C++ object while `self` still parents it.
        self._glow_anim = QVariantAnimation(self)
        self._glow_anim.setDuration(theme.FOCUS_ANIM_MS)
        self._glow_anim.valueChanged.connect(self._on_glow_value)

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

        # Focus glow overlay — see `_Glow` docstring. Sits above the scrim;
        # in practice the two never need to be simultaneously visible at
        # partial strength (the scrim's color/visibility flips immediately
        # in `set_focused`, only the glow strength animates), but raising it
        # last keeps the stacking order well-defined regardless.
        self._glow = _Glow(self._body)
        self._glow.setGeometry(self._body.rect())
        self._glow.raise_()
        self._glow.show()

        # Keep the scrim/glow exactly covering the body as layout resizes it.
        self._body.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        if obj is self._body and event.type() in (
            QEvent.Type.Resize,
            QEvent.Type.ChildAdded,
        ):
            self._scrim.setGeometry(self._body.rect())
            self._scrim.raise_()
            self._glow.setGeometry(self._body.rect())
            self._glow.raise_()
        return super().eventFilter(obj, event)

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

        # Glow strength animates 0.0..1.0 and is rendered in paintEvent —
        # never via a QGraphicsEffect (see comment in __init__). Reuses the
        # single persistent `self._glow_anim` created in __init__ rather
        # than constructing a new QVariantAnimation per call.
        self._glow_anim.stop()
        self._glow_anim.setStartValue(self._glow_strength)
        self._glow_anim.setEndValue(1.0 if focused else 0.0)
        self._glow_anim.start()

        # Dim is the paint-level scrim overlaying `self._body`. Applied
        # unconditionally on every call, regardless of prior focus state —
        # this is what fixes the sibling-dimming spec gap. No QGraphicsEffect
        # is involved, so this never enters Qt's fragile compositor path.
        self._scrim.setColor(
            _Scrim.color_for_opacity(1.0 if focused else theme.UNFOCUSED_OPACITY)
        )
        self._scrim.setVisible(not focused)

    def _on_glow_value(self, value) -> None:
        self._glow_strength = float(value)
        self._glow.set_strength(self._glow_strength)

    def keyPressEvent(self, event) -> None:
        from sixpack.input.keyboard import key_to_action
        from sixpack.input.actions import InputAction

        if key_to_action(event.key()) == InputAction.SELECT:
            self.activated.emit()
        else:
            super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        self.activated.emit()
