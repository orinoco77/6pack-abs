"""A keyboard-navigable grid of focusable widgets."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QGridLayout, QScrollArea, QVBoxLayout, QWidget


class FocusGrid(QWidget):
    """
    Lays out child widgets in a grid and handles arrow-key navigation
    between them. Column count is set at construction time.

    Emits item_activated(index) when an item fires its activated signal.
    """

    item_activated = pyqtSignal(int)
    focus_changed = pyqtSignal(int)

    def __init__(
        self, columns: int = 4, h_spacing: int = 16, v_spacing: int = 16, parent=None
    ) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._columns = columns
        self._items: list[QWidget] = []
        self._focused_index = 0

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.viewport().setStyleSheet("background: transparent;")

        self._container = QWidget()
        self._container.setStyleSheet("background: transparent;")
        self._grid = QGridLayout(self._container)
        self._grid.setHorizontalSpacing(h_spacing)
        self._grid.setVerticalSpacing(v_spacing)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._grid.setContentsMargins(24, 24, 24, 24)

        scroll.setWidget(self._container)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        self._scroll = scroll

    def add_item(self, widget: QWidget) -> int:
        index = len(self._items)
        self._items.append(widget)
        row = index // self._columns
        col = index % self._columns
        self._grid.addWidget(widget, row, col)

        if hasattr(widget, "activated"):
            widget.activated.connect(lambda idx=index: self.item_activated.emit(idx))

        return index

    def clear(self) -> None:
        for item in self._items:
            self._grid.removeWidget(item)
            item.deleteLater()
        self._items.clear()
        self._focused_index = 0

    def focus_item(self, index: int) -> None:
        if not self._items:
            return
        index = max(0, min(index, len(self._items) - 1))
        # Clear visual focus on the old item
        if 0 <= self._focused_index < len(self._items):
            old = self._items[self._focused_index]
            if hasattr(old, "set_focused"):
                old.set_focused(False)
        self._focused_index = index
        widget = self._items[index]
        if hasattr(widget, "set_focused"):
            widget.set_focused(True)
        # Keep keyboard focus on the grid itself — not on the card.
        # If focus were given to the card, arrow keys would bubble up through
        # the QScrollArea which would scroll the view instead of navigating.
        self.setFocus()
        self._scroll.ensureWidgetVisible(widget)
        self.focus_changed.emit(index)

    def set_focus_first(self) -> None:
        self.focus_item(0)

    # ------------------------------------------------------------------
    # Keyboard navigation (forwarded from parent or set as focus proxy)
    # ------------------------------------------------------------------

    def keyPressEvent(self, event) -> None:
        from sixpack.input.actions import InputAction
        from sixpack.input.keyboard import key_to_action

        count = len(self._items)
        if count == 0:
            super().keyPressEvent(event)
            return

        action = key_to_action(event.key())
        idx = self._focused_index
        cols = self._columns

        if action == InputAction.RIGHT:
            self.focus_item((idx + 1) % count)
        elif action == InputAction.LEFT:
            self.focus_item((idx - 1) % count)
        elif action == InputAction.DOWN:
            new = idx + cols
            if new < count:
                self.focus_item(new)
        elif action == InputAction.UP:
            new = idx - cols
            if new >= 0:
                self.focus_item(new)
        elif action == InputAction.SELECT:
            self.item_activated.emit(idx)
        else:
            super().keyPressEvent(event)

    @property
    def item_count(self) -> int:
        return len(self._items)

    @property
    def focused_index(self) -> int:
        return self._focused_index
