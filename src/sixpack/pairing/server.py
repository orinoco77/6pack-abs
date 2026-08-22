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
import html
import secrets
import socket
import threading
import time
import urllib.parse
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer

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
  <input type="text" name="server_url" placeholder="Server URL (e.g. http://192.168.1.10:13378)"
    required>
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
            # exc's message can embed attacker-controlled content (e.g. an
            # APIError built from a malicious server_url's raw response
            # body), so it MUST be HTML-escaped before landing in the page.
            message = html.escape(str(exc))
            self._respond(200, _ERROR_PAGE.format(message=message, code=server.code))
            return

        # NOTE: on_success runs on this background HTTP-server thread,
        # before the HTTP response is sent below. An exception raised by
        # the callback will propagate out of do_POST and the client will
        # never receive a response for this request.
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
