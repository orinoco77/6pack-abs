# LAN Server Discovery + Pairing Form Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect Audiobookshelf servers on the local network automatically so neither the phone-pairing form nor the TV's on-screen-keyboard fallback requires the user to know/type a server URL by default — manual entry stays available as a fallback on both surfaces, never removed. Redesign the phone-facing pairing form to be mobile-responsive and visually branded to match the rest of the app.

**Architecture:** A new, Qt-independent `sixpack.discovery` module scans the local /24 subnet's Audiobookshelf port (13378) concurrently, hitting each candidate's unauthenticated `/status` endpoint and checking for `{"app": "audiobookshelf", ...}` — confirmed live against a real server (`curl http://merton.home:13378/status` → `{"app":"audiobookshelf","serverVersion":"2.31.0",...}`, no auth required). The scan runs on a background thread (mirroring `PairingServer`'s own already-established pattern from the previous plan) so callers never block; results reach Qt code via the same "background thread calls a plain callback, which does a bare `pyqtSignal.emit()`" pattern `PairingServer.on_success` already uses safely. `LoginScreen` owns the ONE scan per pairing session (kicked off from `start_pairing()`) and feeds the results to both consumers: `PairingServer` embeds them as tappable options in the served HTML form, and `LoginScreen` shows them as a small focusable list above the on-screen-keyboard fallback's URL field.

**Tech Stack:** Python 3.12, PyQt6, `httpx`/`asyncio` (already project dependencies), `ipaddress`/`socket`/`threading` (stdlib), pytest + pytest-qt (headless via `QT_QPA_PLATFORM=offscreen`).

**Spec:** No prior written spec — this plan was scoped directly in conversation with the user (real-server API recon confirmed the `/status` endpoint live; the TV-side UX choice — a focusable list above the URL field, not a separate picker screen — was confirmed via an explicit question). Builds on the already-shipped `docs/superpowers/plans/2026-08-22-phase-d-login-splash.md` (`LoginScreen`/`PairingServer`/`OnScreenKeyboard`), which this plan treats as its baseline and does not restructure beyond what's described below.

## Global Constraints

- Python ≥ 3.10 (dev/target 3.12). Line length 100 (ruff, `select = ["E","F","I","UP"]`).
- Coverage gate: `--cov-fail-under=80`.
- All Qt tests run under `QT_QPA_PLATFORM=offscreen`.
- No `QGraphicsEffect` subclass anywhere, ever.
- **Manual URL entry must remain available on BOTH surfaces, always** — auto-detection is a convenience default, never the only path. This is explicit user direction, not an implementation detail to optimize away.
- **No real network subnet scan in tests** — the scanner's public entry point must accept an injectable list of candidate hosts (or an equivalent seam) so tests can point it at a small, controlled set (e.g. a local test HTTP server bound to `127.0.0.1`) instead of scanning a real `/24`.
- Security note, explicit: a discovered server's URL is built entirely from a locally-scanned, `ipaddress`-validated IP address (`f"http://{host}:{ABS_PORT}"`) — never from response BODY content of the scanned host. A malicious/misbehaving device on the LAN could claim to be an Audiobookshelf server, but it cannot inject arbitrary text into what gets displayed or submitted; the worst case is a bogus discovered URL, not an injection vector. No new HTML-escaping surface is introduced by this plan (contrast with the pairing server's *credential fields*, which already go through the escaping fixed in the prior plan) — say so explicitly in your own report rather than assuming, and flag it if you find a case where scanned response content genuinely does get displayed.
- `LoginScreen`'s existing public API and all its current tests (from the prior plan) must keep passing unchanged — this plan only adds to `_build_keyboard_form`'s existing structure and `start_pairing()`'s existing body, it does not restructure the pairing-view/keyboard-fallback-view toggle or any other already-shipped behavior.
- Commit after each task. Branch: `feature/app-wide-cinematic-redesign`.

---

## File Structure

| File | Change |
|------|--------|
| `src/sixpack/discovery/__init__.py` (new) | Package marker |
| `src/sixpack/discovery/scanner.py` (new) | LAN subnet scan for `/status`-identifiable Audiobookshelf servers |
| `src/sixpack/pairing/server.py` (edit) | `_FORM_PAGE` redesigned (mobile-responsive, branded); `PairingServer.set_discovered_servers(list[str])`; discovered servers embedded in the served form |
| `src/sixpack/ui/screens/login.py` (edit) | Discovered-servers list above the URL field in the keyboard-fallback view; `start_pairing()` kicks off the shared scan; navigation state machine extended to include the list |
| `tests/test_discovery/test_scanner.py` (new) | Scanner tests against a controlled host list, no real subnet scan |
| `tests/test_pairing/test_server.py` (edit) | Tests for `set_discovered_servers`/embedded HTML |
| `tests/test_ui/test_screens.py` (edit) | Tests for the discovered-servers list UI and its navigation |

---

## Task 1: LAN scanner module

**Files:**
- Create: `src/sixpack/discovery/__init__.py`
- Create: `src/sixpack/discovery/scanner.py`
- Test: `tests/test_discovery/__init__.py` (empty — this project's test dirs are packages), `tests/test_discovery/test_scanner.py`

**Interfaces:**
- Produces: `scan_for_servers(on_result: Callable[[list[str]], None], hosts: list[str] | None = None) -> None` — starts a background-thread scan; `on_result` is called exactly once, from that background thread, with the list of discovered server URLs (`f"http://{host}:{ABS_PORT}"` for each host that responded correctly), possibly empty. `hosts`, if given, overrides real subnet auto-detection entirely (test seam — when `None`, the function auto-detects the local `/24` and scans it for real). `ABS_PORT = 13378` as a module-level constant.

- [ ] **Step 1: Write the failing tests**

Read `tests/test_pairing/test_server.py` first for this project's established pattern for testing background-thread network code with a real bound local server (it already does this for `PairingServer` itself). Create `tests/test_discovery/test_scanner.py`:

```python
"""Tests for the LAN Audiobookshelf-server scanner — real HTTP requests
against locally-bound test servers, no real subnet scan (the `hosts`
parameter overrides auto-detection for exactly this reason)."""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from sixpack.discovery.scanner import ABS_PORT, scan_for_servers


class _FakeABSHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002
        pass

    def do_GET(self):
        if self.path == "/status":
            body = json.dumps({"app": "audiobookshelf", "serverVersion": "2.31.0"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


class _NotABSHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002
        pass

    def do_GET(self):
        body = json.dumps({"app": "something-else"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def fake_abs_server():
    httpd = HTTPServer(("127.0.0.1", 0), _FakeABSHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield port
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def fake_non_abs_server():
    httpd = HTTPServer(("127.0.0.1", 0), _NotABSHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield port
    httpd.shutdown()
    httpd.server_close()


def _wait_for_result(timeout=5.0):
    results = []
    done = threading.Event()

    def on_result(found):
        results.append(found)
        done.set()

    return results, done, on_result


def test_finds_real_abs_server(fake_abs_server, monkeypatch):
    # Point the scanner's ABS_PORT-based URL construction at our fake
    # server's actual (random) port by scanning "127.0.0.1" and asserting
    # on the port the fake server actually bound — confirm scan_for_servers
    # lets the caller verify against the real fake_abs_server port, e.g. by
    # monkeypatching the module's ABS_PORT for the duration of this test.
    import sixpack.discovery.scanner as scanner_module
    monkeypatch.setattr(scanner_module, "ABS_PORT", fake_abs_server)

    results, done, on_result = _wait_for_result()
    scan_for_servers(on_result, hosts=["127.0.0.1"])
    assert done.wait(timeout=5.0)
    assert results == [[f"http://127.0.0.1:{fake_abs_server}"]]


def test_does_not_flag_non_abs_server(fake_non_abs_server, monkeypatch):
    import sixpack.discovery.scanner as scanner_module
    monkeypatch.setattr(scanner_module, "ABS_PORT", fake_non_abs_server)

    results, done, on_result = _wait_for_result()
    scan_for_servers(on_result, hosts=["127.0.0.1"])
    assert done.wait(timeout=5.0)
    assert results == [[]]


def test_unreachable_host_is_silently_skipped():
    # Port 1 is reserved/unlikely to be listening; the scan must not
    # raise, just omit it from results.
    import sixpack.discovery.scanner as scanner_module
    scanner_module_port = scanner_module.ABS_PORT  # unchanged — nothing listens on 127.0.0.1:ABS_PORT in test env

    results, done, on_result = _wait_for_result()
    scan_for_servers(on_result, hosts=["127.0.0.1"])
    assert done.wait(timeout=5.0)
    assert results == [[]]


def test_empty_hosts_list_calls_on_result_with_empty_list():
    results, done, on_result = _wait_for_result()
    scan_for_servers(on_result, hosts=[])
    assert done.wait(timeout=5.0)
    assert results == [[]]
```

Check that monkeypatching a module-level `ABS_PORT` constant genuinely affects behavior your implementation reads at scan-time (not a value captured once at import time into some other structure) — if your implementation captures `ABS_PORT` into a default argument or a constant computed at function-definition time instead of reading `scanner_module.ABS_PORT` fresh inside the scan, this monkeypatch approach won't work and you'll need to adjust either the implementation or find another way to point the scan at a test-controlled port. State in your report which approach you used.

- [ ] **Step 2: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_discovery/ -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sixpack.discovery'`.

- [ ] **Step 3: Implement**

Create `src/sixpack/discovery/__init__.py` (empty or a one-line docstring).

Create `src/sixpack/discovery/scanner.py`:

```python
"""LAN scanner for locally-reachable Audiobookshelf servers.

Every Audiobookshelf server exposes an unauthenticated `/status` endpoint
that identifies it unambiguously — confirmed live against a real server:
`{"app": "audiobookshelf", "serverVersion": "...", ...}`, HTTP 200, no auth
required. This module scans the local /24 subnet's Audiobookshelf port
concurrently for that fingerprint.

Runs on a background thread (mirroring sixpack.pairing.server.PairingServer's
own established pattern) so callers never block; results are delivered via
a plain callback FROM THAT BACKGROUND THREAD. Qt callers must marshal back
to the GUI thread themselves — a bare pyqtSignal.emit() from the callback is
sufficient and safe, the same pattern PairingServer.on_success already uses.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
import threading
from collections.abc import Callable

import httpx

ABS_PORT = 13378
_SCAN_TIMEOUT = 0.5
_CONCURRENCY = 40


def _lan_subnet_hosts() -> list[str]:
    """Every host address in this machine's local /24, excluding itself.
    Best-effort: returns [] if no network is reachable at all."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return []
    network = ipaddress.ip_network(f"{local_ip}/24", strict=False)
    return [str(ip) for ip in network.hosts() if str(ip) != local_ip]


async def _check_host(client: httpx.AsyncClient, host: str, sem: asyncio.Semaphore) -> str | None:
    async with sem:
        try:
            resp = await client.get(f"http://{host}:{ABS_PORT}/status", timeout=_SCAN_TIMEOUT)
        except httpx.HTTPError:
            return None
        if resp.status_code != 200:
            return None
        try:
            data = resp.json()
        except ValueError:
            return None
        if data.get("app") == "audiobookshelf":
            return f"http://{host}:{ABS_PORT}"
        return None


async def _scan(hosts: list[str]) -> list[str]:
    if not hosts:
        return []
    sem = asyncio.Semaphore(_CONCURRENCY)
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(*(_check_host(client, h, sem) for h in hosts))
    return [r for r in results if r is not None]


def scan_for_servers(
    on_result: Callable[[list[str]], None],
    hosts: list[str] | None = None,
) -> None:
    """Kick off a background LAN scan. `on_result(list_of_urls)` is called
    exactly once, from the background thread, when the scan completes
    (possibly with an empty list). `hosts` overrides subnet auto-detection —
    tests use this to scan a small, controlled set instead of a real /24."""
    def _run() -> None:
        target_hosts = hosts if hosts is not None else _lan_subnet_hosts()
        found = asyncio.run(_scan(target_hosts))
        on_result(found)

    threading.Thread(target=_run, daemon=True).start()
```

Read this against the test file from Step 1 — specifically, confirm `_check_host` reads the MODULE-LEVEL `ABS_PORT` name fresh each call (via the module's own global lookup, which is how Python module-level names normally work when referenced by their bare name inside a function in the same module) so `monkeypatch.setattr(scanner_module, "ABS_PORT", ...)` in the tests actually takes effect. If you restructure this in a way that captures `ABS_PORT` differently, verify the monkeypatch still works before finalizing.

- [ ] **Step 4: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_discovery/ -v`
Expected: PASS. These tests involve real background threads and short waits — run them a few times to confirm they're not flaky before moving on.

- [ ] **Step 5: Run the full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` (3 times)
Expected: all passing, coverage ≥80%.

- [ ] **Step 6: Commit**

```bash
git add src/sixpack/discovery/ tests/test_discovery/
git commit -m "Add LAN scanner for locally-reachable Audiobookshelf servers"
```

---

## Task 2: Pairing form — mobile-responsive redesign + embedded server discovery

**Files:**
- Modify: `src/sixpack/pairing/server.py`
- Test: `tests/test_pairing/test_server.py`

**Interfaces:**
- Consumes: nothing new from Task 1 directly (Task 3 wires the scan itself — this task only needs `PairingServer` to accept and render an already-known list of URLs, so it can be built/tested independently of the scanner).
- Produces: `PairingServer.set_discovered_servers(servers: list[str]) -> None` — stores the list; the NEXT served GET response reflects it. Thread-safety note: this may be called from the GUI thread (by `LoginScreen`, once Task 3 wires it) while `do_GET` reads it from the server's own background thread — a plain Python list assignment is atomic enough for this (no partial-read risk for a list *reference* reassignment), but do not mutate the list in place from one thread while it's being read from another; always assign a NEW list.

- [ ] **Step 1: Read the current `src/sixpack/pairing/server.py` in full** (it has changed since a prior plan — HTML escaping was added, imports were adjusted). Read `tests/test_pairing/test_server.py` in full too, to see the established test fixtures/mocking pattern (`_FakeABSClient`, the `server` fixture) you'll extend, not replace.

- [ ] **Step 2: Write the failing tests**

Add to `tests/test_pairing/test_server.py`, using the existing `server` fixture:

```python
def test_form_page_shows_no_discovered_servers_section_by_default(server):
    resp = httpx.get(f"http://127.0.0.1:{server.port}/?code={server.code}")
    assert "discovered" not in resp.text.lower() or "no servers found" not in resp.text.lower()
    # Adjust this assertion once you see your own template's exact wording —
    # the requirement is: with no discovered servers, the manual-entry
    # field is still present and usable, and nothing broken/empty-looking
    # is shown in its place.
    assert 'name="server_url"' in resp.text


def test_form_page_embeds_discovered_servers(server):
    server.set_discovered_servers(["http://192.168.1.50:13378", "http://192.168.1.51:13378"])
    resp = httpx.get(f"http://127.0.0.1:{server.port}/?code={server.code}")
    assert "192.168.1.50" in resp.text
    assert "192.168.1.51" in resp.text
    # Manual entry must still be present alongside discovered options.
    assert 'name="server_url"' in resp.text


def test_set_discovered_servers_updates_next_response(server):
    resp1 = httpx.get(f"http://127.0.0.1:{server.port}/?code={server.code}")
    assert "192.168.1.50" not in resp1.text
    server.set_discovered_servers(["http://192.168.1.50:13378"])
    resp2 = httpx.get(f"http://127.0.0.1:{server.port}/?code={server.code}")
    assert "192.168.1.50" in resp2.text
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_pairing/test_server.py -v -k discover`
Expected: FAIL.

- [ ] **Step 4: Implement**

Add `set_discovered_servers` to `PairingServer`:

```python
    def set_discovered_servers(self, servers: list[str]) -> None:
        self._discovered_servers = list(servers)
```

Initialize `self._discovered_servers: list[str] = []` in `__init__`.

Change `_Handler.do_GET` to build the discovered-servers HTML fragment and pass it into the form template. Since `_FORM_PAGE` currently uses `.format(code=...)`, extend it to also take a `discovered_html` slot — build that fragment as a small helper:

```python
def _discovered_servers_html(servers: list[str]) -> str:
    if not servers:
        return ""
    items = "\n".join(
        f'<button type="button" class="discovered-btn" '
        f'onclick="document.getElementsByName(\'server_url\')[0].value={s!r}">{html.escape(s)}</button>'
        for s in servers
    )
    return f'<div class="discovered">\n<p>Servers found on your network:</p>\n{items}\n</div>'
```

(`{s!r}` here produces a Python repr — verify this actually produces valid, safe JS-string-literal syntax for the `onclick` attribute once embedded in HTML; since `s` is always `f"http://{ip}:{port}"` built from an `ipaddress`-validated IP and an int port per Task 1's Global Constraints note, it can never contain a quote character that would break out of the attribute, but double-check the exact quoting once you see it rendered rather than assuming `!r`'s output is automatically HTML-attribute-safe — HTML-attribute values still need their own quoting distinct from JS-string quoting when embedded inside `onclick="..."`. If `!r`'s single-quoted Python string repr conflicts with the double-quoted HTML attribute delimiter, adjust — e.g. build the onclick value with explicit escaping/quoting you've verified renders and parses correctly, or use a `<a href>`-based approach with a query-string prefill instead of JS, whichever you find cleaner and can verify actually populates the field on click.)

Then redesign `_FORM_PAGE` for mobile + branding, using SixPack's real theme colors (from `src/sixpack/ui/theme.py`, confirm the exact hex values before using them — do not guess):

```python
_FORM_PAGE = """<!doctype html>
<html><head><title>SixPack Pairing</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root {{
    --bg: #0f0f0f; --surface: #1c1c1c; --surface-high: #2a2a2a;
    --accent: #4a9eff; --accent-dim: #2a6fcc;
    --text-primary: #ffffff; --text-secondary: #a0a0a0; --text-muted: #606060;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg); color: var(--text-primary);
    max-width: 480px; margin: 0 auto; padding: 32px 20px;
  }}
  h1 {{ color: var(--accent); font-size: 28px; font-weight: 700; text-align: center; margin: 0 0 4px; }}
  .subtitle {{ color: var(--text-secondary); text-align: center; margin: 0 0 32px; font-size: 14px; }}
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
{discovered_html}
<form method="post" action="/">
  <input type="text" name="server_url" placeholder="Server URL (e.g. http://192.168.1.10:13378)"
    required>
  <input type="text" name="username" placeholder="Username" required>
  <input type="password" name="password" placeholder="Password" required>
  <input type="hidden" name="code" value="{code}">
  <button type="submit">Connect</button>
</form>
</body></html>"""
```

Update `do_GET` to call `.format(discovered_html=_discovered_servers_html(server.self._discovered_servers), code=server.code)` (fix the attribute-access syntax — this is illustrative, use whatever variable name your `do_GET` already uses to reach the `PairingServer` instance). Font sizes/spacing/exact styling above are a reasonable starting point, not values to treat as sacred — adjust anything that looks visually off once you view the rendered page (see Step 6), consistent with how this project's other visual-polish tasks have always allowed implementation-time tuning.

**16px input font-size is deliberate — do not shrink it.** iOS Safari auto-zooms the page when a text input has a font-size below 16px on focus, which is a real, well-known mobile-web annoyance; keep this constraint even if you adjust other sizing.

Also update `_EXPIRED_PAGE`/`_SUCCESS_PAGE`/`_ERROR_PAGE` to use the same `:root` color variables / general visual language (dark background, branded heading) for consistency — this isn't strictly required by the failing tests above, but leaving them in the old plain-white style while `_FORM_PAGE` alone gets redesigned would look broken/inconsistent to a real user clicking through the flow. Keep each page's existing structural content (the actual text/links/hidden fields) unchanged — visual-only pass on these three.

- [ ] **Step 5: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_pairing/test_server.py -v`
Expected: PASS — including all pre-existing tests in this file (the HTML-injection-escaping test from the prior plan especially — confirm it still passes with the redesigned template).

- [ ] **Step 6: Visual sanity check**

Start a real `PairingServer` instance in a throwaway script (or use `curl`/save the rendered HTML to a file and open it in a real browser — either is fine) and confirm the page actually renders sensibly: readable on a narrow (phone-width) viewport, branded colors visible, a discovered-server button (if you populate one via `set_discovered_servers` in your throwaway check) is clearly tappable and distinct from the manual-entry fields below it. State in your report what you did to verify this and what you observed.

- [ ] **Step 7: Run the full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` (3 times)
Expected: all passing, coverage ≥80%.

- [ ] **Step 8: Commit**

```bash
git add src/sixpack/pairing/server.py tests/test_pairing/test_server.py
git commit -m "Redesign pairing form: mobile-responsive, branded, embeds discovered servers"
```

---

## Task 3: `LoginScreen` — discovered-servers list on the keyboard-fallback view + wiring the shared scan

**Files:**
- Modify: `src/sixpack/ui/screens/login.py`
- Test: `tests/test_ui/test_screens.py`

**Interfaces:**
- Consumes: `scan_for_servers` (Task 1), `PairingServer.set_discovered_servers` (Task 2).
- Produces: no new public signals/methods beyond what's needed internally — `start_pairing()`'s existing behavior is extended (still no signature change), and the keyboard-fallback view gains a discovered-servers list purely as an internal UI addition.

- [ ] **Step 1: Read the current `src/sixpack/ui/screens/login.py` in full** — it has changed since the prior plan (the Critical-bug fix wave added `keyPressEvent`/`showEvent`/the UP/DOWN field-navigation logic). Your job is to EXTEND that existing navigation logic, not replace it. Also re-read `tests/test_ui/test_screens.py`'s existing `LoginScreen` tests, especially `test_login_keyboard_reachable_via_real_dpad_navigation` (the real-key-delivery integration test from the prior plan) — this MUST keep passing, and your new list should be a natural extension of the same navigation model that test already exercises.

**The real current `keyPressEvent`/`_use_keyboard_fallback` (confirmed by reading the live file — there is no `_focus_zone` string or similar state enum; focus-zone tracking is done by checking `QApplication.focusWidget() in fields` directly):**

```python
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
            if action == InputAction.UP and idx > 0:
                fields[idx - 1].setFocus()
                return
        super().keyPressEvent(event)

    def _use_keyboard_fallback(self) -> None:
        self._pairing_view.setVisible(False)
        self._keyboard_form.setVisible(True)
        self._active_field = self._url_input
        self._url_input.setFocus()
```

Your job is to insert a new "discovered list" zone into `keyPressEvent`, checked BEFORE the existing `focused in fields` branch (since the discovered-server buttons are `NoFocus` — matching every other sub-widget pattern in this app — they never appear as `QApplication.focusWidget()`, so this zone needs its own boolean flag rather than a focus-widget check). Use `self._discovered_focus_active: bool` (init `False` in `__init__`) to track whether the discovered list currently owns "logical" focus (with real Qt focus staying on `self`, the screen itself — the same pattern the existing pairing-view branch above already uses: `self.setFocus()`, `keyPressEvent` handles SELECT/UP/DOWN directly, no child widget involved).

```python
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

        if self._discovered_focus_active:
            if action == InputAction.DOWN:
                if self._discovered_focus_index + 1 < len(self._discovered_buttons):
                    self._discovered_focus_index += 1
                    self._reflect_discovered_focus()
                else:
                    self._discovered_focus_active = False
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
```

Add `self._discovered_focus_active: bool = False` to `__init__` alongside the other new state from this task (`_discovered_servers`, `_discovered_focus_index`, `_discovered_buttons`).

- [ ] **Step 2: Write the failing tests**

Add to `tests/test_ui/test_screens.py`, near the existing `LoginScreen` tests:

```python
def test_login_no_discovered_servers_list_hidden_by_default(qtbot):
    screen = LoginScreen()
    qtbot.addWidget(screen)
    screen._use_keyboard_fallback()
    assert not screen._discovered_list_container.isVisible()


def test_login_discovered_servers_shown_when_found(qtbot):
    screen = LoginScreen()
    qtbot.addWidget(screen)
    screen._on_servers_discovered(["http://192.168.1.50:13378", "http://192.168.1.51:13378"])
    screen._use_keyboard_fallback()
    assert screen._discovered_list_container.isVisible()
    assert len(screen._discovered_buttons) == 2


def test_login_selecting_discovered_server_fills_url_field(qtbot):
    screen = LoginScreen()
    qtbot.addWidget(screen)
    screen._on_servers_discovered(["http://192.168.1.50:13378"])
    screen._use_keyboard_fallback()
    screen._select_discovered_server(0)
    assert screen._url_input.text() == "http://192.168.1.50:13378"


def test_login_dpad_reaches_discovered_list_and_selects(qtbot):
    """Regression, matching this plan's own real-key-delivery convention:
    the discovered-servers list must be reachable and selectable using
    ONLY real key events, not direct method calls."""
    from PyQt6.QtWidgets import QApplication

    screen = LoginScreen()
    qtbot.addWidget(screen)
    screen.show()
    qtbot.waitExposed(screen)
    screen.activateWindow()
    QTest.qWaitForWindowActive(screen)
    screen._on_servers_discovered(["http://192.168.1.50:13378"])
    screen._use_keyboard_fallback()

    # With a discovered server present, initial focus in the fallback view
    # should land on the discovered list, not directly on the URL field.
    qtbot.keyClick(screen, Qt.Key.Key_Return)  # SELECT the highlighted (only) discovered server
    assert screen._url_input.text() == "http://192.168.1.50:13378"


def test_login_start_pairing_kicks_off_scan(qtbot, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "sixpack.ui.screens.login.scan_for_servers",
        lambda on_result, **kw: calls.append(on_result),
    )
    screen = LoginScreen()
    qtbot.addWidget(screen)
    screen.start_pairing()
    try:
        assert len(calls) == 1
        # Simulate the scan completing and reporting back.
        calls[0](["http://192.168.1.50:13378"])
        assert screen._discovered_servers == ["http://192.168.1.50:13378"]
    finally:
        screen.stop_pairing()
```

Import `QTest` from `PyQt6.QtTest` at the top of the test file if not already imported. Adjust exact attribute names (`_discovered_list_container`, `_discovered_buttons`, `_on_servers_discovered`, `_select_discovered_server`, `_discovered_servers`) once you've settled on your own implementation's naming — these are illustrative of required behavior, keep the test file internally consistent with whatever you build.

- [ ] **Step 3: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_screens.py -v -k discover`
Expected: FAIL.

- [ ] **Step 4: Implement**

Add the import: `from sixpack.discovery.scanner import scan_for_servers`.

In `__init__`, add `self._discovered_servers: list[str] = []`.

In `_build_keyboard_form`, add a container for the discovered-servers list ABOVE the existing `form` layout (before `outer.addLayout(form)`):

```python
        self._discovered_list_container = QWidget()
        self._discovered_list_layout = QVBoxLayout(self._discovered_list_container)
        self._discovered_list_layout.setSpacing(6)
        self._discovered_list_layout.setContentsMargins(0, 0, 0, 12)
        self._discovered_buttons: list[QPushButton] = []
        self._discovered_focus_index = 0
        self._discovered_list_container.setVisible(False)
        outer.addWidget(self._discovered_list_container)
```

(Place this line in `_build_keyboard_form` before the existing `form = QVBoxLayout()` / `outer.addLayout(form)` block — confirm the exact insertion point against your own read of the current file's structure.)

Add the discovery-population/selection logic:

```python
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
        self._discovered_focus_index = 0
        self._reflect_discovered_focus()

    def _reflect_discovered_focus(self) -> None:
        for i, btn in enumerate(self._discovered_buttons):
            border = theme.ACCENT if i == self._discovered_focus_index else "transparent"
            btn.setStyleSheet(
                f"background: {theme.SURFACE_HIGH}; color: {theme.TEXT_PRIMARY}; "
                f"border: 2px solid {border}; border-radius: 6px; padding: 10px; "
                f"text-align: left; font-size: {theme.FONT_BODY}pt;"
            )

    def _select_discovered_server(self, index: int) -> None:
        if 0 <= index < len(self._discovered_servers):
            self._url_input.setText(self._discovered_servers[index])
```

**Navigation wiring is already fully specified above (Step 1's corrected `keyPressEvent`/`_use_keyboard_fallback` code)** — implement exactly that, merged into the real current file. If `self._discovered_buttons` is empty, behavior is identical to today (focus starts directly on the URL field, the discovered-zone branch is simply never entered since `_discovered_focus_active` stays `False`) — do not force navigation through an empty, invisible list.

**Wire the scan into `start_pairing()`** — find the exact current body (it now includes the Critical-fix-wave's `self.stop_pairing()` defensive call and the `QTimer.singleShot`-based auto-refresh from that same fix wave) and add, after the pairing server has successfully started:

```python
        scan_for_servers(self._on_servers_discovered)
```

Place this call once, after `PairingServer.start()` succeeds (not inside the `except OSError` fallback branch — discovery is still useful on the keyboard-fallback view even if the phone-pairing server itself couldn't bind, so consider whether to ALSO call `scan_for_servers` in the `except OSError` branch; if you do, make sure it isn't called twice for the same `start_pairing()` invocation). Decide and implement whichever placement gives BOTH surfaces (phone form via `PairingServer`, TV keyboard-fallback list) working discovery whenever each is actually reachable, and state your reasoning in your report.

- [ ] **Step 5: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_screens.py -v -k "login or discover"`
Expected: PASS — including ALL pre-existing `LoginScreen` tests from the prior plan (the real-key-delivery integration test especially).

- [ ] **Step 6: Run the full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` (3 times)
Expected: all passing, coverage ≥80%.

- [ ] **Step 7: Commit**

```bash
git add src/sixpack/ui/screens/login.py tests/test_ui/test_screens.py
git commit -m "Add discovered-servers list to LoginScreen's keyboard-fallback view; wire shared LAN scan"
```

---

## Self-Review

**Spec coverage:** Both user-confirmed requirements covered — LAN auto-detection as the default with manual entry always available (Tasks 1 and 3 for the TV side, Task 2 for the phone side), and the phone form's mobile-responsive branded redesign (Task 2). The confirmed TV-side UX choice (focusable list above the URL field, not a separate picker screen) is implemented exactly as specified in Task 3. ✓

**Placeholder scan:** Task 2's `onclick`-attribute-quoting detail and Task 3's exact `start_pairing()` insertion point / whether to also scan on the `OSError` fallback path are both explicitly flagged as real decisions for the implementer to verify/make, with the required BEHAVIOR fully specified either way — not vague hand-waving.

**Type consistency:** `scan_for_servers(on_result: Callable[[list[str]], None], hosts: list[str] | None = None)` (Task 1) is consumed identically in Task 3. `PairingServer.set_discovered_servers(servers: list[str])` (Task 2) is consumed identically in Task 3's `_on_servers_discovered`.
