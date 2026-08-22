"""Tests for the LAN Audiobookshelf-server scanner — real HTTP requests
against locally-bound test servers, no real subnet scan (the `hosts`
parameter overrides auto-detection for exactly this reason)."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from sixpack.discovery.scanner import scan_for_servers


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


def _make_json_body_handler(python_value):
    """Build a handler class that answers `/status` with `python_value`
    JSON-encoded — used to simulate a non-Audiobookshelf LAN device that
    happens to return syntactically valid JSON that isn't a JSON object
    (an array, string, number, or null), which a naive `data.get(...)`
    call would choke on with AttributeError."""

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):  # noqa: A002
            pass

        def do_GET(self):
            body = json.dumps(python_value).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return _Handler


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


@pytest.fixture(params=[[1, 2, 3], "hello", 42, None], ids=["array", "string", "number", "null"])
def fake_non_object_json_server(request):
    """A LAN device that answers /status with valid JSON that is NOT a
    JSON object — plausible from random IoT devices, printers, etc.
    sitting on ABS_PORT. Regression coverage for the AttributeError the
    final whole-plan review found in `_check_host`'s `.get()` call."""
    handler_cls = _make_json_body_handler(request.param)
    httpd = HTTPServer(("127.0.0.1", 0), handler_cls)
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
    results, done, on_result = _wait_for_result()
    scan_for_servers(on_result, hosts=["127.0.0.1"])
    assert done.wait(timeout=5.0)
    assert results == [[]]


def test_empty_hosts_list_calls_on_result_with_empty_list():
    results, done, on_result = _wait_for_result()
    scan_for_servers(on_result, hosts=[])
    assert done.wait(timeout=5.0)
    assert results == [[]]


def test_non_object_json_response_does_not_crash_scan(fake_non_object_json_server, monkeypatch):
    # Before the fix, `data.get("app")` on a non-dict `resp.json()` result
    # raised AttributeError, which propagated out of asyncio.gather (no
    # return_exceptions=True) and out of asyncio.run in _run (no
    # try/except) — killing the background thread before on_result was
    # ever called. That failure mode looks like a hang here: done.wait()
    # times out and the assertion below fails, rather than the scan
    # completing with the offending host simply excluded.
    import sixpack.discovery.scanner as scanner_module
    monkeypatch.setattr(scanner_module, "ABS_PORT", fake_non_object_json_server)

    results, done, on_result = _wait_for_result()
    scan_for_servers(on_result, hosts=["127.0.0.1"])
    assert done.wait(timeout=5.0), "on_result was never called — scan thread likely crashed"
    assert results == [[]]
