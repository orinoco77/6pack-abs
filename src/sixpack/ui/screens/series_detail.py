"""Series detail screen — episode list with progress indicators."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from sixpack.api.models import MediaProgress, Series, SeriesBook
from sixpack.ui import theme


def _fmt_duration(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    if h:
        return f"{h}h {m:02d}m"
    return f"{m}m"


class EpisodeItem(QWidget):
    """A single episode row in the series detail list."""

    def __init__(self, book: SeriesBook, progress: MediaProgress | None, parent=None) -> None:
        super().__init__(parent)
        self._build_ui(book, progress)

    def _build_ui(self, book: SeriesBook, progress: MediaProgress | None) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(16)

        # Progress dot
        dot = QLabel()
        dot.setFixedSize(14, 14)
        if progress and progress.is_finished:
            dot.setStyleSheet(
                f"background: {theme.SUCCESS}; border-radius: 7px;"
            )
        elif progress and progress.current_time > 0:
            dot.setStyleSheet(
                f"background: {theme.ACCENT}; border-radius: 7px;"
            )
        else:
            dot.setStyleSheet(
                f"background: {theme.TEXT_MUTED}; border-radius: 7px;"
            )
        layout.addWidget(dot)

        # Sequence number
        if book.sequence:
            seq_label = QLabel(book.sequence)
            seq_label.setFixedWidth(40)
            seq_label.setStyleSheet(
                f"color: {theme.TEXT_SECONDARY}; font-size: {theme.FONT_META}pt;"
            )
            layout.addWidget(seq_label)

        # Title
        title = QLabel(book.title)
        title.setStyleSheet(
            f"color: {theme.TEXT_PRIMARY}; font-size: {theme.FONT_BODY}pt; font-weight: bold;"
        )
        layout.addWidget(title, stretch=1)

        # Duration / progress
        duration_text = _fmt_duration(book.duration)
        if progress and progress.current_time > 0 and not progress.is_finished:
            elapsed = _fmt_duration(progress.current_time)
            duration_label = QLabel(f"{elapsed} / {duration_text}")
            duration_label.setStyleSheet(
                f"color: {theme.ACCENT}; font-size: {theme.FONT_META}pt;"
            )
        else:
            duration_label = QLabel(duration_text)
            duration_label.setStyleSheet(
                f"color: {theme.TEXT_SECONDARY}; font-size: {theme.FONT_META}pt;"
            )
        layout.addWidget(duration_label)


class SeriesDetailScreen(QWidget):
    """
    Shows the episode list for a series. Emits play_requested(book, start_time)
    when the user selects an episode, and back_requested() on Back.
    """

    play_requested = pyqtSignal(object, float)  # SeriesBook, start_time
    back_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._books: list[SeriesBook] = []
        self._progress: dict[str, MediaProgress] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Top bar
        bar = QWidget()
        bar.setFixedHeight(72)
        bar.setStyleSheet(f"background-color: {theme.SURFACE};")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(24, 0, 24, 0)

        self._back_btn = QPushButton("← Series")
        self._back_btn.setFixedWidth(140)
        self._back_btn.clicked.connect(self.back_requested)
        bar_layout.addWidget(self._back_btn)

        self._title_label = QLabel()
        self._title_label.setStyleSheet(
            f"font-size: {theme.FONT_HEADING}pt; font-weight: bold; color: {theme.TEXT_PRIMARY};"
        )
        bar_layout.addWidget(self._title_label)
        bar_layout.addStretch()

        self._play_all_btn = QPushButton("▶  Play All")
        self._play_all_btn.setFixedWidth(160)
        self._play_all_btn.clicked.connect(self._on_play_all)
        bar_layout.addWidget(self._play_all_btn)

        root.addWidget(bar)

        # Episode list
        self._list = QListWidget()
        self._list.setSpacing(2)
        self._list.itemActivated.connect(self._on_item_activated)
        root.addWidget(self._list)

    def load(self, series: Series, progress: dict[str, MediaProgress]) -> None:
        self._books = series.sorted_books
        self._progress = progress
        self._title_label.setText(series.name)

        self._list.clear()
        for book in self._books:
            prog = progress.get(book.id)
            ep_widget = EpisodeItem(book, prog)
            item = QListWidgetItem()
            item.setSizeHint(ep_widget.sizeHint())
            item.setData(Qt.ItemDataRole.UserRole, book)
            self._list.addItem(item)
            self._list.setItemWidget(item, ep_widget)

        if self._list.count():
            self._list.setCurrentRow(self._find_resume_index())
            self._list.setFocus()

    def _find_resume_index(self) -> int:
        """Return the index of the first unfinished episode."""
        for i, book in enumerate(self._books):
            prog = self._progress.get(book.id)
            if prog is None or (not prog.is_finished):
                return i
        return 0

    def _on_item_activated(self, item: QListWidgetItem) -> None:
        book: SeriesBook = item.data(Qt.ItemDataRole.UserRole)
        prog = self._progress.get(book.id)
        start_time = prog.current_time if prog and not prog.is_finished else 0.0
        self.play_requested.emit(book, start_time)

    def _on_play_all(self) -> None:
        if self._books:
            idx = self._find_resume_index()
            book = self._books[idx]
            prog = self._progress.get(book.id)
            start_time = prog.current_time if prog and not prog.is_finished else 0.0
            self.play_requested.emit(book, start_time)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.back_requested.emit()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            current = self._list.currentItem()
            if current:
                self._on_item_activated(current)
        else:
            super().keyPressEvent(event)
