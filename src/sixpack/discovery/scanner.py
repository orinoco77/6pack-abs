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
import logging
import socket
import threading
from collections.abc import Callable

import httpx

logger = logging.getLogger(__name__)

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
        # A device on the LAN can return valid JSON that isn't an object at
        # all (a bare array/string/number/null — plausible from random IoT
        # devices, printers, etc. sitting on ABS_PORT). Only a JSON object
        # can possibly be an Audiobookshelf /status response; anything else
        # is treated the same as "not an ABS server", exactly like the
        # non-JSON-body branch above, rather than raising AttributeError
        # from .get() on a non-dict.
        if isinstance(data, dict) and data.get("app") == "audiobookshelf":
            return f"http://{host}:{ABS_PORT}"
        return None


async def _scan(hosts: list[str]) -> list[str]:
    if not hosts:
        return []
    sem = asyncio.Semaphore(_CONCURRENCY)
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(
            *(_check_host(client, h, sem) for h in hosts), return_exceptions=True
        )
    # Belt-and-braces: even with the isinstance guard above, no future
    # unexpected exception from an individual host check should be able to
    # take down the whole gather (and with it, the on_result callback).
    return [r for r in results if isinstance(r, str)]


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
        try:
            found = asyncio.run(_scan(target_hosts))
        except Exception:  # noqa: BLE001 — on_result must fire exactly once
            logger.exception("LAN scan failed")
            found = []
        on_result(found)

    threading.Thread(target=_run, daemon=True).start()
