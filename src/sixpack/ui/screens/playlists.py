"""Playlists grid screen — browse all playlists."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal, QPoint
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from sixpack.api.models import Library, Playlist
from sixpack.ui import theme
from sixpack.ui.cover_cache import CoverCache
from sixpack.ui.widgets.focus_grid import FocusGrid
from sixpack.ui.widgets.media_card import MediaCard


class PlaylistsScreen(QWidget):
    """Grid of playlist cards. Emits playlist_selected(playlist)."""

    playlist_selected = pyqtSignal(object)         # Playlist
    back_requested = pyqtSignal()
    library_switch_requested = pyqtSignal(object)  # Library
    view_switch_requested = pyqtSignal(str)       # "series" or "playlists"

    def __init__(self, cover_cache: CoverCache | None = None, parent=None) -> None:
        super().__init__(parent)
        self._library: Library | None = None
        self._all_libraries: list[Library] = []
        self._playlists: list[Playlist] = []
        self._server_url = ""
        self._token = ""
        self._cover_cache = cover_cache
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Top bar — Kodi-style
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

        # View switcher — Kodi-style
        self._view_switcher = QPushButton("Playlists  ▾")
        self._view_switcher.setFixedWidth(140)
        self._view_switcher.setStyleSheet(f"font-size: {theme.FONT_BAR_BTN}pt;")
        self._view_switcher.clicked.connect(self._show_view_menu)
        bar_layout.addWidget(self._view_switcher)

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
        library: Library | None,
        playlists: list[Playlist],
        server_url: str,
        token: str,
        all_libraries: list[Library] | None = None,
    ) -> None:
        self._library = library
        self._playlists = playlists
        self._server_url = server_url
        self._token = token

        if all_libraries is not None:
            self._all_libraries = all_libraries

        lib_name = library.name if library else "All Libraries"
        self._library_btn.setText(f"{lib_name}  ▾")
        self._count_label.setText(f"{len(playlists)} playlist{'s' if len(playlists) != 1 else ''}")

        self._grid.clear()
        for playlist in playlists:
            card = MediaCard(
                title=playlist.name,
                subtitle=f"{playlist.item_count} item{'s' if playlist.item_count != 1 else ''}",
            )
            self._grid.add_item(card)
            if self._cover_cache is not None:
                cover_url = playlist.cover_url(server_url, token)
                if cover_url:
                    self._cover_cache.fetch(cover_url, token, card.set_cover)

        self._grid.set_focus_first()

    def _make_library_menu(self) -> QMenu:
        menu = QMenu(self)
        # Add "All Libraries" option
        action_all = menu.addAction("All Libraries")
        action_all.setCheckable(True)
        action_all.setChecked(self._library is None)
        action_all.setData(None)
        menu.addSeparator()
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
        if (lib is None and self._library is not None) or (
            lib is not None and (self._library is None or lib.id != self._library.id)
        ):
            self.library_switch_requested.emit(lib)

    def _show_view_menu(self) -> None:
        menu = QMenu(self)
        action_series = menu.addAction("Series")
        action_series.setCheckable(True)
        action_series.setChecked(False)
        action_playlists = menu.addAction("Playlists")
        action_playlists.setCheckable(True)
        action_playlists.setChecked(True)
        menu.triggered.connect(self._on_view_menu_action)
        pos = self._view_switcher.mapToGlobal(QPoint(0, self._view_switcher.height()))
        menu.exec(pos)

    def _on_view_menu_action(self, action) -> None:
        view_name = action.text().lower()
        if view_name == "series":
            self.view_switch_requested.emit("series")

    def _on_item_activated(self, index: int) -> None:
        if 0 <= index < len(self._playlists):
            self.playlist_selected.emit(self._playlists[index])

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._grid.setFocus()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.back_requested.emit()
        else:
            super().keyPressEvent(event)
