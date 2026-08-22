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
