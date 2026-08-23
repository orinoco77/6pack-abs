"""Startup screen offering to install a newer release. Follows
LoginScreen's convention: real Qt focus stays on self; keyPressEvent
interprets InputAction and manually restyles whichever button is
logically focused (see LoginScreen._reflect_discovered_focus for the
established version of this pattern).
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from sixpack.input.actions import InputAction
from sixpack.input.keyboard import key_to_action
from sixpack.ui import theme


class UpdatePromptScreen(QWidget):
    """Full-screen prompt shown at startup when a newer release is found.

    Three states, entered via show_prompt/show_installing/show_error. Only
    show_prompt has interactive, keyboard-navigable buttons (Install /
    Later); show_error has a single Continue button; show_installing has
    no interactive elements.
    """

    install_requested = pyqtSignal()
    later_requested = pyqtSignal()
    continue_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._focus_index = 0  # 0 = Install, 1 = Later
        self._build_ui()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def _build_ui(self) -> None:
        self.setStyleSheet(f"background: {theme.BG};")
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(24)

        self._title_label = QLabel("Update available")
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_label.setStyleSheet(
            f"font-size: {theme.FONT_TITLE}pt; font-weight: bold; color: {theme.TEXT_PRIMARY};"
        )
        layout.addWidget(self._title_label)

        self._version_label = QLabel("")
        self._version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._version_label.setStyleSheet(
            f"font-size: {theme.FONT_BODY}pt; color: {theme.TEXT_SECONDARY};"
        )
        layout.addWidget(self._version_label)

        layout.addSpacing(16)

        self._button_row = QWidget()
        button_layout = QHBoxLayout(self._button_row)
        button_layout.setSpacing(16)
        self._install_btn = QPushButton("Install")
        self._install_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._install_btn.clicked.connect(self._activate_install)
        self._later_btn = QPushButton("Later")
        self._later_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._later_btn.clicked.connect(self._activate_later)
        button_layout.addWidget(self._install_btn)
        button_layout.addWidget(self._later_btn)
        layout.addWidget(self._button_row)
        self._buttons = [self._install_btn, self._later_btn]

        self._status_label = QLabel("")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet(
            f"font-size: {theme.FONT_META}pt; color: {theme.TEXT_MUTED}; font-style: italic;"
        )
        self._status_label.setVisible(False)
        layout.addWidget(self._status_label)

        self._continue_btn = QPushButton("Continue")
        self._continue_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._continue_btn.clicked.connect(self._activate_continue)
        self._continue_btn.setVisible(False)
        layout.addWidget(self._continue_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self._reflect_focus()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.setFocus()

    # ------------------------------------------------------------------
    # State entry points
    # ------------------------------------------------------------------

    def show_prompt(self, current_version: str, new_version: str) -> None:
        self._title_label.setText("Update available")
        self._version_label.setText(f"v{current_version} → v{new_version}")
        self._version_label.setVisible(True)
        self._button_row.setVisible(True)
        self._status_label.setVisible(False)
        self._continue_btn.setVisible(False)
        self._focus_index = 0
        self._reflect_focus()

    def show_installing(self) -> None:
        self._title_label.setText("Updating…")
        self._version_label.setVisible(False)
        self._button_row.setVisible(False)
        self._status_label.setText("Downloading and installing the new version…")
        self._status_label.setVisible(True)
        self._continue_btn.setVisible(False)

    def show_error(self, message: str) -> None:
        self._title_label.setText("Update failed")
        self._version_label.setVisible(False)
        self._button_row.setVisible(False)
        self._status_label.setText(message)
        self._status_label.setVisible(True)
        self._continue_btn.setVisible(True)

    # ------------------------------------------------------------------
    # Keyboard navigation
    # ------------------------------------------------------------------

    def keyPressEvent(self, event) -> None:
        action = key_to_action(event.key())

        if self._continue_btn.isVisible():
            if action == InputAction.SELECT:
                self._activate_continue()
                return
            super().keyPressEvent(event)
            return

        if not self._button_row.isVisible():
            super().keyPressEvent(event)
            return

        if action == InputAction.LEFT and self._focus_index > 0:
            self._focus_index -= 1
            self._reflect_focus()
        elif action == InputAction.RIGHT and self._focus_index < len(self._buttons) - 1:
            self._focus_index += 1
            self._reflect_focus()
        elif action == InputAction.SELECT:
            if self._focus_index == 0:
                self._activate_install()
            else:
                self._activate_later()
        else:
            super().keyPressEvent(event)

    def _reflect_focus(self) -> None:
        for i, btn in enumerate(self._buttons):
            active = i == self._focus_index
            border = theme.ACCENT if active else "transparent"
            btn.setStyleSheet(
                f"background: {theme.SURFACE_HIGH}; color: {theme.TEXT_PRIMARY}; "
                f"border: 2px solid {border}; border-radius: 6px; padding: 10px 24px; "
                f"font-size: {theme.FONT_BODY}pt;"
            )

    def _activate_install(self) -> None:
        self.install_requested.emit()

    def _activate_later(self) -> None:
        self.later_requested.emit()

    def _activate_continue(self) -> None:
        self.continue_requested.emit()
