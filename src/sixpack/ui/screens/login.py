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

from PyQt6 import sip
from PyQt6.QtCore import QEvent, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from sixpack.discovery.scanner import scan_for_servers
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
    # Internal marshaling signal: scan_for_servers() calls its on_result
    # callback from a background thread (see sixpack.discovery.scanner's
    # module docstring), so start_pairing() hands it this signal's .emit
    # rather than _on_servers_discovered directly — emit() is safe to call
    # from any thread and Qt automatically queues delivery of the connected
    # slot onto this (GUI-thread) object's thread. _on_pairing_success below
    # uses the identical emit-then-let-Qt-marshal shape for
    # pairing_login_succeeded, and both guard the emit with sip.isdeleted()
    # first — see _deliver_scan_result's docstring for why that guard is
    # checked on THIS (background) side rather than inside the GUI-thread
    # slot, and why it's kept despite not being provably airtight.
    _scan_completed = pyqtSignal(list)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._pairing_server: PairingServer | None = None
        # Which QLineEdit the on-screen keyboard currently types into.
        # Updated via eventFilter's FocusIn handling below (a real click/
        # Select on a field), and explicitly reset to the URL field whenever
        # the keyboard-fallback view is (re)shown.
        self._active_field: QLineEdit | None = None
        self._discovered_servers: list[str] = []
        # Whether the discovered-servers list currently owns "logical"
        # focus (real Qt focus stays on self; keyPressEvent handles
        # SELECT/UP/DOWN directly — mirrors the pairing-view branch's
        # self.setFocus() pattern below).
        self._discovered_focus_active: bool = False
        self._scan_completed.connect(self._on_servers_discovered)
        self._build_ui()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

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

        self._pairing_url_label = QLabel("")
        self._pairing_url_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._pairing_url_label.setWordWrap(True)
        self._pairing_url_label.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: {theme.FONT_META}pt;"
        )
        layout.addWidget(self._pairing_url_label)

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

        self._discovered_list_container = QWidget()
        self._discovered_list_layout = QVBoxLayout(self._discovered_list_container)
        self._discovered_list_layout.setSpacing(6)
        self._discovered_list_layout.setContentsMargins(0, 0, 0, 12)
        self._discovered_buttons: list[QPushButton] = []
        self._discovered_focus_index = 0
        self._discovered_list_container.setVisible(False)
        outer.addWidget(self._discovered_list_container)

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

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._pairing_view.isVisible():
            self.setFocus()
        else:
            self._url_input.setFocus()

    def keyPressEvent(self, event) -> None:
        from sixpack.input.actions import InputAction
        from sixpack.input.keyboard import key_to_action

        action = key_to_action(event.key())

        if self._pairing_view.isVisible():
            if action == InputAction.SELECT:
                self._use_keyboard_fallback()
                return
            super().keyPressEvent(event)
            return

        # Keyboard-fallback view. The 3 QLineEdits keep real Qt focus and
        # their own native text-editing behavior (Left/Right = cursor
        # move, Enter = advance via the existing returnPressed chain) —
        # this screen only needs to handle moving focus UP/DOWN *between*
        # the fields and into/out of the keyboard widget. Once
        # self._keyboard itself holds real focus, it owns its own D-pad
        # navigation entirely (per its established focus-ownership
        # design from Task 3) and this method is not involved again
        # until the user exits it (Back, wired to _use_pairing_view) or
        # a genuinely unmapped key falls through to here.
        #
        # The discovered-servers list sits above the fields and is
        # navigated the same way as the pairing view above: its buttons
        # are NoFocus (matching every other sub-widget pattern in this
        # app), so they never appear as QApplication.focusWidget() — real
        # Qt focus stays on self and self._discovered_focus_active tracks
        # whether the list currently owns "logical" focus.
        if self._discovered_focus_active:
            if action == InputAction.DOWN:
                if self._discovered_focus_index + 1 < len(self._discovered_buttons):
                    self._discovered_focus_index += 1
                    self._reflect_discovered_focus()
                else:
                    self._discovered_focus_active = False
                    self._reflect_discovered_focus()
                    self._url_input.setFocus()
                return
            if action == InputAction.UP and self._discovered_focus_index > 0:
                self._discovered_focus_index -= 1
                self._reflect_discovered_focus()
                return
            if action == InputAction.SELECT:
                self._select_discovered_server(self._discovered_focus_index)
                return
            super().keyPressEvent(event)
            return

        focused = QApplication.focusWidget()
        fields = [self._url_input, self._user_input, self._pass_input]
        if focused in fields:
            idx = fields.index(focused)
            if action == InputAction.DOWN:
                if idx + 1 < len(fields):
                    fields[idx + 1].setFocus()
                else:
                    self._keyboard.setFocus()
                return
            if action == InputAction.UP:
                if idx > 0:
                    fields[idx - 1].setFocus()
                elif self._discovered_buttons:
                    # Back up out of the fields into the discovered list —
                    # the mirror image of the DOWN-past-the-last-button
                    # transition above.
                    self._discovered_focus_active = True
                    self._discovered_focus_index = len(self._discovered_buttons) - 1
                    self._reflect_discovered_focus()
                    self.setFocus()
                return
        super().keyPressEvent(event)

    def eventFilter(self, obj, event) -> bool:
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
        bind a local port. Automatically issues a fresh code shortly after
        this one's TTL elapses, so a TV left on this screen doesn't strand
        a later visitor with an already-expired code and no way to get a
        new one.
        """
        self.stop_pairing()  # defensive: never leak a prior server
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
            # Discovery is still useful here even though the phone-pairing
            # server itself couldn't bind: the keyboard-fallback view (the
            # only surface reachable in this branch) gets a populated list
            # once the scan completes. _on_servers_discovered() skips the
            # PairingServer.set_discovered_servers() call on its own since
            # self._pairing_server is None in this branch.
            scan_for_servers(self._deliver_scan_result)
            return

        self._qr_widget.set_data(self._pairing_server.pairing_url())
        self._pairing_code_label.setText(self._pairing_server.code)
        self._pairing_url_label.setText(self._pairing_server.pairing_url())
        self._pairing_view.setVisible(True)
        self._keyboard_form.setVisible(False)
        # Single scan per start_pairing() call, feeding both surfaces:
        # the phone form (via PairingServer.set_discovered_servers, inside
        # _on_servers_discovered) and this screen's own Qt list — whichever
        # is actually reachable picks up the results.
        scan_for_servers(self._deliver_scan_result)
        QTimer.singleShot(
            int(PairingServer.EXPIRY_SECONDS * 1000) + 1000,
            self._refresh_pairing_code,
        )

    def _refresh_pairing_code(self) -> None:
        if self._pairing_server is None:
            return  # user already left this flow (fallback / success / screen torn down)
        self.start_pairing()

    def stop_pairing(self) -> None:
        """Tear down the pairing server, if one is running. Idempotent."""
        if self._pairing_server is not None:
            self._pairing_server.stop()
            self._pairing_server = None

    def _on_pairing_success(self, url: str, username: str, token: str) -> None:
        # Called from PairingServer's background HTTP-server thread
        # (do_POST calls server.on_success(...) synchronously, before
        # sending the HTTP response — confirmed in pairing/server.py).
        #
        # When stop_pairing() is what tears the server down, there's no
        # race here at all: it calls HTTPServer.shutdown() before
        # server_close()/join(), and shutdown() blocks the calling (GUI)
        # thread *unconditionally* — no timeout — until serve_forever()'s
        # loop has fully returned, which can't happen while a do_POST
        # (and therefore this callback) is still in flight. So the GUI
        # thread cannot proceed to tear this screen down until any
        # in-flight call to this method has already completed; the
        # thread.join(timeout=2.0) that follows is just cleanup of an
        # already-finished thread, not a race-defining deadline.
        #
        # The real exposure is different: nothing guarantees stop_pairing()
        # is called before this widget is deleted in the first place.
        # It's only invoked from a handful of call sites in app.py
        # (successful/failed libraries load, MainWindow.closeEvent); a
        # test that constructs/destroys a LoginScreen without going
        # through those paths, an abrupt process kill, or a future code
        # path that forgets to call it would all leave the daemon
        # PairingServer thread running independently of this screen's
        # lifetime — reopening the same window _deliver_scan_result
        # guards against: a background thread touching this
        # (possibly-deleted) QObject. Same guard, same reasoning — see
        # _deliver_scan_result's docstring for why the check stays on
        # this side of the thread boundary rather than moving into a
        # GUI-thread slot. Kept here as cheap defense-in-depth even
        # though the common (stop_pairing()-mediated) path is already
        # race-free by construction.
        if not sip.isdeleted(self):
            self.pairing_login_succeeded.emit(url, username, token)

    def _use_keyboard_fallback(self) -> None:
        self._pairing_view.setVisible(False)
        self._keyboard_form.setVisible(True)
        if self._discovered_buttons:
            self._discovered_focus_active = True
            self._discovered_focus_index = 0
            self._reflect_discovered_focus()
            self.setFocus()
        else:
            self._discovered_focus_active = False
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
    # LAN server discovery (shared scan feeds both the phone-pairing form
    # via PairingServer.set_discovered_servers and this Qt-native list)
    # ------------------------------------------------------------------

    def _deliver_scan_result(self, servers: list[str]) -> None:
        """scan_for_servers()'s on_result callback: invoked exactly once,
        from the scan's background thread (scanner.py provides no
        cancellation, so this can still fire well after this screen was
        torn down — e.g. the app closed shortly after start_pairing()).

        Why the check is here (background thread), not inside the
        connected slot (_on_servers_discovered, GUI thread):

        The actual crash isn't a delivery-ordering problem — Qt already
        handles that safely on its own. A QObject's destructor
        disconnects its connections and purges any already-posted events
        addressed to it, on the GUI thread, before the object is gone;
        since both that purge and slot delivery happen on the same
        (GUI) thread, they're strictly ordered and race-free by
        construction. A check inside _on_servers_discovered would be
        redundant for that reason — it would never see a deleted `self`.

        The real, reproducible crash is different: this method touching
        `self` (via `self._scan_completed`, then `.emit()`) *while* a
        concurrent GUI-thread deletion of that same `self` is actually in
        progress — a genuine cross-thread data race on the QObject's own
        internals, not a queuing/ordering issue. Verified directly: a
        tight loop emitting a signal from a background thread while
        concurrently deleting the receiver with no guard segfaults
        reliably within a few hundred iterations; the identical loop with
        `sip.isdeleted()` checked immediately before each `.emit()` (this
        code's shape) survived 2000/2000 iterations of the same race.
        Checking here, right before `.emit()`, is what actually narrows
        the window that matters — moving it to the slot would remove that
        protection without closing anything, since the slot is never
        reached when this race loses.

        This is *not* provably airtight — sip.isdeleted() and .emit() are
        still two separate operations and CPython can, in principle,
        switch threads between them — but no public Qt/sip API offers an
        atomic check-and-touch across threads, and the empirical margin
        above is large relative to how narrow the real window is. Closing
        it completely would mean giving scanner.py real
        cancellation/join semantics so no callback can fire post-teardown
        at all (out of this task's scope; see the report's note on
        scanner.py's lack of cancellation).
        """
        if not sip.isdeleted(self):
            self._scan_completed.emit(servers)

    def _on_servers_discovered(self, servers: list[str]) -> None:
        self._discovered_servers = servers
        if self._pairing_server is not None:
            self._pairing_server.set_discovered_servers(servers)
        self._rebuild_discovered_list()

    def _rebuild_discovered_list(self) -> None:
        for btn in self._discovered_buttons:
            btn.setParent(None)
        self._discovered_buttons = []
        for i, url in enumerate(self._discovered_servers):
            btn = QPushButton(url)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.clicked.connect(lambda _checked=False, idx=i: self._select_discovered_server(idx))
            self._discovered_list_layout.addWidget(btn)
            self._discovered_buttons.append(btn)
        self._discovered_list_container.setVisible(bool(self._discovered_buttons))
        if not self._discovered_buttons:
            # A rescan can empty a previously-populated list while the user
            # is logically "inside" it (e.g. a later scan finds nothing on
            # a Wi-Fi hiccup); without this, _discovered_focus_active would
            # stay True over a now-empty, invisible list — a phantom zone
            # where SELECT/UP do nothing and only DOWN escapes. Clearing it
            # here matches how the zone already correctly starts absent
            # when the list is initially empty.
            self._discovered_focus_active = False
        self._discovered_focus_index = 0
        self._reflect_discovered_focus()

    def _reflect_discovered_focus(self) -> None:
        for i, btn in enumerate(self._discovered_buttons):
            active = self._discovered_focus_active and i == self._discovered_focus_index
            border = theme.ACCENT if active else "transparent"
            btn.setStyleSheet(
                f"background: {theme.SURFACE_HIGH}; color: {theme.TEXT_PRIMARY}; "
                f"border: 2px solid {border}; border-radius: 6px; padding: 10px; "
                f"text-align: left; font-size: {theme.FONT_BODY}pt;"
            )

    def _select_discovered_server(self, index: int) -> None:
        if 0 <= index < len(self._discovered_servers):
            self._url_input.setText(self._discovered_servers[index])

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
        if not self._keyboard_form.isVisible():
            self._use_keyboard_fallback()
        self._error_label.setText(message)
        self._error_label.setVisible(True)
        self._login_btn.setEnabled(True)
        self._login_btn.setText("Connect")

    def set_prefill(self, url: str, username: str) -> None:
        self._url_input.setText(url)
        self._user_input.setText(username)
