"""Server login / setup screen.

Two entry paths into the same three credential fields (URL/username/
password):

- **Pairing** (shown by default): a short code + QR code pointing at a
  local :class:`~sixpack.pairing.server.PairingServer` HTTP server. A
  phone or laptop on the same LAN opens that address, submits its own
  server URL + credentials, and this process logs in with them directly —
  no keyboard needed on the TV itself.
- **Keyboard fallback**: the original three ``QLineEdit`` fields, now also
  fillable via an :class:`~sixpack.ui.widgets.onscreen_keyboard.OnScreenKeyboard`
  for a remote-only setup (or when the pairing server can't bind a port).

Both views' widgets are built unconditionally in ``_build_ui`` — nothing is
constructed lazily inside ``_use_keyboard_fallback`` — so ``_url_input``,
``_user_input``, ``_pass_input``, ``_login_btn`` and ``_error_label`` stay
directly usable at all times regardless of which view is currently shown.
Switching views only toggles container visibility.
"""
from __future__ import annotations

from PyQt6.QtCore import QEvent, Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from sixpack.pairing.server import PairingServer
from sixpack.ui import theme
from sixpack.ui.widgets.backdrop import Backdrop
from sixpack.ui.widgets.onscreen_keyboard import OnScreenKeyboard
from sixpack.ui.widgets.qr_code import QRCodeWidget


class LoginScreen(QWidget):
    """Collect server URL + credentials and emit login_requested."""

    login_requested = pyqtSignal(str, str, str)  # url, username, password
    pairing_login_succeeded = pyqtSignal(str, str, str)  # url, username, token
    error_message = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._pairing_server: PairingServer | None = None
        # Which QLineEdit the on-screen keyboard currently types into.
        # Updated via eventFilter's FocusIn handling below (a real click/
        # Select on a field), and explicitly reset to the URL field whenever
        # the keyboard-fallback view is (re)shown.
        self._active_field: QLineEdit | None = None
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self._backdrop = Backdrop(self)
        self._backdrop.lower()
        self._backdrop.show_color(QColor(theme.ACCENT_DIM))

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

        self._build_pairing_view(root)
        self._build_keyboard_form(root)

        # Pairing is the default entry path; the keyboard fallback starts
        # hidden until start_pairing() fails to bind or the user explicitly
        # asks for it.
        self._pairing_view.setVisible(True)
        self._keyboard_form.setVisible(False)

    def _build_pairing_view(self, root: QVBoxLayout) -> None:
        self._pairing_view = QWidget()
        layout = QVBoxLayout(self._pairing_view)
        layout.setSpacing(16)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self._qr_widget = QRCodeWidget()
        self._qr_widget.setFixedSize(220, 220)
        layout.addWidget(self._qr_widget, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._pairing_code_label = QLabel("")
        self._pairing_code_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._pairing_code_label.setStyleSheet(
            f"font-size: {theme.FONT_HUGE}pt; font-weight: bold; "
            f"letter-spacing: 4px; color: {theme.ACCENT};"
        )
        layout.addWidget(self._pairing_code_label)

        instructions = QLabel(
            "On your phone or laptop, scan the QR code (or open the address "
            "shown) and enter this code to connect."
        )
        instructions.setAlignment(Qt.AlignmentFlag.AlignCenter)
        instructions.setWordWrap(True)
        instructions.setMaximumWidth(420)
        instructions.setStyleSheet(
            f"color: {theme.TEXT_SECONDARY}; font-size: {theme.FONT_META}pt;"
        )
        layout.addWidget(instructions)

        use_remote_btn = QPushButton("Use the remote instead")
        use_remote_btn.clicked.connect(self._use_keyboard_fallback)
        layout.addWidget(use_remote_btn, alignment=Qt.AlignmentFlag.AlignHCenter)

        root.addWidget(self._pairing_view)

    def _build_keyboard_form(self, root: QVBoxLayout) -> None:
        self._keyboard_form = QWidget()
        outer = QVBoxLayout(self._keyboard_form)
        outer.setSpacing(12)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        # Inline note shown only when start_pairing() auto-falls-back here
        # because the pairing server couldn't bind a port.
        self._pairing_unavailable_label = QLabel("")
        self._pairing_unavailable_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._pairing_unavailable_label.setStyleSheet(
            f"color: {theme.TEXT_SECONDARY}; font-size: {theme.FONT_META}pt;"
        )
        self._pairing_unavailable_label.setVisible(False)
        outer.addWidget(self._pairing_unavailable_label)

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

        outer.addLayout(form)

        # Track which field the on-screen keyboard types into: whichever
        # field last received real Qt focus (a click/Select on it).
        for field in (self._url_input, self._user_input, self._pass_input):
            field.installEventFilter(self)

        self._error_label = QLabel("")
        self._error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._error_label.setStyleSheet(f"color: {theme.DANGER}; font-size: {theme.FONT_META}pt;")
        self._error_label.setVisible(False)
        outer.addWidget(self._error_label)

        btn_row = QHBoxLayout()
        btn_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._login_btn = QPushButton("Connect")
        self._login_btn.setFixedWidth(200)
        self._login_btn.clicked.connect(self._on_connect)
        btn_row.addWidget(self._login_btn)
        outer.addLayout(btn_row)

        self._pass_input.returnPressed.connect(self._on_connect)
        self._user_input.returnPressed.connect(self._pass_input.setFocus)
        self._url_input.returnPressed.connect(self._user_input.setFocus)

        self._keyboard = OnScreenKeyboard()
        self._keyboard.key_pressed.connect(self._on_keyboard_key)
        self._keyboard.backspace_pressed.connect(self._on_keyboard_backspace)
        self._keyboard.done_pressed.connect(self._on_connect)
        self._keyboard.back_requested.connect(self._use_pairing_view)
        outer.addWidget(self._keyboard, alignment=Qt.AlignmentFlag.AlignHCenter)

        root.addWidget(self._keyboard_form)

    def resizeEvent(self, event) -> None:
        self._backdrop.setGeometry(self.rect())
        super().resizeEvent(event)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 — Qt-mandated name
        if event.type() == QEvent.Type.FocusIn and obj in (
            self._url_input,
            self._user_input,
            self._pass_input,
        ):
            self._active_field = obj
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------------
    # Pairing lifecycle
    # ------------------------------------------------------------------

    def start_pairing(self) -> None:
        """Start a fresh pairing server and show the pairing view.

        Falls back to the keyboard view automatically if the server can't
        bind a local port.
        """
        self._pairing_server = PairingServer(on_success=self._on_pairing_success)
        try:
            self._pairing_server.start()
        except OSError:
            self._pairing_server = None
            self._pairing_unavailable_label.setText(
                "Pairing unavailable — use the remote to connect"
            )
            self._pairing_unavailable_label.setVisible(True)
            self._use_keyboard_fallback()
            return

        self._qr_widget.set_data(self._pairing_server.pairing_url())
        self._pairing_code_label.setText(self._pairing_server.code)
        self._pairing_view.setVisible(True)
        self._keyboard_form.setVisible(False)

    def stop_pairing(self) -> None:
        """Tear down the pairing server, if one is running. Idempotent."""
        if self._pairing_server is not None:
            self._pairing_server.stop()
            self._pairing_server = None

    def _on_pairing_success(self, url: str, username: str, token: str) -> None:
        # Called from PairingServer's background HTTP-server thread. A
        # plain pyqtSignal.emit() here is safe and sufficient: Qt
        # automatically queues the delivery to any slot connected on this
        # (GUI-thread) object, regardless of which thread emitted it.
        self.pairing_login_succeeded.emit(url, username, token)

    def _use_keyboard_fallback(self) -> None:
        self._pairing_view.setVisible(False)
        self._keyboard_form.setVisible(True)
        self._active_field = self._url_input
        self._url_input.setFocus()

    def _use_pairing_view(self) -> None:
        """Switch back to the pairing view (mirror of _use_keyboard_fallback).

        Connected to the on-screen keyboard's back_requested signal — the
        remote's Back action while on the keyboard-fallback view. Only
        meaningful when a pairing server is actually running: if pairing
        was never started, or start_pairing() fell back here after a bind
        failure, self._pairing_server is None and there's no pairing view
        to return to, so this is a deliberate no-op rather than showing a
        broken/empty pairing view.
        """
        if self._pairing_server is None:
            return
        self._keyboard_form.setVisible(False)
        self._pairing_view.setVisible(True)

    # ------------------------------------------------------------------
    # On-screen keyboard wiring
    # ------------------------------------------------------------------

    def _on_keyboard_key(self, ch: str) -> None:
        field = self._active_field or self._url_input
        field.insert(ch)

    def _on_keyboard_backspace(self) -> None:
        field = self._active_field or self._url_input
        field.backspace()

    # ------------------------------------------------------------------
    # Credential submission (shared by the "Connect" button, Enter on the
    # password field, and the on-screen keyboard's Done key)
    # ------------------------------------------------------------------

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
