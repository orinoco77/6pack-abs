"""Playlist detail screen — item list with progress indicators."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from sixpack.api.models import MediaProgress, Playlist, PlaylistItem
from sixpack.ui import theme
from sixpack.ui.cover_cache import CoverCache


def _fmt_duration(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    if h:
        return f"{h}h {m:02d}m"
    return f"{m}m"


class PlaylistItemWidget(QWidget):
    """A single playlist item row."""

    def __init__(self, item: PlaylistItem, progress: MediaProgress | None, parent=None) -> None:
        super().__init__(parent)
        self._item = item
        self._build_ui(item, progress)

    def _build_ui(self, item: PlaylistItem, progress: MediaProgress | None) -> None:
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.set_focused(False)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 16, 12)
        layout.setSpacing(12)

        # Cover art thumbnail
        self._cover_label = QLabel()
        self._cover_label.setFixedSize(44, 44)
        self._cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cover_label.setStyleSheet(
            f"background-color: {theme.SURFACE_HIGH}; border-radius: 4px; border: none;"
        )
        layout.addWidget(self._cover_label)

        self._dot = QLabel()
        self._dot.setFixedSize(14, 14)
        layout.addWidget(self._dot)

        title = QLabel(item.title)
        title.setStyleSheet(
            f"color: {theme.TEXT_PRIMARY}; font-size: {theme.FONT_BODY}pt; font-weight: bold; background: transparent; border: none;"
        )
        layout.addWidget(title, stretch=1)

        # Chapter count hint — shown only for items with chapters
        chapter_count = len(item.media.chapters)
        if chapter_count > 1:
            ch_label = QLabel(f"{chapter_count} ch")
            ch_label.setStyleSheet(
                f"color: {theme.TEXT_MUTED}; font-size: {theme.FONT_META}pt; background: transparent; border: none;"
            )
            layout.addWidget(ch_label)

        self._duration_label = QLabel()
        layout.addWidget(self._duration_label)

        self.update_progress(progress)

    def set_focused(self, focused: bool) -> None:
        border = theme.ACCENT if focused else "transparent"
        self.setStyleSheet(
            f"background: {theme.SURFACE}; border: 2px solid {border}; border-radius: 6px;"
        )

    def set_cover(self, pix: QPixmap) -> None:
        scaled = pix.scaled(
            44, 44,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._cover_label.setPixmap(scaled)

    def update_progress(self, progress: MediaProgress | None) -> None:
        if progress and progress.is_finished:
            self._dot.setStyleSheet(
                f"background: {theme.SUCCESS}; border-radius: 7px; border: none;"
            )
        elif progress and progress.current_time > 0:
            self._dot.setStyleSheet(
                f"background: {theme.ACCENT}; border-radius: 7px; border: none;"
            )
        else:
            self._dot.setStyleSheet(
                f"background: {theme.TEXT_MUTED}; border-radius: 7px; border: none;"
            )

        duration_text = _fmt_duration(self._item.duration)
        if progress and progress.current_time > 0 and not progress.is_finished:
            elapsed = _fmt_duration(progress.current_time)
            self._duration_label.setText(f"{elapsed} / {duration_text}")
            self._duration_label.setStyleSheet(
                f"color: {theme.ACCENT}; font-size: {theme.FONT_META}pt; background: transparent; border: none;"
            )
        else:
            self._duration_label.setText(duration_text)
            self._duration_label.setStyleSheet(
                f"color: {theme.TEXT_SECONDARY}; font-size: {theme.FONT_META}pt; background: transparent; border: none;"
            )


class PlaylistDetailScreen(QWidget):
    """
    Shows the item list for a playlist. Emits play_requested(item, start_time)
    for single-track items, item_activated(item) for items with chapters,
    and back_requested() on Back.
    """

    play_requested = pyqtSignal(object, float)   # PlaylistItem, start_time
    item_activated = pyqtSignal(object)           # PlaylistItem — fetch chapters then route
    back_requested = pyqtSignal()

    def __init__(self, cover_cache: CoverCache | None = None, parent=None) -> None:
        super().__init__(parent)
        self._items: list[PlaylistItem] = []
        self._progress: dict[str, MediaProgress] = {}
        self._cover_cache = cover_cache
        self._server_url = ""
        self._token = ""
        self._playlist: Playlist | None = None
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

        self._back_btn = QPushButton("← Playlists")
        self._back_btn.setFixedWidth(140)
        self._back_btn.setStyleSheet(f"font-size: {theme.FONT_BAR_BTN}pt;")
        self._back_btn.clicked.connect(self.back_requested)
        bar_layout.addWidget(self._back_btn)

        self._title_label = QLabel()
        self._title_label.setStyleSheet(
            f"font-size: {theme.FONT_HEADING}pt; font-weight: bold; color: {theme.TEXT_PRIMARY};"
        )
        bar_layout.addWidget(self._title_label)
        bar_layout.addStretch()

        self._loading_label = QLabel("Loading…")
        self._loading_label.setStyleSheet(
            f"color: {theme.TEXT_SECONDARY}; font-size: {theme.FONT_META}pt; font-style: italic;"
        )
        self._loading_label.hide()
        bar_layout.addWidget(self._loading_label)

        self._play_all_btn = QPushButton("▶  Play All")
        self._play_all_btn.setFixedWidth(160)
        self._play_all_btn.setStyleSheet(f"font-size: {theme.FONT_BAR_BTN}pt;")
        self._play_all_btn.clicked.connect(self._on_play_all)
        bar_layout.addWidget(self._play_all_btn)

        root.addWidget(bar)

        # Padding: 0 — global QListWidget::item padding clips custom widgets.
        # All focus/selection rendering is done by PlaylistItemWidget.set_focused(); we
        # suppress Qt's own selection painter so it never touches child labels.
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
            if isinstance(widget, PlaylistItemWidget):
                widget.set_focused(i == row)

    def show_loading(self, playlist: Playlist, server_url: str = "", token: str = "") -> None:
        """Display items immediately while progress is still being fetched."""
        self._playlist = playlist
        self._items = playlist.items
        self._progress = {}
        self._server_url = server_url
        self._token = token
        self._title_label.setText(playlist.name)
        self._loading_label.show()
        self._populate_list()

    def load(
        self,
        playlist: Playlist,
        progress: dict[str, MediaProgress],
        server_url: str = "",
        token: str = "",
    ) -> None:
        self._playlist = playlist
        self._items = playlist.items
        self._progress = progress
        self._server_url = server_url
        self._token = token
        self._title_label.setText(playlist.name)
        self._loading_label.hide()
        self._populate_list()

    def _populate_list(self) -> None:
        self._list.clear()
        for item in self._items:
            prog = self._progress.get(item.library_item_id)
            item_widget = PlaylistItemWidget(item, prog)
            list_item = QListWidgetItem()
            list_item.setSizeHint(QSize(0, 68))
            list_item.setData(Qt.ItemDataRole.UserRole, item)
            self._list.addItem(list_item)
            self._list.setItemWidget(list_item, item_widget)
            if self._cover_cache and self._server_url:
                cover_url = item.cover_url(self._server_url, self._token)
                self._cover_cache.fetch(cover_url, self._token, item_widget.set_cover)
        if self._list.count():
            idx = self._find_resume_index()
            self._list.setCurrentRow(idx)
            self._on_row_changed(idx)
            self._list.setFocus()

    def update_progress(self, progress: dict[str, MediaProgress]) -> None:
        """Refresh progress indicators on existing item widgets in-place."""
        self._progress = progress
        self._loading_label.hide()
        for row in range(self._list.count()):
            item = self._list.item(row)
            playlist_item: PlaylistItem = item.data(Qt.ItemDataRole.UserRole)
            widget = self._list.itemWidget(item)
            if isinstance(widget, PlaylistItemWidget):
                widget.update_progress(progress.get(playlist_item.library_item_id))
        idx = self._find_resume_index()
        self._list.setCurrentRow(idx)
        self._on_row_changed(idx)

    def _find_resume_index(self) -> int:
        for i, item in enumerate(self._items):
            prog = self._progress.get(item.library_item_id)
            if prog is None or not prog.is_finished:
                return i
        return 0

    def _on_item_activated(self, item: QListWidgetItem) -> None:
        playlist_item: PlaylistItem = item.data(Qt.ItemDataRole.UserRole)
        self.item_activated.emit(playlist_item)

    def _on_play_all(self) -> None:
        if self._items:
            idx = self._find_resume_index()
            item = self._items[idx]
            prog = self._progress.get(item.library_item_id)
            start_time = prog.current_time if prog and not prog.is_finished else 0.0
            self.play_requested.emit(item, start_time)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._list.count():
            self._list.setFocus()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.back_requested.emit()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            current = self._list.currentItem()
            if current:
                self._on_item_activated(current)
        else:
            super().keyPressEvent(event)
