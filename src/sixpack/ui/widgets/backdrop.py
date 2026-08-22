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
    ``QPainter.setOpacity``) rather than via ``QGraphicsOpacityEffect`` —
    see ``docs/qt-graphics-effect-crash.md`` for why no widget in this
    package ever uses ``QGraphicsEffect``.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._current_pixmap: QPixmap | None = None   # fully-settled content
        self._incoming_pixmap: QPixmap | None = None  # cross-fading in
        self._fade: float = 0.0                        # 0.0..1.0 of incoming

        # `_current_key` is the key of the item this Backdrop is currently
        # expected to be showing content for — set synchronously (via
        # `set_expected_key`) by the caller right before it kicks off an
        # async fetch. `show_image` compares its own `key` argument against
        # this before painting, so a callback that resolves after focus has
        # already moved on to a different item (a real, reachable race on a
        # cold disk cache: an uncached item's fetch is still in flight when
        # a different, already-cached item is focused and paints first) gets
        # silently dropped instead of clobbering what's currently displayed.
        self._current_key: str = ""

        # Key of the item whose blurred image is the fully-settled display
        # right now (set once a cross-fade finishes). Lets show_color/
        # show_image skip redundant work when they're asked to (re-)show
        # content for an item that's already fully displayed — e.g. a
        # background data refresh re-reflecting the still-focused item,
        # which would otherwise fade the image onto itself (a visible
        # flicker with no actual visual change) or regress the display
        # back to a flat gradient placeholder.
        self._image_key: str = ""

        # One long-lived QVariantAnimation, reused (stopped/reconfigured/
        # restarted) on every cross-fade rather than recreated per call.
        # Backdrop is a single long-lived widget for the whole app session
        # (hours, on a TV client) — recreating a QVariantAnimation(self) on
        # every show_image() leaks a live QObject child every time, since
        # dropping the Python reference doesn't delete the underlying C++
        # object while `self` still parents it.
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(_FADE_MS)
        self._anim.valueChanged.connect(self._on_fade_value)
        self._anim.finished.connect(self._on_fade_finished)

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

    def set_expected_key(self, key: str) -> None:
        """Record which item's content this Backdrop should now show.

        Call this synchronously, before starting any async fetch for `key`.
        Any later `show_image(pixmap, key=...)` callback whose key no
        longer matches — because focus already moved on to a different
        item by the time the fetch resolved — is dropped rather than
        painted.
        """
        self._current_key = key

    def show_color(self, color: QColor, key: str | None = None) -> None:
        if key is not None and key == self._image_key:
            # Already showing this item's blurred image — don't regress to
            # a flat gradient placeholder for a same-item re-reflect.
            return
        pix = QPixmap(max(1, self.width()), max(1, self.height()))
        grad = QLinearGradient(0, 0, 0, pix.height())
        grad.setColorAt(0.0, color.darker(150))
        grad.setColorAt(1.0, QColor(theme.BG))
        painter = QPainter(pix)
        painter.fillRect(pix.rect(), QBrush(grad))
        painter.end()
        self._anim.stop()
        self._current_pixmap = pix
        self._incoming_pixmap = None
        self._fade = 0.0
        self.update()

    def show_image(self, pixmap: QPixmap, key: str | None = None) -> None:
        # A stale callback for an item that's no longer focused — drop it
        # silently instead of clobbering whatever is now displayed. `key`
        # is optional (defaults to None, which always passes) so direct/
        # test callers that don't care about staleness are unaffected.
        if key is not None and key != self._current_key:
            return

        if key is not None and key == self._image_key:
            # Already fully showing this exact item's blurred image —
            # skip the redundant cross-fade (no visual change to make).
            return

        # Promote whatever was mid-fade-in to the settled layer, then fade
        # the new pixmap in on top of it.
        if self._incoming_pixmap is not None and not self._incoming_pixmap.isNull():
            self._current_pixmap = self._incoming_pixmap
        self._anim.stop()
        self._incoming_pixmap = pixmap
        self._fade = 0.0

        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def _on_fade_value(self, value) -> None:
        self._fade = float(value)
        self.update()

    def _on_fade_finished(self) -> None:
        if self._incoming_pixmap is not None:
            self._current_pixmap = self._incoming_pixmap
            self._image_key = self._current_key
        self._incoming_pixmap = None
        self._fade = 0.0
        self.update()
