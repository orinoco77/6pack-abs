"""Reusable centered Cancel/Confirm confirmation overlay, shared by
PlayerScreen and DetailGridScreen (see the manual mark-finished design
spec). Not a QDialog -- this app never uses modal Qt dialogs; every
existing overlay (e.g. PlayerScreen's chapter overlay) is a plain child
widget shown on top of its host screen, and this follows the same
convention.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from sixpack.input.actions import InputAction
from sixpack.ui import theme


class ConfirmPopup(QWidget):
    """Host screens must check `.isVisible()` in their own keyPressEvent
    and call `handle_key(action)` (then unconditionally return) before
    falling through to normal handling -- see PlayerScreen's existing
    chapter-overlay convention, now shared by two screens. `handle_key`
    always consumes the key while visible; it has no return value because
    every caller's usage is unconditional "call it, then return" while
    the popup is up.
    """

    confirmed = pyqtSignal()
    cancelled = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._focus_index = 0  # 0 = Cancel, 1 = Confirm -- safer default
        self._build_ui()
        self.hide()

    def _build_ui(self) -> None:
        self.setStyleSheet(
            f"background: {theme.SURFACE}; border: 2px solid {theme.ACCENT}; "
            f"border-radius: 8px;"
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(20)

        self._message_label = QLabel("")
        self._message_label.setWordWrap(True)
        self._message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._message_label.setStyleSheet(
            f"color: {theme.TEXT_PRIMARY}; font-size: {theme.FONT_BODY}pt; "
            f"background: transparent; border: none;"
        )
        outer.addWidget(self._message_label)

        button_row = QHBoxLayout()
        button_row.setSpacing(16)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._cancel_btn.clicked.connect(self._activate_cancel)
        self._confirm_btn = QPushButton("Confirm")
        self._confirm_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._confirm_btn.clicked.connect(self._activate_confirm)
        button_row.addWidget(self._cancel_btn)
        button_row.addWidget(self._confirm_btn)
        outer.addLayout(button_row)
        self._buttons = [self._cancel_btn, self._confirm_btn]

    def show_confirm(
        self, message: str, confirm_label: str = "Confirm", cancel_label: str = "Cancel"
    ) -> None:
        self._message_label.setText(message)
        self._confirm_btn.setText(confirm_label)
        self._cancel_btn.setText(cancel_label)
        self._focus_index = 0
        self._reflect_focus()
        self.show()
        self.raise_()

    def handle_key(self, action: InputAction | None) -> None:
        if action == InputAction.BACK:
            self._activate_cancel()
        elif action == InputAction.LEFT:
            self._focus_index = max(0, self._focus_index - 1)
            self._reflect_focus()
        elif action == InputAction.RIGHT:
            self._focus_index = min(len(self._buttons) - 1, self._focus_index + 1)
            self._reflect_focus()
        elif action == InputAction.SELECT:
            self._buttons[self._focus_index].click()
        # Anything else is silently swallowed too -- the popup owns all
        # input while visible, matching the chapter overlay's convention.

    def _reflect_focus(self) -> None:
        for i, btn in enumerate(self._buttons):
            border = theme.ACCENT if i == self._focus_index else "transparent"
            btn.setStyleSheet(
                f"background: {theme.SURFACE_HIGH}; color: {theme.TEXT_PRIMARY}; "
                f"border: 2px solid {border}; border-radius: 6px; padding: 8px 20px; "
                f"font-size: {theme.FONT_BODY}pt;"
            )

    def _activate_cancel(self) -> None:
        self.hide()
        self.cancelled.emit()

    def _activate_confirm(self) -> None:
        self.hide()
        self.confirmed.emit()
