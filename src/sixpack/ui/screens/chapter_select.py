"""Chapter selection screen — pick a story within a box-set book."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from sixpack.api.models import Chapter, MediaProgress, SeriesBook
from sixpack.ui import theme
from sixpack.ui.cover_cache import CoverCache


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


class ChapterItem(QWidget):
    def __init__(self, index: int, chapter: Chapter, status: str, parent=None) -> None:
        super().__init__(parent)
        self._build_ui(index, chapter, status)

    def _build_ui(self, index: int, chapter: Chapter, status: str) -> None:
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.set_focused(False)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(16)

        dot = QLabel()
        dot.setFixedSize(14, 14)
        if status == "finished":
            dot.setStyleSheet(f"background: {theme.SUCCESS}; border-radius: 7px; border: none;")
        elif status == "in_progress":
            dot.setStyleSheet(f"background: {theme.ACCENT}; border-radius: 7px; border: none;")
        else:
            dot.setStyleSheet(f"background: {theme.TEXT_MUTED}; border-radius: 7px; border: none;")
        layout.addWidget(dot)

        num_label = QLabel(str(index + 1))
        num_label.setFixedWidth(36)
        num_label.setStyleSheet(
            f"color: {theme.TEXT_SECONDARY}; font-size: {theme.FONT_META}pt; background: transparent; border: none;"
        )
        layout.addWidget(num_label)

        title_text = chapter.title if chapter.title else f"Chapter {index + 1}"
        title = QLabel(title_text)
        title.setStyleSheet(
            f"color: {theme.TEXT_PRIMARY}; font-size: {theme.FONT_BODY}pt; font-weight: bold; background: transparent; border: none;"
        )
        layout.addWidget(title, stretch=1)

        duration = _fmt_duration(chapter.end - chapter.start)
        dur_label = QLabel(duration)
        dur_label.setStyleSheet(
            f"color: {theme.TEXT_SECONDARY}; font-size: {theme.FONT_META}pt; background: transparent; border: none;"
        )
        layout.addWidget(dur_label)

    def set_focused(self, focused: bool) -> None:
        border = theme.ACCENT if focused else "transparent"
        self.setStyleSheet(
            f"background: {theme.SURFACE}; border: 2px solid {border}; border-radius: 6px;"
        )


class ChapterSelectScreen(QWidget):
    """Chapter list for a single book/box-set. Emits play_requested(book, start_time)."""

    play_requested = pyqtSignal(object, float)   # SeriesBook, start_time
    back_requested = pyqtSignal()

    def __init__(self, cover_cache: CoverCache | None = None, parent=None) -> None:
        super().__init__(parent)
        self._book: SeriesBook | None = None
        self._chapters: list[Chapter] = []
        self._cover_cache = cover_cache
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        bar = QWidget()
        bar.setFixedHeight(72)
        bar.setStyleSheet(f"background-color: {theme.SURFACE};")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(24, 0, 24, 0)

        self._back_btn = QPushButton("← Episodes")
        self._back_btn.setFixedWidth(160)
        self._back_btn.setStyleSheet(f"font-size: {theme.FONT_BAR_BTN}pt;")
        self._back_btn.clicked.connect(self.back_requested)
        bar_layout.addWidget(self._back_btn)

        self._title_label = QLabel()
        self._title_label.setStyleSheet(
            f"font-size: {theme.FONT_HEADING}pt; font-weight: bold; color: {theme.TEXT_PRIMARY};"
        )
        bar_layout.addWidget(self._title_label)
        bar_layout.addStretch()

        self._count_label = QLabel()
        self._count_label.setStyleSheet(
            f"color: {theme.TEXT_SECONDARY}; font-size: {theme.FONT_META}pt;"
        )
        bar_layout.addWidget(self._count_label)

        root.addWidget(bar)

        # All focus/selection rendering is done by ChapterItem.set_focused().
        self._list = QListWidget()
        self._list.setSpacing(2)
        self._list.setStyleSheet(f"""
            QListWidget {{
                background-color: {theme.BG};
                outline: none;
            }}
            QListWidget::item {{
                padding: 0;
                margin: 2px 0;
                background-color: transparent;
                border: none;
            }}
            QListWidget::item:selected {{
                background-color: transparent;
            }}
            QListWidget::item:focus {{
                background-color: transparent;
                outline: none;
            }}
        """)
        self._list.currentRowChanged.connect(self._on_row_changed)
        self._list.itemActivated.connect(self._on_item_activated)
        root.addWidget(self._list)

    def _on_row_changed(self, row: int) -> None:
        for i in range(self._list.count()):
            widget = self._list.itemWidget(self._list.item(i))
            if isinstance(widget, ChapterItem):
                widget.set_focused(i == row)

    def load(
        self,
        book: SeriesBook,
        chapters: list[Chapter],
        progress: MediaProgress | None,
        server_url: str = "",
        token: str = "",
    ) -> None:
        self._book = book
        self._chapters = chapters
        self._title_label.setText(book.title)
        self._count_label.setText(f"{len(self._chapters)} chapters")

        is_finished = progress.is_finished if progress else False
        current_time = progress.current_time if (progress and not is_finished) else 0.0

        self._list.clear()
        for i, chapter in enumerate(self._chapters):
            status = _chapter_status(chapter, current_time, is_finished)
            ch_widget = ChapterItem(i, chapter, status)
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 68))
            item.setData(Qt.ItemDataRole.UserRole, chapter)
            self._list.addItem(item)
            self._list.setItemWidget(item, ch_widget)

        if self._list.count():
            idx = self._find_resume_index(current_time, is_finished)
            self._list.setCurrentRow(idx)
            self._on_row_changed(idx)
            self._list.setFocus()

    def _find_resume_index(self, current_time: float, is_finished: bool) -> int:
        if is_finished or current_time <= 0:
            return 0
        for i, chapter in enumerate(self._chapters):
            if current_time < chapter.end:
                return i
        return 0

    def _on_item_activated(self, item: QListWidgetItem) -> None:
        chapter: Chapter = item.data(Qt.ItemDataRole.UserRole)
        self.play_requested.emit(self._book, chapter.start)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._list.count():
            self._list.setFocus()

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.back_requested.emit()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            current = self._list.currentItem()
            if current:
                self._on_item_activated(current)
        else:
            super().keyPressEvent(event)
