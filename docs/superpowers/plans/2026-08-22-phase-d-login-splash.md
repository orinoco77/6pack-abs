# Phase D — Login Pairing Flow & Splash Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace SixPack's remote-unfriendly text-entry login with a phone/laptop pairing flow (pairing code + QR code, login typed on a real keyboard elsewhere on the LAN) as the primary path, keep an on-screen D-pad-navigable keyboard as an explicit fallback, and bring the splash screen's typography in line with the rest of the app's theme tokens.

**Architecture:** A new, Qt-independent `sixpack.pairing` package owns a small stdlib `http.server`-based local HTTP server: it generates a short-lived, single-use pairing code, serves a plain HTML login form at `/`, and on successful submission calls `ABSClient.login` itself (not the browser) before reporting success back. `LoginScreen` owns this server's lifecycle (start when shown, stop when left) and a new `OnScreenKeyboard` widget for the fallback path; a new `QRCodeWidget` renders the pairing URL via plain `QPainter` (no `QGraphicsEffect`, no Pillow dependency). The server's background-thread success callback crosses into the GUI thread via a plain `pyqtSignal` emission — Qt auto-queues a cross-thread signal emission to a slot owned by a GUI-thread object, so no extra marshaling code is needed.

**Tech Stack:** Python 3.12, PyQt6, `http.server`/`socketserver`/`threading`/`secrets` (stdlib), `qrcode` (new dependency), pytest + pytest-qt (headless via `QT_QPA_PLATFORM=offscreen`), `httpx` for the pairing server's own tests (already a project dependency, used here as a plain HTTP test client against a real bound port — independent of Qt).

**Spec:** `docs/superpowers/specs/2026-08-21-app-wide-cinematic-redesign-design.md` (Phase D section)

## Global Constraints

- Python ≥ 3.10 (dev/target 3.12). Line length 100 (ruff, `select = ["E","F","I","UP"]`).
- Coverage gate: `--cov-fail-under=80`.
- All Qt tests run under `QT_QPA_PLATFORM=offscreen`.
- No `QGraphicsEffect` subclass anywhere, ever — see `docs/qt-graphics-effect-crash.md`. The QR widget and on-screen keyboard's focus highlighting are plain `QPainter`/stylesheet work, matching the rest of the app.
- New dependency: `qrcode` (pure-Python core, no Pillow needed for matrix-only use — confirmed via `pip install --dry-run qrcode` showing zero transitive dependencies). Add to `pyproject.toml`'s `dependencies` list.
- Security scope (explicit, from the spec — do not over-build): LAN-only exposure, single-use short-lived pairing code, no persistent server (torn down once login completes or the screen is left). Deliberately NOT hardened further — no TLS, no rate-limiting beyond the single-use code. This is proportionate to a local network setup flow, not a general-purpose auth system; do not add scope beyond this.
- `LoginScreen`'s existing public API (`login_requested` signal, `show_error(str)`, `set_prefill(url, username)`) must keep working exactly as today — `app.py`'s existing manual-login wiring (`_on_login_requested`/`_async_login`/error handling) is unchanged by this plan. This plan only adds a new, additional way credentials can arrive at `LoginScreen`.
- Pairing server bind failure (any `OSError` from `PairingServer.start()`) must fall back to showing the on-screen-keyboard path automatically, with a brief inline note — never present a broken/blank pairing screen.
- Pairing code expiry/reuse on the SERVED HTML form must show a clear "code expired, generate a new one" state, not a generic error.
- Commit after each task. Branch: `feature/app-wide-cinematic-redesign`.

---

## File Structure

| File | Change |
|------|--------|
| `src/sixpack/pairing/__init__.py` (new) | Package marker |
| `src/sixpack/pairing/server.py` (new) | `PairingServer`, pairing-code generation/expiry, HTTP request handling, LAN-IP detection |
| `src/sixpack/ui/widgets/qr_code.py` (new) | `QRCodeWidget` — paints a QR code from `qrcode`'s matrix output |
| `src/sixpack/ui/widgets/onscreen_keyboard.py` (new) | `OnScreenKeyboard` — D-pad-navigable QWERTY-ish widget |
| `src/sixpack/ui/screens/login.py` (edit) | Pairing code + QR as primary path; explicit fallback to `OnScreenKeyboard`-driven form; Backdrop |
| `src/sixpack/ui/screens/splash.py` (edit) | Typography/spacing brought onto theme tokens |
| `src/sixpack/ui/app.py` (edit) | Start/stop pairing server lifecycle; handle `LoginScreen.pairing_login_succeeded` |
| `pyproject.toml` (edit) | Add `qrcode` dependency |
| `tests/test_pairing/test_server.py` (new) | Direct HTTP tests against a real bound `PairingServer` instance |
| `tests/test_ui/test_qr_code.py` (new) | `QRCodeWidget` tests |
| `tests/test_ui/test_onscreen_keyboard.py` (new) | `OnScreenKeyboard` tests |
| `tests/test_ui/test_screens.py` (existing file — add to it) | `LoginScreen` pairing/fallback tests |
| `tests/test_ui/test_app.py` (edit) | `MainWindow` pairing-server lifecycle wiring tests |

---

## Task 1: Pairing server core

**Files:**
- Create: `src/sixpack/pairing/__init__.py`
- Create: `src/sixpack/pairing/server.py`
- Test: `tests/test_pairing/test_server.py` — this project's test dirs are packages (confirmed: `tests/test_player/__init__.py`, `tests/test_api/__init__.py`, etc. all exist), so ALSO create an empty `tests/test_pairing/__init__.py`.

**Interfaces:**
- Produces: `PairingServer(on_success: Callable[[str, str, str], None])` — constructor takes a callback invoked with `(server_url, username, token)` on a successful pairing login. `.start() -> None` (raises `OSError` on bind failure — callers must catch this). `.stop() -> None` (idempotent — safe to call even if never started, or twice). `.code: str` (the 6-character pairing code, available after `start()`). `.port: int` (available after `start()`). `.pairing_url() -> str` (returns `f"http://{lan_ip}:{port}/?code={code}"`).

- [ ] **Step 1: Write the failing tests**

Read `tests/test_player/test_player.py` first for this project's general test-file conventions (imports, fixture style), then create `tests/test_pairing/test_server.py`:

**On mocking the outbound ABS login call:** this project's existing `respx` convention (see `tests/test_api/test_client.py`) uses `async with respx.mock(base_url=...) as mock:` inside `async def` tests. That doesn't fit cleanly here — the pairing server's login call happens on a background HTTP-server request-handling *thread* (via a synchronous `asyncio.run(...)` inside `do_POST`), triggered by a plain synchronous `httpx.post(...)` call from the test's own thread hitting the local pairing server. Rather than reasoning about whether `respx`'s mock covers a nested call on a different thread, mock `ABSClient` directly at the point `server.py` imports it, with a small fake class — simpler and avoids any cross-thread mocking ambiguity:

```python
"""Tests for the pairing HTTP server — real HTTP requests against a bound
instance, independent of Qt (per this project's Phase D spec's Testing
section)."""
from __future__ import annotations

import time
import urllib.parse

import httpx
import pytest

from sixpack.pairing import server as server_module
from sixpack.pairing.server import PairingServer


class _FakeUser:
    def __init__(self, token: str) -> None:
        self.token = token


class _FakeLoginResult:
    def __init__(self, token: str) -> None:
        self.user = _FakeUser(token)


class _FakeABSClient:
    """Stands in for sixpack.api.client.ABSClient — avoids a real network
    call and avoids reasoning about respx across the pairing server's
    background request-handling thread."""

    should_fail: bool = False
    fail_message: str = "bad credentials"
    issued_token: str = "tok123"

    def __init__(self, base_url: str, token: str = "") -> None:
        self.base_url = base_url

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return None

    async def login(self, username: str, password: str):
        if _FakeABSClient.should_fail:
            raise server_module.AuthenticationError(_FakeABSClient.fail_message)
        return _FakeLoginResult(_FakeABSClient.issued_token)


@pytest.fixture(autouse=True)
def _reset_fake_client():
    _FakeABSClient.should_fail = False
    _FakeABSClient.fail_message = "bad credentials"
    _FakeABSClient.issued_token = "tok123"
    yield


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setattr(server_module, "ABSClient", _FakeABSClient)
    results = []
    srv = PairingServer(on_success=lambda url, user, token: results.append((url, user, token)))
    srv.start()
    srv.results = results  # test-only convenience attribute
    yield srv
    srv.stop()


def test_server_starts_and_generates_code(server):
    assert len(server.code) == 6
    assert server.code.isalnum()
    assert server.port > 0


def test_pairing_url_contains_code_and_port(server):
    url = server.pairing_url()
    assert f":{server.port}" in url
    assert f"code={server.code}" in url


def test_get_with_valid_code_serves_form(server):
    resp = httpx.get(f"http://127.0.0.1:{server.port}/?code={server.code}")
    assert resp.status_code == 200
    assert "form" in resp.text.lower()
    assert server.code in resp.text  # code carried through as a hidden field


def test_get_with_invalid_code_serves_expired_page(server):
    resp = httpx.get(f"http://127.0.0.1:{server.port}/?code=WRONG1")
    assert resp.status_code == 200
    assert "expired" in resp.text.lower() or "invalid" in resp.text.lower()


def test_get_with_no_code_serves_expired_page(server):
    resp = httpx.get(f"http://127.0.0.1:{server.port}/")
    assert resp.status_code == 200
    assert "expired" in resp.text.lower() or "invalid" in resp.text.lower()


def test_post_with_valid_code_calls_on_success(server):
    body = urllib.parse.urlencode({
        "server_url": "http://abs.example.com",
        "username": "alice",
        "password": "hunter2",
        "code": server.code,
    })
    resp = httpx.post(
        f"http://127.0.0.1:{server.port}/",
        content=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200
    assert "connected" in resp.text.lower()
    assert server.results == [("http://abs.example.com", "alice", "tok123")]


def test_post_marks_code_used_after_success(server):
    body = urllib.parse.urlencode({
        "server_url": "http://abs.example.com", "username": "alice",
        "password": "x", "code": server.code,
    })
    httpx.post(f"http://127.0.0.1:{server.port}/", content=body,
               headers={"Content-Type": "application/x-www-form-urlencoded"})
    # Second attempt with the same (now-used) code must be rejected.
    resp2 = httpx.post(f"http://127.0.0.1:{server.port}/", content=body,
                        headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert "expired" in resp2.text.lower() or "invalid" in resp2.text.lower()
    assert len(server.results) == 1


def test_post_with_wrong_code_is_rejected(server):
    body = urllib.parse.urlencode({
        "server_url": "http://abs.example.com", "username": "alice",
        "password": "x", "code": "WRONG1",
    })
    resp = httpx.post(f"http://127.0.0.1:{server.port}/", content=body,
                       headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert "expired" in resp.text.lower() or "invalid" in resp.text.lower()
    assert server.results == []


def test_post_with_failed_login_does_not_consume_code(server):
    _FakeABSClient.should_fail = True
    body = urllib.parse.urlencode({
        "server_url": "http://abs.example.com", "username": "alice",
        "password": "wrong", "code": server.code,
    })
    resp = httpx.post(f"http://127.0.0.1:{server.port}/", content=body,
                       headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert resp.status_code == 200
    assert server.results == []
    # The code must still be valid for a retry — a failed login shouldn't
    # burn the user's single-use pairing code.
    resp2 = httpx.get(f"http://127.0.0.1:{server.port}/?code={server.code}")
    assert "form" in resp2.text.lower()


def test_code_expires_after_ttl(server, monkeypatch):
    # Force the code to look old without a real sleep.
    server._issued_at = time.monotonic() - server.EXPIRY_SECONDS - 1
    resp = httpx.get(f"http://127.0.0.1:{server.port}/?code={server.code}")
    assert "expired" in resp.text.lower()


def test_stop_is_idempotent():
    srv = PairingServer(on_success=lambda *a: None)
    srv.start()
    srv.stop()
    srv.stop()  # must not raise
```

`server.py` must import `ABSClient`/`AuthenticationError`/`APIError` at module level as plain names (`from sixpack.api.client import ABSClient, APIError, AuthenticationError`) so `monkeypatch.setattr(server_module, "ABSClient", _FakeABSClient)` in the test above can replace the name the module actually calls — if `server.py` instead does `from sixpack.api import client as _client_module` and calls `_client_module.ABSClient(...)`, adjust the monkeypatch target to match whatever import style you actually use, but keep it a module-level, patchable name either way.

- [ ] **Step 2: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_pairing/ -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sixpack.pairing'`.

- [ ] **Step 3: Implement**

Create `src/sixpack/pairing/__init__.py` (empty, or a one-line docstring).

Create `src/sixpack/pairing/server.py`:

```python
"""Local HTTP server for the phone/laptop pairing login flow.

Generates a short-lived, single-use pairing code. Serves a plain HTML
login form at `/` on a random local port, bound to all interfaces so it's
reachable from another device on the same LAN. On a valid submission, logs
in against the real Audiobookshelf server FROM THIS PROCESS (not the
browser) and reports the result back via a callback.

Security scope (deliberate, not an oversight — see this plan's Global
Constraints): LAN-only, single-use, short-lived code, no TLS, no
rate-limiting beyond the single-use code, no persistent server. This is
proportionate to a local network setup flow, not a general-purpose auth
system.
"""
from __future__ import annotations

import asyncio
import secrets
import socket
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable

from sixpack.api.client import ABSClient, APIError, AuthenticationError

_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I/l ambiguity
_CODE_LENGTH = 6

_FORM_PAGE = """<!doctype html>
<html><head><title>SixPack Pairing</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body {{ font-family: sans-serif; max-width: 420px; margin: 40px auto; padding: 0 16px; }}
input {{ display: block; width: 100%; padding: 10px; margin: 8px 0; box-sizing: border-box; }}
button {{ padding: 10px 24px; }}
</style></head>
<body>
<h2>Connect SixPack</h2>
<form method="post" action="/">
  <input type="text" name="server_url" placeholder="Server URL (e.g. http://192.168.1.10:13378)" required>
  <input type="text" name="username" placeholder="Username" required>
  <input type="password" name="password" placeholder="Password" required>
  <input type="hidden" name="code" value="{code}">
  <button type="submit">Connect</button>
</form>
</body></html>"""

_EXPIRED_PAGE = """<!doctype html>
<html><head><title>SixPack Pairing</title></head>
<body><h2>This pairing code has expired or is invalid</h2>
<p>Go back to the TV and select "Pair a new device" to get a fresh code.</p>
</body></html>"""

_SUCCESS_PAGE = """<!doctype html>
<html><head><title>SixPack Pairing</title></head>
<body><h2>Connected!</h2>
<p>You can return to the TV now.</p>
</body></html>"""

_ERROR_PAGE = """<!doctype html>
<html><head><title>SixPack Pairing</title></head>
<body><h2>Login failed</h2>
<p>{message}</p>
<p><a href="/?code={code}">Try again</a></p>
</body></html>"""


def _lan_ip() -> str:
    """Best-effort LAN-reachable IP for this machine. Doesn't actually send
    any packets — connecting a UDP socket just makes the OS pick the right
    outbound interface/IP for that route."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"


class _Handler(BaseHTTPRequestHandler):
    # Silence BaseHTTPRequestHandler's default per-request stderr logging —
    # this is a short-lived local server, not something that needs an
    # access log.
    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass

    def do_GET(self) -> None:  # noqa: N802 — stdlib-mandated method name
        server: PairingServer = self.server.pairing_server  # type: ignore[attr-defined]
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        code = (query.get("code") or [""])[0]
        if server.is_code_valid(code):
            self._respond(200, _FORM_PAGE.format(code=server.code))
        else:
            self._respond(200, _EXPIRED_PAGE)

    def do_POST(self) -> None:  # noqa: N802
        server: PairingServer = self.server.pairing_server  # type: ignore[attr-defined]
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        fields = urllib.parse.parse_qs(body)
        code = (fields.get("code") or [""])[0]
        server_url = (fields.get("server_url") or [""])[0].strip()
        username = (fields.get("username") or [""])[0].strip()
        password = (fields.get("password") or [""])[0]

        if not server.is_code_valid(code):
            self._respond(200, _EXPIRED_PAGE)
            return

        try:
            token = asyncio.run(self._login(server_url, username, password))
        except (AuthenticationError, APIError, Exception) as exc:  # noqa: BLE001
            self._respond(200, _ERROR_PAGE.format(message=str(exc), code=server.code))
            return

        server.mark_used()
        server.on_success(server_url, username, token)
        self._respond(200, _SUCCESS_PAGE)

    @staticmethod
    async def _login(server_url: str, username: str, password: str) -> str:
        async with ABSClient(server_url) as client:
            result = await client.login(username, password)
            return result.user.token

    def _respond(self, status: int, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class PairingServer:
    """Owns the local HTTP server's lifecycle for one pairing session."""

    EXPIRY_SECONDS = 600.0

    def __init__(self, on_success: Callable[[str, str, str], None]) -> None:
        self.on_success = on_success
        self.code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))
        self.port = 0
        self._issued_at = time.monotonic()
        self._used = False
        self._httpd: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._httpd = HTTPServer(("0.0.0.0", 0), _Handler)
        self._httpd.pairing_server = self  # type: ignore[attr-defined]
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def is_code_valid(self, code: str) -> bool:
        if self._used or not code or code != self.code:
            return False
        return (time.monotonic() - self._issued_at) < self.EXPIRY_SECONDS

    def mark_used(self) -> None:
        self._used = True

    def pairing_url(self) -> str:
        return f"http://{_lan_ip()}:{self.port}/?code={self.code}"
```

Check `_Handler.do_GET`/`do_POST`'s exact interaction with `ABSClient`'s constructor/context-manager (`ABSClient(server_url)`, `async with ... as client: await client.login(...)`) against the REAL current `src/sixpack/api/client.py` before finalizing — this sample was written against that file's current shape, but confirm field/method names match exactly (`client.login(username, password)` returning an object with `.user.token`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_pairing/ -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` (3 times)
Expected: all passing, coverage ≥80%.

- [ ] **Step 6: Commit**

```bash
git add src/sixpack/pairing/ tests/test_pairing/
git commit -m "Add pairing HTTP server: short-lived single-use code, plain-HTML login form"
```

---

## Task 2: QR code widget

**Files:**
- Create: `src/sixpack/ui/widgets/qr_code.py`
- Test: `tests/test_ui/test_qr_code.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: `QRCodeWidget(parent=None)` — a `QWidget`. `.set_data(data: str) -> None` builds and stores the QR matrix, triggers a repaint.

- [ ] **Step 1: Add the `qrcode` dependency**

In `pyproject.toml`, add `"qrcode>=7.4.2"` to the `dependencies` list (alongside `PyQt6`, `python-mpv`, `httpx`, `pydantic`). Run `.venv/bin/pip install qrcode` (or `.venv/bin/pip install -e .` to pick it up via the project's own dependency list, whichever this project's existing dev workflow uses — check for a `requirements`-style install script or just confirm `pip install qrcode` alone is sufficient for local dev, matching how other dependencies were presumably installed).

- [ ] **Step 2: Write the failing tests**

Create `tests/test_ui/test_qr_code.py`:

```python
"""Tests for QRCodeWidget."""
from __future__ import annotations

from sixpack.ui.widgets.qr_code import QRCodeWidget


def test_qr_code_widget_creates(qtbot):
    widget = QRCodeWidget()
    qtbot.addWidget(widget)
    assert widget is not None


def test_set_data_builds_matrix(qtbot):
    widget = QRCodeWidget()
    qtbot.addWidget(widget)
    widget.set_data("http://192.168.1.10:8080/?code=ABC123")
    assert widget._matrix
    assert len(widget._matrix) > 0
    assert all(len(row) == len(widget._matrix) for row in widget._matrix)  # QR matrices are square


def test_set_data_empty_string_does_not_crash(qtbot):
    widget = QRCodeWidget()
    qtbot.addWidget(widget)
    widget.set_data("")  # qrcode raises on empty data internally — confirm this is handled gracefully
```

For the last test, check `qrcode.QRCode.add_data("")`'s actual behavior (it may raise or may silently produce an empty/minimal code) before deciding what "handled gracefully" means precisely — either "doesn't crash the widget, matrix stays empty" or "raises a specific, documented exception the caller is expected to avoid triggering (i.e. callers must not call `set_data('')`)" are both acceptable outcomes; pick whichever matches `qrcode`'s real behavior and write the test to match reality rather than an assumption.

- [ ] **Step 3: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_qr_code.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 4: Implement**

Create `src/sixpack/ui/widgets/qr_code.py`:

```python
"""QR-code widget — plain QPainter rendering from qrcode's matrix output.

Deliberately not a QGraphicsEffect — see docs/qt-graphics-effect-crash.md.
Renders black-on-white regardless of the app's dark theme: QR scanners
expect strong, standard dark-on-light contrast, and most phone camera
apps are tuned for it — matching the app's theme here would hurt
scannability for no benefit.
"""
from __future__ import annotations

import qrcode
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QWidget


class QRCodeWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._matrix: list[list[bool]] = []

    def set_data(self, data: str) -> None:
        qr = qrcode.QRCode(border=2)
        qr.add_data(data)
        qr.make(fit=True)
        self._matrix = qr.get_matrix()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: ARG002
        try:
            painter = QPainter(self)
            painter.fillRect(self.rect(), QColor("white"))
            if self._matrix:
                size = len(self._matrix)
                module_px = min(self.width(), self.height()) / size
                painter.setPen(QColor("black"))
                painter.setBrush(QColor("black"))
                for row_idx, row in enumerate(self._matrix):
                    for col_idx, is_dark in enumerate(row):
                        if is_dark:
                            x = int(col_idx * module_px)
                            y = int(row_idx * module_px)
                            side = int(module_px) + 1  # +1 avoids sub-pixel seams
                            painter.drawRect(x, y, side, side)
            painter.end()
        except RuntimeError:
            # Widget was deleted on the C++ side during teardown; skip painting.
            pass
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_qr_code.py -v`
Expected: PASS.

- [ ] **Step 6: Run the full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` (3 times)
Expected: all passing, coverage ≥80%.

- [ ] **Step 7: Commit**

```bash
git add src/sixpack/ui/widgets/qr_code.py tests/test_ui/test_qr_code.py pyproject.toml
git commit -m "Add QRCodeWidget: plain QPainter rendering of qrcode's matrix output"
```

---

## Task 3: On-screen keyboard widget

**Files:**
- Create: `src/sixpack/ui/widgets/onscreen_keyboard.py`
- Test: `tests/test_ui/test_onscreen_keyboard.py`

**Interfaces:**
- Produces: `OnScreenKeyboard(parent=None)` — a `QWidget`, `Qt.FocusPolicy.StrongFocus`. Signals: `key_pressed = pyqtSignal(str)` (a single character — letter, digit, or space), `backspace_pressed = pyqtSignal()`, `done_pressed = pyqtSignal()`, `back_requested = pyqtSignal()`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ui/test_onscreen_keyboard.py`:

```python
"""Tests for OnScreenKeyboard — D-pad-navigable text entry."""
from __future__ import annotations

from PyQt6.QtCore import Qt

from sixpack.ui.widgets.onscreen_keyboard import OnScreenKeyboard


def test_creates(qtbot):
    kb = OnScreenKeyboard()
    qtbot.addWidget(kb)
    assert kb is not None


def test_select_on_default_focus_emits_first_key(qtbot):
    kb = OnScreenKeyboard()
    qtbot.addWidget(kb)
    kb.show()
    qtbot.waitExposed(kb)
    received = []
    kb.key_pressed.connect(received.append)
    qtbot.keyClick(kb, Qt.Key.Key_Return)
    assert received == ["1"]  # top-left key, per the row layout


def test_right_then_select_emits_second_key(qtbot):
    kb = OnScreenKeyboard()
    qtbot.addWidget(kb)
    kb.show()
    qtbot.waitExposed(kb)
    received = []
    kb.key_pressed.connect(received.append)
    qtbot.keyClick(kb, Qt.Key.Key_Right)
    qtbot.keyClick(kb, Qt.Key.Key_Return)
    assert received == ["2"]


def test_down_moves_to_letter_row(qtbot):
    kb = OnScreenKeyboard()
    qtbot.addWidget(kb)
    kb.show()
    qtbot.waitExposed(kb)
    received = []
    kb.key_pressed.connect(received.append)
    qtbot.keyClick(kb, Qt.Key.Key_Down)
    qtbot.keyClick(kb, Qt.Key.Key_Return)
    assert received == ["q"]


def test_back_emits_back_requested(qtbot):
    kb = OnScreenKeyboard()
    qtbot.addWidget(kb)
    kb.show()
    qtbot.waitExposed(kb)
    with qtbot.waitSignal(kb.back_requested, timeout=1000):
        qtbot.keyClick(kb, Qt.Key.Key_Escape)


def test_navigating_to_bottom_row_and_selecting_backspace(qtbot):
    kb = OnScreenKeyboard()
    qtbot.addWidget(kb)
    kb.show()
    qtbot.waitExposed(kb)
    for _ in range(4):
        qtbot.keyClick(kb, Qt.Key.Key_Down)  # from row 0 down to the bottom row
    # Move right from the space key to the backspace key — exact column
    # count depends on the bottom row's layout, verify against your own
    # _build_ui implementation and adjust the number of Right presses here
    # to land on backspace, not guess it.
    with qtbot.waitSignal(kb.backspace_pressed, timeout=1000):
        qtbot.keyClick(kb, Qt.Key.Key_Right)
        qtbot.keyClick(kb, Qt.Key.Key_Return)
```

The last test's exact navigation path depends on your own bottom-row column layout — read your `_build_ui` implementation once it exists and adjust the `Right` press count so the test reaches the backspace key deterministically, rather than guessing.

- [ ] **Step 2: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_onscreen_keyboard.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

Create `src/sixpack/ui/widgets/onscreen_keyboard.py`:

```python
"""D-pad-navigable on-screen QWERTY-ish keyboard — fallback text-entry
method for LoginScreen when the pairing flow isn't used. This screen (not
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


class OnScreenKeyboard(QWidget):
    key_pressed = pyqtSignal(str)
    backspace_pressed = pyqtSignal()
    done_pressed = pyqtSignal()
    back_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._grid: list[list[QPushButton | None]] = []
        self._focused_row = 0
        self._focused_col = 0
        self._build_ui()
        self._reflect_focus()

    def _make_key(self, label: str, width: int, on_click) -> QPushButton:
        btn = QPushButton(label)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setFixedSize(width, 48)
        btn.clicked.connect(on_click)
        return btn

    def _build_ui(self) -> None:
        layout = QGridLayout(self)
        layout.setSpacing(6)

        for row_idx, chars in enumerate(_ROWS):
            row_buttons: list[QPushButton | None] = []
            for col_idx, ch in enumerate(chars):
                btn = self._make_key(ch, 48, lambda _checked=False, c=ch: self.key_pressed.emit(c))
                layout.addWidget(btn, row_idx, col_idx)
                row_buttons.append(btn)
            self._grid.append(row_buttons)

        bottom_row_idx = len(_ROWS)
        space_btn = self._make_key("Space", 220, lambda: self.key_pressed.emit(" "))
        layout.addWidget(space_btn, bottom_row_idx, 0, 1, 5)
        back_btn = self._make_key("⌫", 48, lambda: self.backspace_pressed.emit())
        layout.addWidget(back_btn, bottom_row_idx, 5)
        done_btn = self._make_key("Done", 100, lambda: self.done_pressed.emit())
        layout.addWidget(done_btn, bottom_row_idx, 6, 1, 2)
        # Bottom row occupies grid columns 0-7; only columns 0, 5, and 6
        # host a real button (the others are spanned-over by the wide
        # space/done buttons) — None marks the non-button columns so
        # _move_focus's column-clamping/nearest-button search works the
        # same way it does for the letter rows above.
        self._grid.append([space_btn, None, None, None, None, back_btn, done_btn, None])

    def _reflect_focus(self) -> None:
        focused = self._grid[self._focused_row][self._focused_col]
        for row in self._grid:
            for btn in row:
                if btn is None:
                    continue
                border = theme.ACCENT if btn is focused else "transparent"
                btn.setStyleSheet(
                    f"background: {theme.SURFACE_HIGH}; color: {theme.TEXT_PRIMARY}; "
                    f"border: 2px solid {border}; border-radius: 6px; "
                    f"font-size: {theme.FONT_BODY}pt;"
                )

    def _move_focus(self, row: int, col: int) -> None:
        row = max(0, min(row, len(self._grid) - 1))
        row_buttons = self._grid[row]
        col = max(0, min(col, len(row_buttons) - 1))
        if row_buttons[col] is None:
            for offset in range(1, len(row_buttons)):
                if col - offset >= 0 and row_buttons[col - offset] is not None:
                    col -= offset
                    break
                if col + offset < len(row_buttons) and row_buttons[col + offset] is not None:
                    col += offset
                    break
        self._focused_row, self._focused_col = row, col
        self._reflect_focus()

    def keyPressEvent(self, event) -> None:
        from sixpack.input.keyboard import key_to_action
        from sixpack.input.actions import InputAction

        action = key_to_action(event.key())
        if action == InputAction.BACK:
            self.back_requested.emit()
        elif action == InputAction.SELECT:
            btn = self._grid[self._focused_row][self._focused_col]
            if btn is not None:
                btn.click()
        elif action == InputAction.UP:
            self._move_focus(self._focused_row - 1, self._focused_col)
        elif action == InputAction.DOWN:
            self._move_focus(self._focused_row + 1, self._focused_col)
        elif action == InputAction.LEFT:
            self._move_focus(self._focused_row, self._focused_col - 1)
        elif action == InputAction.RIGHT:
            self._move_focus(self._focused_row, self._focused_col + 1)
        else:
            super().keyPressEvent(event)
```

Double-check the bottom row's column math (`space_btn` spanning columns 0-4, `back_btn` at column 5, `done_btn` spanning 6-7) against what `QGridLayout`'s `addWidget(widget, row, col, rowSpan, colSpan)` actually produces, and against the `self._grid.append([...])` list's column indices — these must agree for `_move_focus`'s column-based navigation to land on the right button. Adjust the test in Step 1 (`test_navigating_to_bottom_row_and_selecting_backspace`) to match whatever exact layout you end up with.

- [ ] **Step 4: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_onscreen_keyboard.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` (3 times)
Expected: all passing, coverage ≥80%.

- [ ] **Step 6: Commit**

```bash
git add src/sixpack/ui/widgets/onscreen_keyboard.py tests/test_ui/test_onscreen_keyboard.py
git commit -m "Add OnScreenKeyboard: D-pad-navigable QWERTY-ish text entry"
```

---

## Task 4: LoginScreen redesign — pairing primary path + keyboard fallback

**Files:**
- Modify: `src/sixpack/ui/screens/login.py`
- Test: `tests/test_ui/test_screens.py` — this project's existing `LoginScreen` tests already live in this shared file (confirmed via `grep -rln LoginScreen tests/`), not a dedicated `test_login_screen.py`. Add your new tests there, near the existing `LoginScreen` tests, matching that file's established style.

**Interfaces:**
- Consumes: `PairingServer` (Task 1), `QRCodeWidget` (Task 2), `OnScreenKeyboard` (Task 3), `Backdrop` (existing, `src/sixpack/ui/widgets/backdrop.py`).
- Produces: `LoginScreen`'s existing public API is preserved unchanged (`login_requested = pyqtSignal(str, str, str)`, `show_error(str)`, `set_prefill(url, username)`). New: `pairing_login_succeeded = pyqtSignal(str, str, str)` (url, username, token) — emitted when the pairing server's background thread reports success (see below for the cross-thread note). New: `start_pairing() -> None` / `stop_pairing() -> None` — lifecycle methods `app.py` calls (Task 5) when navigating to/away from this screen.

- [ ] **Step 1: Read the current `src/sixpack/ui/screens/login.py` in full** (reproduced in this plan's earlier investigation, but re-read the live file — it may have drifted) and grep `tests/` for any existing `LoginScreen` test file to extend rather than duplicate.

- [ ] **Step 2: Write the failing tests**

Add to `tests/test_ui/test_screens.py`, near the existing `LoginScreen` tests:

```python
"""Tests for LoginScreen's pairing flow and on-screen-keyboard fallback."""
from __future__ import annotations

from PyQt6.QtCore import Qt

from sixpack.ui.screens.login import LoginScreen


def test_starts_on_pairing_view_by_default(qtbot):
    screen = LoginScreen()
    qtbot.addWidget(screen)
    screen.start_pairing()
    try:
        assert screen._qr_widget.isVisible()
        assert screen._pairing_server is not None
    finally:
        screen.stop_pairing()


def test_stop_pairing_tears_down_server(qtbot):
    screen = LoginScreen()
    qtbot.addWidget(screen)
    screen.start_pairing()
    server = screen._pairing_server
    screen.stop_pairing()
    assert screen._pairing_server is None
    # The underlying HTTPServer must actually be torn down, not just
    # dereferenced — confirm the port is no longer accepting connections.
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        result = s.connect_ex(("127.0.0.1", server.port))
        assert result != 0  # connection refused/failed — server is down


def test_pairing_success_emits_pairing_login_succeeded(qtbot):
    screen = LoginScreen()
    qtbot.addWidget(screen)
    screen.start_pairing()
    try:
        with qtbot.waitSignal(screen.pairing_login_succeeded, timeout=2000) as blocker:
            # Simulate the pairing server's background-thread callback —
            # call it exactly the way PairingServer would (see how
            # start_pairing wires PairingServer(on_success=...) to confirm
            # you're calling the right method/signal here).
            screen._pairing_server.on_success("http://abs.test", "alice", "tok123")
        assert blocker.args == ["http://abs.test", "alice", "tok123"]
    finally:
        screen.stop_pairing()


def test_use_remote_instead_switches_to_keyboard_form(qtbot):
    screen = LoginScreen()
    qtbot.addWidget(screen)
    screen.start_pairing()
    try:
        screen._use_keyboard_fallback()
        assert screen._keyboard_form.isVisible()
        assert not screen._qr_widget.isVisible()
    finally:
        screen.stop_pairing()


def test_keyboard_fallback_typing_and_submit_emits_login_requested(qtbot):
    screen = LoginScreen()
    qtbot.addWidget(screen)
    screen.start_pairing()
    try:
        screen._use_keyboard_fallback()
        # Adjust these calls to match your actual field-targeting API —
        # the on-screen keyboard needs to know which QLineEdit is
        # "active" and append characters to it; the exact mechanism
        # (explicit field-switching action, or a simple "active field"
        # attribute cycled via Tab-equivalent) is this task's own design
        # choice, not specified further here.
        screen._url_input.setText("http://abs.test:13378")
        screen._user_input.setText("alice")
        screen._pass_input.setText("hunter2")

        signals = []
        screen.login_requested.connect(lambda *a: signals.append(a))
        screen._keyboard.done_pressed.emit()
        assert signals == [("http://abs.test:13378", "alice", "hunter2")]
    finally:
        screen.stop_pairing()


def test_show_error_still_works_unchanged(qtbot):
    screen = LoginScreen()
    qtbot.addWidget(screen)
    screen.show_error("Login failed: bad credentials")
    # This is the EXISTING show_error contract — must still work exactly
    # as before this task's changes, regardless of which view (pairing or
    # keyboard fallback) is currently showing.


def test_set_prefill_still_works_unchanged(qtbot):
    screen = LoginScreen()
    qtbot.addWidget(screen)
    screen.set_prefill("http://abs.test", "alice")
    assert screen._url_input.text() == "http://abs.test"
    assert screen._user_input.text() == "alice"
```

Adapt the exact internal attribute names (`_qr_widget`, `_pairing_server`, `_keyboard_form`, `_keyboard`) to whatever you actually build in Step 3 — these are illustrative of the required behavior (pairing view by default, explicit fallback switch, working teardown, existing API preserved), not literal names to force onto your implementation if a cleaner name occurs to you. Keep the test file internally consistent with whatever names you choose.

- [ ] **Step 3: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_screens.py -k login -v`
Expected: FAIL.

- [ ] **Step 4: Implement**

Rebuild `_build_ui` and add the new methods. Key structural requirements (exact widget tree/styling is your call, following the established `Backdrop`-behind-everything pattern from `detail_grid.py`/`chapter_select.py`/`player.py`):

- A `Backdrop` behind the whole screen (reuse as-is; this screen has no per-item cover art, so a static/neutral backdrop color via `Backdrop.show_color(...)` is enough — check `Backdrop`'s API for the simplest "just show something, no image" call).
- Two mutually-exclusive views inside the screen, toggled via visibility (not separate screens in the app's `QStackedWidget` — this stays one `LoginScreen`):
  - **Pairing view** (default): the pairing code (large text), a `QRCodeWidget` fed `self._pairing_server.pairing_url()`, a short instruction line, and an explicit "Use the remote instead" button/action that calls `self._use_keyboard_fallback()`.
  - **Keyboard-fallback view**: the existing three `QLineEdit` fields (URL/username/password) plus an `OnScreenKeyboard` instance below them. Wire the keyboard's `key_pressed`/`backspace_pressed` signals to append/remove characters from whichever field is currently "active" (decide and implement a simple active-field mechanism — e.g. clicking/selecting a field marks it active, or a fixed forward-only field order advanced by the keyboard's own Done/Tab-equivalent action; this is a real but small design choice left to you, consistent with how earlier phases of this plan left comparable small UI-flow choices to implementation). Wire `done_pressed` to trigger the same validation/emit logic `_on_connect` already has (reuse `_on_connect` directly if the three `QLineEdit`s are the same instances, just now also fillable via the on-screen keyboard instead of a real keyboard — don't duplicate the validation logic).
- `start_pairing()`: construct `self._pairing_server = PairingServer(on_success=self._on_pairing_success)`, try `self._pairing_server.start()`; on `OSError` (bind failure), per this plan's Global Constraints, fall back automatically: set `self._pairing_server = None`, show a brief inline note (e.g. a small status label: "Pairing unavailable — use the remote to connect"), and call `self._use_keyboard_fallback()` instead of showing the (now broken) pairing view. On success, update the QR widget and code label, show the pairing view.
- `stop_pairing()`: if `self._pairing_server` is not None, call `.stop()` and set it to `None`. Idempotent (safe to call when already stopped/never started).
- `_on_pairing_success(self, url: str, username: str, token: str) -> None`: this is what `PairingServer`'s `on_success` callback invokes — from the SERVER'S BACKGROUND THREAD, not the GUI thread. Simply do `self.pairing_login_succeeded.emit(url, username, token)` — Qt automatically queues a signal emission to a slot connected on a different thread than the emitting thread, as long as the receiving object (this `LoginScreen` instance, and whatever `app.py` connects to this signal in Task 5) lives on the GUI thread, which it does. Do NOT attempt any other thread-marshaling mechanism (`QMetaObject.invokeMethod`, etc.) — plain `pyqtSignal.emit()` from a background thread is the standard, safe Qt pattern here, and matches how this codebase already marshals mpv-thread callbacks in `player.py` conceptually (though that file uses `QMetaObject.invokeMethod` explicitly for methods with typed positional args across a C-extension boundary — a plain Python `pyqtSignal` doesn't need that machinery; confirm this reasoning holds by testing it, per this task's Step 2 test, rather than assuming).
- `_use_keyboard_fallback(self) -> None`: hides the pairing view, shows the keyboard-fallback view, gives the URL field initial focus/active-field status.

- [ ] **Step 5: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_screens.py -k login -v`
Expected: PASS.

- [ ] **Step 6: Run the full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` (3 times)
Expected: all passing, coverage ≥80%.

- [ ] **Step 7: Commit**

```bash
git add src/sixpack/ui/screens/login.py tests/test_ui/test_screens.py
git commit -m "Redesign LoginScreen: pairing code/QR primary path, on-screen-keyboard fallback"
```

---

## Task 5: `app.py` wiring — pairing server lifecycle

**Files:**
- Modify: `src/sixpack/ui/app.py`
- Test: `tests/test_ui/test_app.py`

**Interfaces:**
- Consumes: `LoginScreen.pairing_login_succeeded` (Task 4), `LoginScreen.start_pairing()`/`stop_pairing()` (Task 4).
- Produces: `MainWindow._on_pairing_login_succeeded(url: str, username: str, token: str) -> None`.

- [ ] **Step 1: Read `app.py`'s current `_show_login`, `_try_autologin`, `_on_login_requested`, `_on_result`'s `"login"`/`"libraries"`/`"autologin"` branches, and `closeEvent`** — confirm exactly how a successful manual login today ends up saving the token (`ServerConfig`/`AppConfig.add_or_update_server`/`.save()`) and proceeding to browse, since the pairing success path needs to do the same thing, not a parallel/duplicate mechanism.

- [ ] **Step 2: Write the failing test**

Add to `tests/test_ui/test_app.py` (using the `window` fixture from an earlier phase's task, if present — check the file's current fixtures first):

```python
def test_pairing_login_succeeded_saves_token_and_proceeds(window, qtbot, monkeypatch):
    """The pairing flow's success path must save the token via the same
    AppConfig/ServerConfig mechanism manual login uses, and proceed to
    fetch libraries / show browse — matching _on_login_requested's
    existing successful-login behavior, not a parallel path."""
    saved = []
    monkeypatch.setattr(window._config, "add_or_update_server", lambda cfg: saved.append(cfg))
    monkeypatch.setattr(window._config, "save", lambda: None)

    window._login_screen.pairing_login_succeeded.emit("http://abs.test", "alice", "tok123")

    assert len(saved) == 1
    assert saved[0].url == "http://abs.test"
    assert saved[0].token == "tok123"
    assert saved[0].username == "alice"


def test_show_login_starts_pairing_server(window):
    calls = []
    window._login_screen.start_pairing = lambda: calls.append(True)
    window._show_login()
    assert calls == [True]


def test_leaving_login_screen_stops_pairing_server(window):
    calls = []
    window._login_screen.stop_pairing = lambda: calls.append(True)
    window._show_browse()
    assert calls == [True]
```

The exact assertion in the third test (`_show_browse` stopping pairing) is illustrative — check where in the real code the transition AWAY from login actually happens (likely inside the `_on_result` `"libraries"`/`"autologin"` success branch, not `_show_browse()` itself, since `_show_browse` might be called from other places too that shouldn't imply "login just succeeded") and adjust the test to target the real call site.

- [ ] **Step 3: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_app.py -v -k pairing`
Expected: FAIL.

- [ ] **Step 4: Implement**

In `_build_ui`'s signal-wiring block, alongside `self._login_screen.login_requested.connect(self._on_login_requested)`, add:

```python
self._login_screen.pairing_login_succeeded.connect(self._on_pairing_login_succeeded)
```

In `_show_login`, start the pairing server:

```python
def _show_login(self) -> None:
    self._login_screen.start_pairing()
    self._stack.setCurrentWidget(self._login_screen)
```

Find the real call site(s) where the app transitions AWAY from the login screen after a successful login (read `_on_result`'s `"libraries"`/`"autologin"` branches, which currently call `self._show_browse()` on success) and add `self._login_screen.stop_pairing()` there, guarded so it's a no-op if pairing was never started (per Task 4's idempotent `stop_pairing()`).

Add the new handler, reusing the exact save/proceed logic `_on_login_requested`'s success path already establishes (check `_on_result`'s `"login"` branch for the precise `ServerConfig`/`AppConfig` construction to mirror — don't invent a different shape):

```python
def _on_pairing_login_succeeded(self, url: str, username: str, token: str) -> None:
    self._server_url = url
    self._token = token
    self._client = ABSClient(url, token=token)
    self._config.add_or_update_server(
        ServerConfig(name=url, url=url, token=token, username=username)
    )
    self._config.save()
    self._worker.run("libraries", self._async_get_libraries())
```

Verify this matches the real `_on_result`'s `"login"` branch's `ServerConfig` construction field-for-field (the plan text above is illustrative based on this plan's earlier investigation of the live file — confirm against the actual current code before finalizing, since `app.py` may have changed since).

In `closeEvent`, add `self._login_screen.stop_pairing()` as a safety net (alongside the existing `self._player.shutdown()`/`self._worker.stop_loop()`/thread teardown) so the background HTTP server thread doesn't outlive the app on quit.

- [ ] **Step 5: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_app.py -v -k pairing`
Expected: PASS.

- [ ] **Step 6: Run the full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` (3 times)
Expected: all passing, coverage ≥80%.

- [ ] **Step 7: Commit**

```bash
git add src/sixpack/ui/app.py tests/test_ui/test_app.py
git commit -m "Wire pairing server lifecycle and success path into MainWindow"
```

---

## Task 6: Splash screen polish

**Files:**
- Modify: `src/sixpack/ui/screens/splash.py`
- Test: `tests/test_ui/test_screens.py` (or wherever existing splash tests live — grep first) or a new small test file if none exists

**Interfaces:** No new public API — `SplashScreen.set_status(str)` unchanged.

- [ ] **Step 1: Read the current `splash.py`** (reproduced earlier in this plan's investigation — re-read the live file, low risk of drift but confirm) and `theme.py`'s exact token values (`FONT_HUGE = 32`, `ACCENT = "#4a9eff"`, etc.).

- [ ] **Step 2: Replace hardcoded values with theme tokens**

Change the title's stylesheet from hardcoded `font-size: 52pt` / `theme.TEXT_PRIMARY` to use `theme.FONT_HUGE` and `theme.ACCENT` (matching `LoginScreen`'s own title styling, which already uses `theme.ACCENT` for its "SixPack" title — bring `splash.py`'s title into visual parity with it, since both show the same brand title):

```python
title.setStyleSheet(
    f"font-size: {theme.FONT_HUGE}pt; font-weight: bold; color: {theme.ACCENT}; letter-spacing: 4px;"
)
```

Bring the subtitle and status label onto `theme.FONT_HEADING`/`theme.FONT_META` and `theme.TEXT_SECONDARY`/`theme.TEXT_MUTED` respectively (they're already close — `TEXT_SECONDARY`/`TEXT_MUTED` are already used, just confirm the font sizes reference the theme constants instead of the current hardcoded `18pt`/`13pt`, using whichever theme constant is closest to the existing hardcoded value rather than changing the actual visual size).

This is explicitly low-priority, no-structural-change polish per the spec — don't add a `Backdrop` or restructure the layout, just bring typography onto theme tokens.

- [ ] **Step 3: Run existing splash tests (or add minimal coverage if none exist)**

Grep `tests/` for `SplashScreen` first. If tests exist, run them and confirm they still pass with the token-based styling (a test asserting exact hardcoded stylesheet strings would need updating to match the new token-based values — update, don't work around). If none exist, this is low-risk enough that a single smoke test is sufficient:

```python
def test_splash_screen_creates(qtbot):
    from sixpack.ui.screens.splash import SplashScreen
    screen = SplashScreen()
    qtbot.addWidget(screen)
    screen.set_status("Connecting…")
```

- [ ] **Step 4: Run the full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` (3 times)
Expected: all passing, coverage ≥80%.

- [ ] **Step 5: Commit**

```bash
git add src/sixpack/ui/screens/splash.py
git commit -m "Bring splash screen typography onto theme tokens"
```

---

## Self-Review

**Spec coverage:** All of Phase D's spec bullets covered — pairing flow primary path (Tasks 1, 2, 4, 5), on-screen-keyboard fallback (Tasks 3, 4), splash polish (Task 6). Error handling requirements from the spec (bind-failure auto-fallback, expired-code page) explicitly specified in Tasks 1 and 4. Security scope explicitly bounded in Global Constraints to prevent over-building. ✓

**Placeholder scan:** Task 4's active-field-tracking mechanism for the on-screen keyboard, and the exact bottom-row column layout in Task 3, are explicitly flagged as small, real design choices left to the implementer (consistent with how earlier phases of this larger effort handled comparable small UI-flow/visual-placement decisions) — not vague hand-waving, since the required BEHAVIOR (what must work) is fully specified even where the exact mechanism isn't pre-chosen.

**Type consistency:** `PairingServer(on_success: Callable[[str, str, str], None])` (Task 1) is consumed identically by `LoginScreen.start_pairing()` (Task 4). `LoginScreen.pairing_login_succeeded = pyqtSignal(str, str, str)` (Task 4) is consumed identically by `MainWindow._on_pairing_login_succeeded` (Task 5). `QRCodeWidget.set_data(str)` (Task 2) and `OnScreenKeyboard`'s four signals (Task 3) are consumed identically in Task 4.
