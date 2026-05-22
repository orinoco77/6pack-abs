"""Server login / setup screen."""
from __future__ import annotations

import asyncio

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
)

from sixpack.ui import theme


class LoginScreen(QWidget):
    """Collect server URL + credentials and emit login_requested."""

    login_requested = pyqtSignal(str, str, str)  # url, username, password
    error_message = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.setSpacing(20)
        root.setContentsMargins(80, 60, 80, 60)

        title = QLabel("SixPack")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            f"font-size: {theme.FONT_HUGE}pt; font-weight: bold; color: {theme.ACCENT};"
        )
        root.addWidget(title)

        subtitle = QLabel("Audiobookshelf client for your TV")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: {theme.FONT_BODY}pt;")
        root.addWidget(subtitle)

        root.addSpacing(40)

        form = QVBoxLayout()
        form.setSpacing(12)
        form.setContentsMargins(0, 0, 0, 0)

        max_w = 480

        self._url_input = QLineEdit()
        self._url_input.setPlaceholderText("Server URL  e.g. http://192.168.1.10:13378")
        self._url_input.setMaximumWidth(max_w)
        form.addWidget(self._url_input, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._user_input = QLineEdit()
        self._user_input.setPlaceholderText("Username")
        self._user_input.setMaximumWidth(max_w)
        form.addWidget(self._user_input, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._pass_input = QLineEdit()
        self._pass_input.setPlaceholderText("Password")
        self._pass_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._pass_input.setMaximumWidth(max_w)
        form.addWidget(self._pass_input, alignment=Qt.AlignmentFlag.AlignHCenter)

        root.addLayout(form)

        self._error_label = QLabel("")
        self._error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._error_label.setStyleSheet(f"color: {theme.DANGER}; font-size: {theme.FONT_META}pt;")
        self._error_label.setVisible(False)
        root.addWidget(self._error_label)

        btn_row = QHBoxLayout()
        btn_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._login_btn = QPushButton("Connect")
        self._login_btn.setFixedWidth(200)
        self._login_btn.clicked.connect(self._on_connect)
        btn_row.addWidget(self._login_btn)
        root.addLayout(btn_row)

        self._pass_input.returnPressed.connect(self._on_connect)
        self._user_input.returnPressed.connect(self._pass_input.setFocus)
        self._url_input.returnPressed.connect(self._user_input.setFocus)

    def _on_connect(self) -> None:
        url = self._url_input.text().strip()
        username = self._user_input.text().strip()
        password = self._pass_input.text()

        self._error_label.setVisible(False)

        if not url:
            self.show_error("Please enter the server URL")
            return
        if not username:
            self.show_error("Please enter your username")
            return

        self._login_btn.setEnabled(False)
        self._login_btn.setText("Connecting…")
        self.login_requested.emit(url, username, password)

    def show_error(self, message: str) -> None:
        self._error_label.setText(message)
        self._error_label.setVisible(True)
        self._login_btn.setEnabled(True)
        self._login_btn.setText("Connect")

    def set_prefill(self, url: str, username: str) -> None:
        self._url_input.setText(url)
        self._user_input.setText(username)
