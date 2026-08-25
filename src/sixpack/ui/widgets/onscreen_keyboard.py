"""D-pad-navigable on-screen QWERTY-ish keyboard — fallback text-entry
method for LoginScreen when the pairing flow isn't used. This widget (not
individual keys) owns real keyboard focus, matching the established
pattern elsewhere in this app (FocusGrid, ChapterSelectScreen): individual
key buttons are NoFocus, and this widget's own keyPressEvent drives
navigation, so a real remote's D-pad/Select/Back always reaches it
directly rather than being swallowed by a focused child button.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QGridLayout, QPushButton, QWidget

from sixpack.ui import theme

_ROWS: list[list[str]] = [
    list("1234567890"),
    list("qwertyuiop"),
    list("asdfghjkl"),
    list("zxcvbnm"),
]

_KEY_SIZE = 48


class OnScreenKeyboard(QWidget):
    key_pressed = pyqtSignal(str)
    backspace_pressed = pyqtSignal()
    done_pressed = pyqtSignal()
    back_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # self._grid[row][col] always holds a real QPushButton — never
        # None. A button that spans multiple grid columns (Space, Done)
        # has its reference repeated across every column it covers, so
        # column-indexing always resolves to a real, clickable widget and
        # _move_focus_horizontal below can walk column-by-column looking
        # for "the next *different* widget" without any gap-searching.
        self._grid: list[list[QPushButton]] = []
        self._focused_row = 0
        self._focused_col = 0
        self._build_ui()
        self._reflect_focus()

    def _make_key(self, label: str, width: int, on_click) -> QPushButton:
        btn = QPushButton(label)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setFixedSize(width, _KEY_SIZE)
        btn.clicked.connect(on_click)
        return btn

    def _build_ui(self) -> None:
        layout = QGridLayout(self)
        layout.setSpacing(6)

        for row_idx, chars in enumerate(_ROWS):
            row_buttons: list[QPushButton] = []
            for col_idx, ch in enumerate(chars):
                emit_char = lambda _checked=False, c=ch: self.key_pressed.emit(c)  # noqa: E731
                btn = self._make_key(ch, _KEY_SIZE, emit_char)
                layout.addWidget(btn, row_idx, col_idx)
                row_buttons.append(btn)
            self._grid.append(row_buttons)

        # Bottom row: Space / Backspace / Done, laid out across the same
        # 10-column width as the digit/letter rows above (Space spans
        # columns 0-6, Backspace sits at column 7, Done spans columns
        # 8-9) so a QGridLayout(widget, row, col, rowSpan, colSpan) call
        # for each matches a `self._grid.append([...])` entry of the same
        # length (10) with each button's reference repeated across the
        # columns it visually spans:
        #   [space, space, space, space, space, space, space, back, done, done]
        #    col0   col1   col2   col3   col4   col5   col6   col7  col8  col9
        bottom_row_idx = len(_ROWS)
        space_btn = self._make_key("Space", 7 * _KEY_SIZE, lambda: self.key_pressed.emit(" "))
        layout.addWidget(space_btn, bottom_row_idx, 0, 1, 7)
        back_btn = self._make_key("⌫", _KEY_SIZE, lambda: self.backspace_pressed.emit())
        layout.addWidget(back_btn, bottom_row_idx, 7)
        done_btn = self._make_key("Done", 2 * _KEY_SIZE, lambda: self.done_pressed.emit())
        layout.addWidget(done_btn, bottom_row_idx, 8, 1, 2)
        self._grid.append([space_btn] * 7 + [back_btn] + [done_btn] * 2)

    def _reflect_focus(self) -> None:
        focused = self._grid[self._focused_row][self._focused_col]
        seen: set[int] = set()
        for row in self._grid:
            for btn in row:
                if id(btn) in seen:
                    continue
                seen.add(id(btn))
                border = theme.ACCENT if btn is focused else "transparent"
                btn.setStyleSheet(
                    f"background: {theme.SURFACE_HIGH}; color: {theme.TEXT_PRIMARY}; "
                    f"border: 2px solid {border}; border-radius: 6px; "
                    f"font-size: {theme.FONT_BODY}pt; padding: 0px;"
                )

    def _move_focus_vertical(self, row: int) -> None:
        """Move focus up/down. Column is preserved (clamped to the target
        row's width) since every column already resolves to a real widget —
        no gap-searching needed."""
        row = max(0, min(row, len(self._grid) - 1))
        row_buttons = self._grid[row]
        col = max(0, min(self._focused_col, len(row_buttons) - 1))
        self._focused_row, self._focused_col = row, col
        self._reflect_focus()

    def _move_focus_horizontal(self, direction: int) -> None:
        """Move focus left/right by walking column-by-column, in one
        keypress, until reaching a *different* widget than the one
        currently focused. This means a single Right/Left press moves off
        a multi-column button (e.g. Space) in one step, rather than
        requiring one press per spanned column."""
        row_buttons = self._grid[self._focused_row]
        current = row_buttons[self._focused_col]
        col = self._focused_col
        while True:
            new_col = col + direction
            if new_col < 0 or new_col >= len(row_buttons):
                break
            col = new_col
            if row_buttons[col] is not current:
                break
        self._focused_col = col
        self._reflect_focus()

    def keyPressEvent(self, event) -> None:
        from sixpack.input.actions import InputAction
        from sixpack.input.keyboard import key_to_action

        action = key_to_action(event.key())
        if action == InputAction.BACK:
            self.back_requested.emit()
        elif action == InputAction.SELECT:
            self._grid[self._focused_row][self._focused_col].click()
        elif action == InputAction.UP:
            self._move_focus_vertical(self._focused_row - 1)
        elif action == InputAction.DOWN:
            self._move_focus_vertical(self._focused_row + 1)
        elif action == InputAction.LEFT:
            self._move_focus_horizontal(-1)
        elif action == InputAction.RIGHT:
            self._move_focus_horizontal(1)
        else:
            super().keyPressEvent(event)
