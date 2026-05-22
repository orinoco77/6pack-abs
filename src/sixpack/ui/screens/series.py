"""Series grid screen — browse all series in a library."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal, QThread, pyqtSlot
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from sixpack.api.models import Library, Series
from sixpack.ui import theme
from sixpack.ui.widgets.focus_grid import FocusGrid
from sixpack.ui.widgets.media_card import MediaCard


class SeriesScreen(QWidget):
    """Grid of series cards for a given library. Emits series_selected(series)."""

    series_selected = pyqtSignal(object)         # Series
    back_requested = pyqtSignal()
    library_switch_requested = pyqtSignal(object)  # Library

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._library: Library | None = None
        self._all_libraries: list[Library] = []
        self._series_list: list[Series] = []
        self._server_url = ""
        self._token = ""
        self._nam: QNetworkAccessManager | None = None
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

        self._back_btn = QPushButton("← Libraries")
        self._back_btn.setFixedWidth(160)
        self._back_btn.setStyleSheet(f"font-size: {theme.FONT_BAR_BTN}pt;")
        self._back_btn.clicked.connect(self.back_requested)
        bar_layout.addWidget(self._back_btn)

        self._library_btn = QPushButton()
        self._library_btn.setMinimumWidth(180)
        self._library_btn.setStyleSheet(f"font-size: {theme.FONT_BAR_BTN}pt; font-weight: bold; text-align: left;")
        self._library_btn.clicked.connect(self._show_library_menu)
        bar_layout.addWidget(self._library_btn)
        bar_layout.addStretch()

        self._count_label = QLabel()
        self._count_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
        bar_layout.addWidget(self._count_label)

        root.addWidget(bar)

        self._grid = FocusGrid(columns=5, h_spacing=20, v_spacing=20)
        self._grid.item_activated.connect(self._on_item_activated)
        root.addWidget(self._grid)

    def load(
        self,
        library: Library,
        series_list: list[Series],
        server_url: str,
        token: str,
        all_libraries: list[Library] | None = None,
    ) -> None:
        self._library = library
        self._series_list = series_list
        self._server_url = server_url
        self._token = token

        if all_libraries is not None:
            self._all_libraries = all_libraries

        self._library_btn.setText(f"{library.name}  ▾")
        self._count_label.setText(f"{len(series_list)} series")

        self._grid.clear()
        if self._nam is None:
            self._nam = QNetworkAccessManager(self)

        for series in series_list:
            card = MediaCard(
                title=series.name,
                subtitle=f"{series.book_count} episode{'s' if series.book_count != 1 else ''}",
            )
            self._grid.add_item(card)
            cover_url = series.cover_url(server_url, token)
            if cover_url:
                self._fetch_cover(card, cover_url, token)

        self._grid.set_focus_first()

    def _fetch_cover(self, card: MediaCard, url: str, token: str) -> None:
        if self._nam is None:
            return
        request = QNetworkRequest()
        from PyQt6.QtCore import QUrl
        request.setUrl(QUrl(url))
        request.setRawHeader(b"Authorization", f"Bearer {token}".encode())
        reply = self._nam.get(request)
        reply.finished.connect(lambda r=reply, c=card: self._on_cover_loaded(r, c))

    def _on_cover_loaded(self, reply: QNetworkReply, card: MediaCard) -> None:
        if reply.error() == QNetworkReply.NetworkError.NoError:
            data = reply.readAll()
            pix = QPixmap()
            pix.loadFromData(data)
            if not pix.isNull():
                card.set_cover(pix)
        reply.deleteLater()

    def _make_library_menu(self) -> QMenu:
        menu = QMenu(self)
        for lib in self._all_libraries:
            action = menu.addAction(lib.name)
            action.setCheckable(True)
            action.setChecked(self._library is not None and lib.id == self._library.id)
            action.setData(lib)
        menu.triggered.connect(self._on_menu_action)
        return menu

    def _show_library_menu(self) -> None:
        menu = self._make_library_menu()
        pos = self._library_btn.mapToGlobal(QPoint(0, self._library_btn.height()))
        menu.exec(pos)

    def _on_menu_action(self, action) -> None:
        lib: Library | None = action.data()
        if lib is not None and (self._library is None or lib.id != self._library.id):
            self.library_switch_requested.emit(lib)

    def _on_item_activated(self, index: int) -> None:
        if 0 <= index < len(self._series_list):
            self.series_selected.emit(self._series_list[index])

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.back_requested.emit()
        else:
            super().keyPressEvent(event)
