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


def test_post_with_html_in_error_message_is_escaped(server):
    # A malicious server_url could point at an attacker-controlled server
    # whose raw response body (truncated) becomes an APIError's message.
    # That message must never be reflected into the served HTML unescaped.
    _FakeABSClient.should_fail = True
    _FakeABSClient.fail_message = "<script>alert(document.cookie)</script>"
    body = urllib.parse.urlencode({
        "server_url": "http://evil.example.com", "username": "alice",
        "password": "x", "code": server.code,
    })
    resp = httpx.post(f"http://127.0.0.1:{server.port}/", content=body,
                       headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert resp.status_code == 200
    assert "<script>alert(document.cookie)</script>" not in resp.text
    assert "&lt;script&gt;alert(document.cookie)&lt;/script&gt;" in resp.text


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


def test_form_page_shows_no_discovered_servers_section_by_default(server):
    resp = httpx.get(f"http://127.0.0.1:{server.port}/?code={server.code}")
    assert "discovered" not in resp.text.lower() or "no servers found" not in resp.text.lower()
    # With no discovered servers, the manual-entry field is still present
    # and usable, and nothing broken/empty-looking is shown in its place.
    assert 'name="server_url"' in resp.text


def test_form_page_embeds_discovered_servers(server):
    server.set_discovered_servers(["http://192.168.1.50:13378", "http://192.168.1.51:13378"])
    resp = httpx.get(f"http://127.0.0.1:{server.port}/?code={server.code}")
    assert "192.168.1.50" in resp.text
    assert "192.168.1.51" in resp.text
    # Manual entry must still be present alongside discovered options.
    assert 'name="server_url"' in resp.text


def test_discovered_server_onclick_survives_quote_injection(server):
    # Task 1's ipaddress-validated LAN scan can never produce a URL
    # containing a `"` character, so this exact string can't arrive via the
    # real scanner today. But _discovered_servers_html() must not depend on
    # that external invariant — it has to be safe on its own. Simulate what
    # a future, less-careful caller of set_discovered_servers() could pass.
    adversarial = 'http://192.168.1.50:13378" onclick="alert(1)'
    server.set_discovered_servers([adversarial])
    resp = httpx.get(f"http://127.0.0.1:{server.port}/?code={server.code}")
    assert resp.status_code == 200
    text = resp.text

    # The pre-fix `{s!r}` approach produced a Python repr for this string
    # (no embedded single quote, so repr picks single-quote delimiters and
    # leaves the double quote completely unescaped):
    #   'http://192.168.1.50:13378" onclick="alert(1)'
    # embedded straight into the onclick="..." HTML attribute. That raw `"`
    # would terminate the attribute early, and the literal text
    # `onclick="alert(1)` would land in the page as a second, real HTML
    # attribute — i.e. a working injected onclick handler. Assert that
    # exact breakout string is never present verbatim in the response.
    broken_onclick = 'value=\'http://192.168.1.50:13378" onclick="alert(1)\''
    assert broken_onclick not in text

    # More directly: an injected `onclick="alert(1)"` must never appear as
    # its own separate HTML attribute anywhere in the response.
    assert 'onclick="alert(1)"' not in text

    # The value must still make it into the page in some safe, escaped
    # form (proving we didn't just drop/reject it).
    assert "192.168.1.50" in text


def test_set_discovered_servers_updates_next_response(server):
    resp1 = httpx.get(f"http://127.0.0.1:{server.port}/?code={server.code}")
    assert "192.168.1.50" not in resp1.text
    server.set_discovered_servers(["http://192.168.1.50:13378"])
    resp2 = httpx.get(f"http://127.0.0.1:{server.port}/?code={server.code}")
    assert "192.168.1.50" in resp2.text


# ---- /discovered polling endpoint (phone-form live-update mechanism) ----


def test_form_page_embeds_discovered_container_and_poll_script(server):
    # The form page's <form>/input markup must be completely unaffected by
    # the new polling mechanism — same assertions the pre-existing
    # test_get_with_valid_code_serves_form makes, plus checks for the new
    # container + script.
    resp = httpx.get(f"http://127.0.0.1:{server.port}/?code={server.code}")
    assert resp.status_code == 200
    text = resp.text
    assert 'id="discovered-container"' in text
    assert "/discovered?code=" in text
    assert 'name="server_url"' in text
    assert 'name="username"' in text
    assert 'name="password"' in text
    assert 'name="code"' in text
    assert "<form" in text.lower()


def test_discovered_endpoint_returns_empty_list_by_default(server):
    resp = httpx.get(f"http://127.0.0.1:{server.port}/discovered?code={server.code}")
    assert resp.status_code == 200
    assert resp.json() == {"servers": []}


def test_discovered_endpoint_returns_current_discovered_list(server):
    server.set_discovered_servers(["http://192.168.1.50:13378", "http://192.168.1.51:13378"])
    resp = httpx.get(f"http://127.0.0.1:{server.port}/discovered?code={server.code}")
    assert resp.status_code == 200
    assert resp.json() == {
        "servers": ["http://192.168.1.50:13378", "http://192.168.1.51:13378"]
    }


def test_discovered_endpoint_reflects_live_state_across_polls(server):
    # Mirrors test_set_discovered_servers_updates_next_response, but for
    # the new polling endpoint: a client that polls once and gets an empty
    # result, then polls again after set_discovered_servers() is called,
    # must see the update — the endpoint reflects live state, not a
    # snapshot frozen at first request.
    resp1 = httpx.get(f"http://127.0.0.1:{server.port}/discovered?code={server.code}")
    assert resp1.json() == {"servers": []}

    server.set_discovered_servers(["http://192.168.1.50:13378"])

    resp2 = httpx.get(f"http://127.0.0.1:{server.port}/discovered?code={server.code}")
    assert resp2.json() == {"servers": ["http://192.168.1.50:13378"]}


def test_discovered_endpoint_with_invalid_code_returns_empty_list(server):
    # Gated the same way the form page itself is — an invalid/expired code
    # must not leak discovered servers.
    server.set_discovered_servers(["http://192.168.1.50:13378"])
    resp = httpx.get(f"http://127.0.0.1:{server.port}/discovered?code=WRONG1")
    assert resp.status_code == 200
    assert resp.json() == {"servers": []}
