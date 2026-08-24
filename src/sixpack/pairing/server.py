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
import json
import secrets
import socket
import threading
import time
import urllib.parse
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer

from sixpack.api.client import (  # noqa: F401 — re-exported for tests (server_module.AuthenticationError / .APIError)
    ABSClient,
    APIError,
    AuthenticationError,
)

_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I/l ambiguity
_CODE_LENGTH = 6

_ROOT_VARS = """
    --bg: #0f0f0f; --surface: #1c1c1c; --surface-high: #2a2a2a;
    --accent: #4a9eff; --accent-dim: #2a6fcc;
    --text-primary: #ffffff; --text-secondary: #a0a0a0; --text-muted: #606060;
"""

# Shared dark-theme styling for the simpler status pages (expired/success/
# error) — just enough to look like part of the same app, not a full form
# layout.
_STATUS_STYLE = f"""
<style>
  :root {{{_ROOT_VARS}}}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg); color: var(--text-primary);
    max-width: 480px; margin: 0 auto; padding: 48px 20px; text-align: center;
  }}
  h2 {{ color: var(--accent); font-size: 22px; margin: 0 0 12px; }}
  p {{ color: var(--text-secondary); font-size: 15px; line-height: 1.5; }}
  a {{ color: var(--accent); }}
</style>"""

_FORM_PAGE = """<!doctype html>
<html><head><title>SixPack Pairing</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root {{{root_vars}}}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg); color: var(--text-primary);
    max-width: 480px; margin: 0 auto; padding: 32px 20px;
  }}
  h1 {{
    color: var(--accent); font-size: 28px; font-weight: 700;
    text-align: center; margin: 0 0 4px;
  }}
  .subtitle {{
    color: var(--text-secondary); text-align: center; margin: 0 0 32px; font-size: 14px;
  }}
  #discovered-container {{ display: contents; }}
  .discovered {{ margin-bottom: 24px; }}
  .discovered p {{ color: var(--text-secondary); font-size: 13px; margin: 0 0 8px; }}
  .discovered-btn {{
    display: block; width: 100%; padding: 14px 16px; margin: 0 0 8px;
    background: var(--surface-high); color: var(--text-primary);
    border: 2px solid var(--accent-dim); border-radius: 8px;
    font-size: 16px; text-align: left; cursor: pointer;
  }}
  .divider {{ color: var(--text-muted); text-align: center; font-size: 13px; margin: 16px 0; }}
  input {{
    display: block; width: 100%; padding: 14px 16px; margin: 0 0 12px;
    background: var(--surface); color: var(--text-primary);
    border: 2px solid var(--text-muted); border-radius: 8px; font-size: 16px;
  }}
  input:focus {{ border-color: var(--accent); outline: none; }}
  button[type="submit"] {{
    display: block; width: 100%; padding: 16px; margin-top: 8px;
    background: var(--accent); color: #ffffff; border: none; border-radius: 8px;
    font-size: 17px; font-weight: 700;
  }}
</style></head>
<body>
<h1>SixPack</h1>
<p class="subtitle">Connect to your Audiobookshelf server</p>
<div id="discovered-container">{discovered_html}</div>
<form method="post" action="/">
  <input type="text" name="server_url" placeholder="Server URL (e.g. http://192.168.1.10:13378)"
    required>
  <input type="text" name="username" placeholder="Username" required>
  <input type="password" name="password" placeholder="Password" required>
  <input type="hidden" name="code" value="{code}">
  <button type="submit">Connect</button>
</form>
<script>
(function() {{
  // Poll a small `/discovered` endpoint on this same pairing server for
  // newly-discovered LAN servers and, if any turn up, inject them into
  // #discovered-container in place. A real /24 LAN scan can take several
  // seconds (measured ~3.6s worst case) and the QR code / this page is
  // shown before that scan finishes, so a user who loads this page early
  // would otherwise see an empty discovered-servers section forever. This
  // script NEVER touches the <form> or any of its input fields — it only
  // ever appends/replaces children of the standalone #discovered-container
  // div above the form, so text a user has already started typing into
  // the manual-entry fields can never be disturbed by a poll landing.
  var container = document.getElementById('discovered-container');
  if (container.children.length > 0) {{
    return;  // already server-rendered with results — nothing to poll for
  }}
  var code = {code_json};
  var attempts = 0;
  var maxAttempts = 10;      // ~15s of polling at 1.5s intervals — comfortably
  var intervalMs = 1500;     // above the measured ~3.6s worst-case scan time

  function renderDiscovered(servers) {{
    var wrap = document.createElement('div');
    wrap.className = 'discovered';
    var p = document.createElement('p');
    p.textContent = 'Servers found on your network:';
    wrap.appendChild(p);
    servers.forEach(function(s) {{
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'discovered-btn';
      // textContent (not innerHTML) and addEventListener with a closure
      // (not an inline onclick="..." HTML-attribute string) — the server
      // value never passes through any HTML/JS string-building step here,
      // so there is no escaping to get wrong on this path.
      btn.textContent = s;
      btn.addEventListener('click', function() {{
        document.getElementsByName('server_url')[0].value = s;
      }});
      wrap.appendChild(btn);
    }});
    container.innerHTML = '';
    container.appendChild(wrap);
  }}

  function poll() {{
    attempts += 1;
    fetch('/discovered?code=' + encodeURIComponent(code))
      .then(function(r) {{ return r.json(); }})
      .then(function(data) {{
        var servers = (data && data.servers) || [];
        if (servers.length > 0) {{
          renderDiscovered(servers);
          return;  // found results — stop polling
        }}
        if (attempts < maxAttempts) {{
          setTimeout(poll, intervalMs);
        }}
      }})
      .catch(function() {{
        if (attempts < maxAttempts) {{
          setTimeout(poll, intervalMs);
        }}
      }});
  }}

  setTimeout(poll, intervalMs);
}})();
</script>
</body></html>"""

_VIEWPORT_META = '<meta name="viewport" content="width=device-width, initial-scale=1">'

_EXPIRED_PAGE = f"""<!doctype html>
<html><head><title>SixPack Pairing</title>
{_VIEWPORT_META}{_STATUS_STYLE}</head>
<body><h2>This pairing code has expired or is invalid</h2>
<p>Go back to the TV and select "Pair a new device" to get a fresh code.</p>
</body></html>"""

_SUCCESS_PAGE = f"""<!doctype html>
<html><head><title>SixPack Pairing</title>
{_VIEWPORT_META}{_STATUS_STYLE}</head>
<body><h2>Connected!</h2>
<p>You can return to the TV now.</p>
</body></html>"""

# NOTE: unlike _STATUS_STYLE above (spliced pre-resolved, with single
# braces, into pages that are never run through .format()), this page IS
# run through .format() in do_POST (it has {message}/{code} slots) — so its
# CSS braces must stay DOUBLED here (plain string, not an f-string) or
# str.format() would try to treat raw CSS braces as format placeholders and
# raise (confirmed: this broke do_POST's exception-handling path during
# development). root_vars is filled in from _ROOT_VARS at format() time.
_ERROR_PAGE = ("""<!doctype html>
<html><head><title>SixPack Pairing</title>
""" + _VIEWPORT_META + """
<style>
  :root {{{root_vars}}}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg); color: var(--text-primary);
    max-width: 480px; margin: 0 auto; padding: 48px 20px; text-align: center;
  }}
  h2 {{ color: var(--accent); font-size: 22px; margin: 0 0 12px; }}
  p {{ color: var(--text-secondary); font-size: 15px; line-height: 1.5; }}
  a {{ color: var(--accent); }}
</style></head>
<body><h2>Login failed</h2>
<p>{message}</p>
<p><a href="/?code={code}">Try again</a></p>
</body></html>""")


def _discovered_servers_html(servers: list[str]) -> str:
    """Build the tappable pre-fill buttons shown above the manual-entry
    fields. `servers` entries currently always come from Task 1's
    ipaddress-validated LAN scan (f"http://{ip}:{port}", which can never
    contain a quote character) — but this function does not rely on that
    external invariant holding. Each value is independently made safe here:

    - `json.dumps(s)` produces a valid, double-quoted JS string literal with
      every JS-special character (including `"`) correctly backslash-escaped
      — safe to drop into the `onclick` JS body as-is.
    - That JS literal is then run through `html.escape()` before being
      embedded in the (double-quoted) `onclick="..."` HTML attribute, so it
      cannot contain a raw `"` that would terminate the attribute early
      regardless of what characters `s` contains. The browser HTML-decodes
      the attribute value before handing it to the JS parser, so the
      resulting `\&quot;` -> `\"` round-trips back to the exact JS-escaped
      quote `json.dumps` produced — the JS string content is unaffected.

    html.escape() on the visible label text is separately applied as
    defense in depth for the button's inner text content.
    """
    if not servers:
        return ""
    items = "\n".join(
        f'<button type="button" class="discovered-btn" '
        f'onclick="document.getElementsByName(\'server_url\')[0].value='
        f'{html.escape(json.dumps(s))}">{html.escape(s)}</button>'
        for s in servers
    )
    return f'<div class="discovered">\n<p>Servers found on your network:</p>\n{items}\n</div>'


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
    def log_message(self, format: str, *args) -> None:
        pass

    def do_GET(self) -> None:
        server: PairingServer = self.server.pairing_server  # type: ignore[attr-defined]
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        code = (query.get("code") or [""])[0]

        if parsed.path == "/discovered":
            # Small polling endpoint the form page's own script calls (see
            # _FORM_PAGE) to pick up scan results that land after the page
            # was first served. Gated on code validity like the form page
            # itself — an invalid/expired code just gets an empty list
            # rather than leaking scan results.
            servers = list(server._discovered_servers) if server.is_code_valid(code) else []
            self._respond_json(200, {"servers": servers})
            return

        if server.is_code_valid(code):
            discovered_html = _discovered_servers_html(server._discovered_servers)
            self._respond(
                200,
                _FORM_PAGE.format(
                    code=server.code,
                    code_json=json.dumps(server.code),
                    discovered_html=discovered_html,
                    root_vars=_ROOT_VARS,
                ),
            )
        else:
            self._respond(200, _EXPIRED_PAGE)

    def do_POST(self) -> None:
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
        except Exception as exc:
            # exc's message can embed attacker-controlled content (e.g. an
            # APIError built from a malicious server_url's raw response
            # body), so it MUST be HTML-escaped before landing in the page.
            message = html.escape(str(exc))
            self._respond(
                200,
                _ERROR_PAGE.format(message=message, code=server.code, root_vars=_ROOT_VARS),
            )
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

    def _respond(self, status: int, body_html: str) -> None:
        body = body_html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _respond_json(self, status: int, payload: dict) -> None:
        # json.dumps produces a well-formed JSON document regardless of
        # what characters the discovered server URLs contain — no manual
        # escaping needed on this path, unlike the HTML-attribute embedding
        # _discovered_servers_html does for the initial page render.
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
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
        self._discovered_servers: list[str] = []

    def set_discovered_servers(self, servers: list[str]) -> None:
        """Store already-discovered server URLs to offer as tappable pre-fill
        options on the NEXT served GET response. May be called from the GUI
        thread while `do_GET` reads `_discovered_servers` from the server's
        own background thread — always assign a NEW list (never mutate one
        in place) so a plain reference reassignment is all that's needed;
        no lock required.
        """
        self._discovered_servers = list(servers)

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
        if self._used or not code or not secrets.compare_digest(code, self.code):
            return False
        return (time.monotonic() - self._issued_at) < self.EXPIRY_SECONDS

    def mark_used(self) -> None:
        self._used = True

    def pairing_url(self) -> str:
        return f"http://{_lan_ip()}:{self.port}/?code={self.code}"
