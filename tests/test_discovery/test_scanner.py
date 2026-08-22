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
