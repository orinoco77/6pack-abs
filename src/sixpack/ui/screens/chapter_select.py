"""Chapter selection screen — pick a chapter within an audiobook.

Reuses the same cinematic Backdrop+hero shell as the grid detail screens
(``DetailGridScreen``), but does NOT subclass it: chapters within one book
all share the SAME cover art (the book's own cover), so a card grid of
duplicate images would be visually useless here. Instead this screen keeps
its existing ``QListWidget``-based list — the right structural choice for
a single-column list — with each row (``ChapterItem``) upgraded to the same
progress language ``MediaCard`` uses: a thin progress bar + checkmark-when-
finished, instead of the old small colored status dot.
"""
from __future__ import annotations

from PyQt6 import sip
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QColor, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from sixpack.api.models import Chapter, LibraryItem, MediaProgress, SeriesBook, PlaylistItem
from sixpack.ui import theme
from sixpack.ui.cover_cache import CoverCache, dominant_color
from sixpack.ui.widgets.hero_backdrop import HeroBackdrop


def _fmt_duration(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def _chapter_status(chapter: Chapter, current_time: float, is_finished: bool) -> str:
    if is_finished:
        return "finished"
    if current_time <= 0:
        return "unstarted"
    if current_time >= chapter.end:
        return "finished"
    if current_time >= chapter.start:
        return "in_progress"
    return "unstarted"


def _chapter_fraction(chapter: Chapter, current_time: float, status: str) -> float:
    """Fraction (0.0..1.0) through *this* chapter — mirrors the semantics
    MediaCard's callers use (``DetailGridScreen._item_progress``): a
    finished item reports fraction 0.0 (its bar stays empty; the
    checkmark alone communicates "finished"), only an in-progress item
    reports a real fraction.
    """
    if status != "in_progress":
        return 0.0
    span = chapter.end - chapter.start
    if span <= 0:
        return 0.0
    return max(0.0, min(1.0, (current_time - chapter.start) / span))


class _ProgressStrip(QWidget):
    """Thin paint-level progress bar spanning a chapter row's full width —
    same visual weight/drawing approach as ``MediaCard.set_progress``'s
    bar, adapted to a list-row footer instead of a card-bottom overlay.

    Deliberately paint-level, not a ``QGraphicsEffect`` — see
    ``docs/qt-graphics-effect-crash.md``.
    """

    _HEIGHT = 4

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(self._HEIGHT)
        self._fraction = 0.0

    def set_fraction(self, fraction: float) -> None:
        self._fraction = max(0.0, min(1.0, fraction))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: ARG002
        try:
            painter = QPainter(self)
            painter.fillRect(self.rect(), QColor(theme.SURFACE_HIGH))
            width = int(self.width() * self._fraction)
            if width > 0:
                painter.fillRect(0, 0, width, self.height(), QColor(theme.ACCENT))
            painter.end()
        except RuntimeError:
            # Widget was deleted on the C++ side during teardown; skip painting.
            pass


class _FinishedCheck(QWidget):
    """Small paint-level checkmark badge for a finished chapter row — the
    same ``theme.SUCCESS`` checkmark-on-a-circle visual language as
    ``MediaCard``'s ``_FinishedBadge``, just sized down for a list row
    rather than a card-corner overlay.

    Deliberately paint-level, not a ``QGraphicsEffect`` — see
    ``docs/qt-graphics-effect-crash.md``.
    """

    _SIZE = 22

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
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
            font.setPointSize(11)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "✓")
            painter.end()
        except RuntimeError:
            # Widget was deleted on the C++ side during teardown; skip painting.
            pass


class ChapterItem(QWidget):
    def __init__(
        self,
        index: int,
        chapter: Chapter,
        status: str,
        fraction: float = 0.0,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._build_ui(index, chapter, status, fraction)

    def _build_ui(self, index: int, chapter: Chapter, status: str, fraction: float) -> None:
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.set_focused(False)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 10, 16, 8)
        outer.setSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(16)

        num_label = QLabel(str(index + 1))
        num_label.setFixedWidth(36)
        num_label.setStyleSheet(
            f"color: {theme.TEXT_SECONDARY}; font-size: {theme.FONT_META}pt; background: transparent; border: none;"
        )
        row.addWidget(num_label)

        title_text = chapter.title if chapter.title else f"Chapter {index + 1}"
        title = QLabel(title_text)
        title.setStyleSheet(
            f"color: {theme.TEXT_PRIMARY}; font-size: {theme.FONT_BODY}pt; font-weight: bold; background: transparent; border: none;"
        )
        row.addWidget(title, stretch=1)

        duration = _fmt_duration(chapter.end - chapter.start)
        dur_label = QLabel(duration)
        dur_label.setStyleSheet(
            f"color: {theme.TEXT_SECONDARY}; font-size: {theme.FONT_META}pt; background: transparent; border: none;"
        )
        row.addWidget(dur_label)

        self._check = _FinishedCheck()
        self._check.setVisible(status == "finished")
        row.addWidget(self._check)

        outer.addLayout(row)

        self._progress = _ProgressStrip()
        self._progress.set_fraction(fraction)
        outer.addWidget(self._progress)

    def set_focused(self, focused: bool) -> None:
        border = theme.ACCENT if focused else "transparent"
        self.setStyleSheet(
            f"background: {theme.SURFACE}; border: 2px solid {border}; border-radius: 6px;"
        )


class ChapterSelectScreen(QWidget):
    """Chapter list for a single book/box-set. Emits play_requested(book, start_time)."""

    play_requested = pyqtSignal(object, float)                  # SeriesBook, start_time
    playlist_item_play_requested = pyqtSignal(object, float)    # PlaylistItem, start_time
    library_item_play_requested = pyqtSignal(object, float)     # LibraryItem, start_time
    back_requested = pyqtSignal()

    def __init__(self, cover_cache: CoverCache | None = None, parent=None) -> None:
        super().__init__(parent)
        self._book: SeriesBook | None = None
        self._playlist_item: PlaylistItem | None = None
        self._library_item: LibraryItem | None = None
        self._chapters: list[Chapter] = []
        self._cover_cache = cover_cache
        self._backdrop_key: str = ""
        self._backdrop_image_shown: bool = False
        self._build_ui()

    def _build_ui(self) -> None:
        self._hero_backdrop = HeroBackdrop(self)

        # All focus/selection rendering is done by ChapterItem.set_focused().
        self._list = QListWidget()
        self._list.setSpacing(2)
        # QListWidget inherits from QAbstractScrollArea, so — like every
        # other scroll container sitting in front of a Backdrop in this
        # codebase (browse.py's _rows_scroll/_grid_scroll, FocusGrid) — it
        # needs BOTH the widget's own stylesheet AND its viewport's
        # stylesheet set to a transparent background, or its opaque
        # QAbstractScrollArea viewport paints over the Backdrop and hides
        # it completely.
        self._list.setStyleSheet("""
            QListWidget {
                background: transparent;
                outline: none;
            }
            QListWidget::item {
                padding: 0;
                margin: 2px 0;
                background-color: transparent;
                border: none;
            }
            QListWidget::item:selected {
                background-color: transparent;
            }
            QListWidget::item:focus {
                background-color: transparent;
                outline: none;
            }
        """)
        self._list.viewport().setStyleSheet("background: transparent;")
        self._list.currentRowChanged.connect(self._on_row_changed)
        self._list.itemActivated.connect(self._on_item_activated)

        layout = QVBoxLayout(self)
        # Top margin pushes the list below the hero band (same fix as
        # detail_grid.py's outer layout, applied here to the QVBoxLayout
        # directly rather than inside a scroll area, so content is clipped
        # at the hero's bottom edge instead of scrolling under it — unlike
        # browse.py's rows_layout, which applies its margin INSIDE a scroll
        # area so content scrolls under a translucent hero as the user
        # scrolls) so the first chapter row doesn't start already
        # overlapping the hero's title/subtitle text.
        layout.setContentsMargins(0, HeroBackdrop.HERO_H, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._list)
        # Explicit z-order: HeroBackdrop only manages stacking among its own
        # children (backdrop vs. hero overlay), not relative to external
        # siblings like _list — see HeroBackdrop's class docstring.
        self._hero_backdrop.lower()

    def resizeEvent(self, event) -> None:
        self._hero_backdrop.setGeometry(self.rect())
        super().resizeEvent(event)

    def _on_row_changed(self, row: int) -> None:
        for i in range(self._list.count()):
            widget = self._list.itemWidget(self._list.item(i))
            if isinstance(widget, ChapterItem):
                widget.set_focused(i == row)

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load_from_library_item(
        self,
        item: LibraryItem,
        chapters: list[Chapter],
        progress: MediaProgress | None,
        server_url: str = "",
        token: str = "",
    ) -> None:
        """Load chapters for a standalone library item (from the browse screen)."""
        self._library_item = item
        self._book = None
        self._playlist_item = None
        self._populate_chapters(
            item.title, chapters, progress,
            item.cover_url(server_url, token), item.id, token,
        )

    def load(
        self,
        book: SeriesBook,
        chapters: list[Chapter],
        progress: MediaProgress | None,
        server_url: str = "",
        token: str = "",
    ) -> None:
        self._book = book
        self._playlist_item = None
        self._library_item = None
        self._populate_chapters(
            book.title, chapters, progress,
            book.cover_url(server_url, token), book.id, token,
        )

    def load_from_playlist_item(
        self,
        item: PlaylistItem,
        chapters: list[Chapter],
        progress: MediaProgress | None,
        server_url: str = "",
        token: str = "",
    ) -> None:
        """Load chapters for a playlist item (similar to load but for playlists)."""
        self._playlist_item = item
        self._book = None
        self._library_item = None
        self._populate_chapters(
            item.title, chapters, progress,
            item.cover_url(server_url, token), item.id, token,
        )

    def _populate_chapters(
        self,
        title: str,
        chapters: list[Chapter],
        progress: MediaProgress | None,
        cover_url: str | None,
        key: str,
        token: str,
    ) -> None:
        self._chapters = chapters
        self._hero_backdrop.set_title(title)
        self._hero_backdrop.set_subtitle(f"{len(self._chapters)} chapters")

        is_finished = progress.is_finished if progress else False
        current_time = progress.current_time if (progress and not is_finished) else 0.0

        self._list.clear()
        for i, chapter in enumerate(self._chapters):
            status = _chapter_status(chapter, current_time, is_finished)
            fraction = _chapter_fraction(chapter, current_time, status)
            ch_widget = ChapterItem(i, chapter, status, fraction)
            list_item = QListWidgetItem()
            list_item.setSizeHint(QSize(0, 68))
            list_item.setData(Qt.ItemDataRole.UserRole, chapter)
            self._list.addItem(list_item)
            self._list.setItemWidget(list_item, ch_widget)

        if self._list.count():
            idx = self._find_resume_index(current_time, is_finished)
            self._list.setCurrentRow(idx)
            self._on_row_changed(idx)
            self._list.setFocus()

        # ONE cover for the whole screen (the book's own) — fetched and
        # shown once here, NOT re-fetched as focus moves between chapter
        # rows (see module docstring / _on_row_changed above, which never
        # touches the backdrop).
        self._load_backdrop(cover_url, token, key)

    def _load_backdrop(self, cover_url: str | None, token: str, key: str) -> None:
        self._hero_backdrop.backdrop.set_expected_key(key)
        # Set synchronously, before either async fetch below kicks off, so a
        # callback that resolves after this screen has since been reused for
        # a different book (this screen instance is constructed once and
        # reused across load()/load_from_library_item()/
        # load_from_playlist_item() calls) can detect it's stale and drop
        # itself — same key-guard pattern as Backdrop.set_expected_key,
        # applied here at the screen level since it guards the dominant-
        # color fetch below, which Backdrop.show_color itself doesn't key-
        # check the way Backdrop.show_image does.
        #
        # `_backdrop_image_shown` guards a SECOND, same-key race: fetch()
        # and fetch_backdrop() can resolve at different speeds (sync on a
        # cache hit, async on a miss) for the SAME book — e.g. the raw cover
        # was evicted from CoverCache but the backdrop JPEG wasn't (the
        # backdrop file is always written after its raw cover, so it's
        # always newer, making this the systematic case under eviction
        # pressure). If `_backdrop_cb` fires first and starts cross-fading
        # to the real image, a later same-key `_color_cb` must not call
        # show_color and hard-reset the Backdrop back to a flat gradient —
        # the `_backdrop_key` guard alone doesn't catch this because the key
        # still matches; only "has the real image already started showing"
        # does.
        self._backdrop_key = key
        self._backdrop_image_shown = False
        if not cover_url or self._cover_cache is None:
            return

        def _color_cb(pm: QPixmap) -> None:
            if sip.isdeleted(self) or self._backdrop_key != key or self._backdrop_image_shown:
                return
            self._hero_backdrop.backdrop.show_color(dominant_color(pm))

        def _backdrop_cb(pm: QPixmap, k: str = key) -> None:
            if sip.isdeleted(self):
                return
            self._backdrop_image_shown = True
            self._hero_backdrop.backdrop.show_image(pm, key=k)

        self._cover_cache.fetch(cover_url, token, _color_cb)
        self._cover_cache.fetch_backdrop(cover_url, token, _backdrop_cb)

    def _find_resume_index(self, current_time: float, is_finished: bool) -> int:
        if is_finished or current_time <= 0:
            return 0
        for i, chapter in enumerate(self._chapters):
            if current_time < chapter.end:
                return i
        return 0

    def _on_item_activated(self, item: QListWidgetItem) -> None:
        chapter: Chapter = item.data(Qt.ItemDataRole.UserRole)
        if self._library_item:
            self.library_item_play_requested.emit(self._library_item, chapter.start)
        elif self._book:
            self.play_requested.emit(self._book, chapter.start)
        elif self._playlist_item:
            self.playlist_item_play_requested.emit(self._playlist_item, chapter.start)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._list.count():
            self._list.setFocus()

    def keyPressEvent(self, event) -> None:
        from sixpack.input.keyboard import key_to_action
        from sixpack.input.actions import InputAction

        action = key_to_action(event.key())
        if action == InputAction.BACK:
            self.back_requested.emit()
        elif action == InputAction.SELECT:
            current = self._list.currentItem()
            if current:
                self._on_item_activated(current)
        else:
            super().keyPressEvent(event)
