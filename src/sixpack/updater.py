"""Auto-update: check GitHub for a newer release, download it, and install
it using the same `uv tool install --reinstall` command install.sh already
runs. Deliberately does NOT introduce a new deployment mechanism (see
docs/superpowers/specs/2026-08-23-auto-update-design.md's Non-goals) -- the
only guarantees this module adds are: its own downloaded/extracted temp
files are always cleaned up, and a failed update never touches the
existing, working install.
"""
from __future__ import annotations

import asyncio
import importlib.metadata
import shutil
import subprocess
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

import httpx

REPO = "orinoco77/6pack-abs"
CURRENT_VERSION = importlib.metadata.version("sixpack-abs")
_API_TIMEOUT = 5.0
_DOWNLOAD_TIMEOUT = 60.0
_INSTALL_TIMEOUT = 120.0
_RELAUNCH_GRACE_SECONDS = 1.5


@dataclass
class ReleaseInfo:
    version: str
    zipball_url: str


class UpdateError(Exception):
    """Raised by the apply-update path (download/extract/install/relaunch
    failures). fetch_latest_release() and is_newer() never raise -- the
    version CHECK must never be able to break or delay startup.
    """


async def fetch_latest_release() -> ReleaseInfo | None:
    """Return the latest published GitHub release, or None if unavailable
    for any reason (offline, rate-limited, malformed response, no releases
    published yet). Never raises.
    """
    try:
        async with httpx.AsyncClient(timeout=_API_TIMEOUT) as client:
            response = await client.get(
                f"https://api.github.com/repos/{REPO}/releases/latest",
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "sixpack-abs-updater",
                },
            )
        if response.status_code != 200:
            return None
        data = response.json()
        tag = data.get("tag_name", "")
        version = tag[1:] if tag.startswith("v") else tag
        zipball_url = data.get("zipball_url")
        if not version or not zipball_url:
            return None
        return ReleaseInfo(version=version, zipball_url=zipball_url)
    except (httpx.HTTPError, ValueError):
        return None


def is_newer(latest: str, current: str) -> bool:
    """Dotted-integer version comparison, e.g. "0.10.0" > "0.9.0" (numeric,
    not lexicographic). This project controls both sides of the
    comparison, so a version that doesn't parse as dotted integers is
    treated as "not newer" rather than risk offering a bad update.
    """
    try:
        latest_parts = tuple(int(p) for p in latest.split("."))
        current_parts = tuple(int(p) for p in current.split("."))
    except ValueError:
        return False
    return latest_parts > current_parts


def _safe_extract(zf: zipfile.ZipFile, dest_dir: Path) -> None:
    """extractall() with a per-member path check, guarding against "zip
    slip" (a member whose name resolves outside dest_dir via `../` or an
    absolute path, letting a malicious archive write anywhere on disk).
    The archive is GitHub-generated from this project's own repo, not
    attacker-uploaded, so practical risk is low -- but it costs nothing to
    not trust unzip logic blindly for a step that runs with the current
    user's full filesystem permissions.
    """
    dest_root = dest_dir.resolve()
    for member in zf.namelist():
        target = (dest_dir / member).resolve()
        if target != dest_root and dest_root not in target.parents:
            raise UpdateError(f"Refusing to extract unsafe archive entry: {member!r}")
    zf.extractall(dest_dir)


async def download_and_extract(zipball_url: str, dest_dir: Path) -> Path:
    """Download the release zip into dest_dir and extract it. Returns the
    path to the single top-level directory GitHub's generated source zips
    always contain (named "{owner}-{repo}-{sha}"), which is what `uv tool
    install` needs pointed at -- it must find pyproject.toml at its root.

    Raises UpdateError on any failure. The caller owns dest_dir's
    lifetime (see apply_update, which always uses a fresh
    tempfile.TemporaryDirectory() per attempt).
    """
    zip_path = dest_dir / "release.zip"
    try:
        async with (
            httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT, follow_redirects=True) as client,
            client.stream("GET", zipball_url) as response,
        ):
            if response.status_code != 200:
                raise UpdateError(f"Download failed: HTTP {response.status_code}")
            with open(zip_path, "wb") as f:
                async for chunk in response.aiter_bytes():
                    f.write(chunk)
    except httpx.HTTPError as exc:
        raise UpdateError(f"Download failed: {exc}") from exc

    try:
        with zipfile.ZipFile(zip_path) as zf:
            _safe_extract(zf, dest_dir)
    except zipfile.BadZipFile as exc:
        raise UpdateError(f"Downloaded file is not a valid zip: {exc}") from exc

    extracted = [p for p in dest_dir.iterdir() if p.is_dir()]
    if len(extracted) != 1:
        raise UpdateError(
            f"Expected exactly one extracted directory, found {len(extracted)}"
        )
    return extracted[0]


def _find_executable(name: str) -> str:
    """Mirrors install.sh's own assumption: `uv`/`sixpack` are on PATH, or
    were placed by the uv installer at ~/.local/bin (see install.sh's
    ensure_uv/check_path).
    """
    found = shutil.which(name)
    if found:
        return found
    fallback = Path.home() / ".local" / "bin" / name
    if fallback.exists():
        return str(fallback)
    raise UpdateError(f"Could not locate '{name}' -- is it installed and on PATH?")


async def install(source_dir: Path) -> None:
    """Run the same install command install.sh's install_app() uses.
    Raises UpdateError on a nonzero exit.
    """
    uv = _find_executable("uv")
    proc = await asyncio.create_subprocess_exec(
        uv, "tool", "install", "--reinstall", str(source_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_INSTALL_TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise UpdateError(
            f"Install timed out after {_INSTALL_TIMEOUT:.0f}s -- keeping the current version"
        ) from None
    if proc.returncode != 0:
        raise UpdateError(
            f"Install failed (exit {proc.returncode}): {stderr.decode(errors='replace')[:500]}"
        )


async def apply_update(zipball_url: str) -> None:
    """Full apply-update sequence: download, extract, install. Always
    cleans up its temp directory, success or failure.
    """
    with tempfile.TemporaryDirectory(prefix="sixpack-update-") as tmp:
        source_dir = await download_and_extract(zipball_url, Path(tmp))
        await install(source_dir)


def relaunch() -> None:
    """Spawn a new, detached sixpack process and verify it doesn't exit
    immediately before returning. Caller is responsible for quitting the
    current process/QApplication immediately after a successful call --
    this function does not exit the current process itself, keeping it
    testable without tearing down the test process.

    Raises UpdateError if the new process dies within the grace window
    (e.g. a broken import in the new build) -- the caller must NOT quit
    the current, still-working process in that case, or the app would be
    left stranded with neither process running.
    """
    sixpack = _find_executable("sixpack")
    proc = subprocess.Popen([sixpack], start_new_session=True)
    time.sleep(_RELAUNCH_GRACE_SECONDS)
    if proc.poll() is not None:
        raise UpdateError(
            f"New version exited immediately (code {proc.returncode}) -- "
            "keeping the current version running"
        )
