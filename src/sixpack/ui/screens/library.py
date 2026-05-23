"""Library selection screen — shows all libraries on the server."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from sixpack.api.models import Library
from sixpack.ui import theme


class LibraryScreen(QWidget):
    """Displays available libraries. Emits library_selected(library) on activation."""

    library_selected = pyqtSignal(object)  # Library

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._libraries: list[Library] = []
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(60, 40, 60, 40)
        root.setSpacing(20)

        header = QHBoxLayout()
        title = QLabel("Libraries")
        title.setStyleSheet(
            f"font-size: {theme.FONT_TITLE}pt; font-weight: bold; color: {theme.TEXT_PRIMARY};"
        )
        header.addWidget(title)
        header.addStretch()
        root.addLayout(header)

        hint = QLabel("Select a library to browse")
        hint.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: {theme.FONT_META}pt;")
        root.addWidget(hint)

        self._list = QListWidget()
        self._list.itemActivated.connect(self._on_activated)
        self._list.itemPressed.connect(self._list.setCurrentItem)
        root.addWidget(self._list)

    def set_libraries(self, libraries: list[Library]) -> None:
        self._libraries = libraries
        self._list.clear()
        for lib in libraries:
            item = QListWidgetItem()
            item.setText(f"  {lib.name}")
            item.setData(Qt.ItemDataRole.UserRole, lib)
            self._list.addItem(item)
        if self._list.count():
            self._list.setCurrentRow(0)
            self._list.setFocus()

    def _on_activated(self, item: QListWidgetItem) -> None:
        lib: Library = item.data(Qt.ItemDataRole.UserRole)
        self.library_selected.emit(lib)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            current = self._list.currentItem()
            if current:
                self._on_activated(current)
        else:
            super().keyPressEvent(event)
