# Auto-Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** SixPack checks GitHub for a newer release at startup and, if one exists, offers to download and install it itself — no more manually re-downloading a zip and re-running `install.sh` to update the copy on `cholet`.

**Architecture:** A new, Qt-independent `sixpack.updater` module owns the whole lifecycle (check GitHub's Releases API, compare semantic versions, download the release's auto-generated source zip, extract it, and run the exact `uv tool install --reinstall <dir>` command `install.sh` already uses). It plugs into `app.py`'s existing `AsyncWorker`/`_on_result` tag-dispatch pattern via two new tags, `check_update` and `apply_update`. A new `UpdatePromptScreen` shows the Install/Later choice (and an in-progress/error state), following `LoginScreen`'s existing manual-focus/`keyPressEvent` convention.

**Tech Stack:** Python 3.12, `httpx` (already a dependency, used by `ABSClient`), stdlib `zipfile`/`tempfile`/`asyncio.create_subprocess_exec`/`subprocess.Popen`, PyQt6, pytest + pytest-qt + respx (all already dev dependencies). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-23-auto-update-design.md`

## Global Constraints

- Python ≥ 3.10 (dev/target 3.12). Line length 100 (ruff, `select = ["E","F","I","UP"]`).
- Coverage gate: `--cov-fail-under=80`. `src/sixpack/ui/app.py` is excluded from coverage (see `pyproject.toml`'s `[tool.coverage.run] omit`) — `src/sixpack/updater.py` and `src/sixpack/ui/screens/update_prompt.py` are NOT excluded and need real test coverage.
- All Qt tests run under `QT_QPA_PLATFORM=offscreen` (already the default via `tests/conftest.py`).
- No new dependencies. `httpx` (already used by `ABSClient`) covers both the GitHub API call and the zip download.
- Repo is hardcoded as `orinoco77/6pack-abs` (matches `git remote -v`'s origin) — there is no `[project.urls]` entry in `pyproject.toml` to derive it from.
- The install step is exactly `uv tool install --reinstall <extracted-dir>` — the same command `install.sh`'s `install_app()` already runs. No new deployment scheme (no versioned venvs, no symlink swap) — see the spec's Non-goals. This feature's own responsibility is only: always clean up its own downloaded/extracted temp files, and never leave the app in a worse state than before the check ran if anything fails.
- No persisted "skip this version" state. Declining ("Later") just asks again next launch.
- No manual "check for updates" entry point in v1 — startup-only.
- **Test-safety hazard, read before Task 3:** `_on_result("apply_update", ...)`'s success path calls `relaunch()` (spawns a real detached process) and `QApplication.instance().quit()` (which would tear down the *shared test QApplication* and abort the rest of the pytest session if called for real). Any test that exercises this branch MUST monkeypatch both `relaunch` and `QApplication.quit` first — Task 3 spells out the exact monkeypatch code; do not exercise this branch any other way.
- **Test-safety hazard #2:** once Task 3 lands, `MainWindow.__init__` fires a *real* `check_update` job on the real background `AsyncWorker` thread on every construction. The shared `window` fixture in `tests/test_ui/test_app.py` (used by ~40 pre-existing tests) must be updated to stub `fetch_latest_release` (mirroring how it already stubs `AudioPlayer`) so no test hits the real network, AND must wait for startup to settle past the splash screen before yielding, since `_try_autologin()` no longer runs synchronously inside `__init__` — it now only runs after the (stubbed, near-instant, but still genuinely asynchronous) `check_update` round-trip completes. Task 3 spells out the exact fixture change.
- Commit after each task. Branch: `feature/auto-update` (already checked out, based on `main`, with the spec doc as the branch's only prior commit).

---

## File Structure

| File | Change |
|------|--------|
| `src/sixpack/updater.py` (new) | `ReleaseInfo`, `UpdateError`, `CURRENT_VERSION`, `fetch_latest_release`, `is_newer`, `download_and_extract`, `install`, `apply_update`, `relaunch` |
| `src/sixpack/ui/screens/update_prompt.py` (new) | `UpdatePromptScreen` — Install/Later prompt, "Updating…" state, error state |
| `src/sixpack/ui/app.py` (edit) | Import updater names; `_pending_release` attribute; `check_update`/`apply_update` dispatch and result/error handling; `UpdatePromptScreen` wiring |
| `tests/test_updater/__init__.py` (new) | Empty package marker (this project's test dirs are packages — see `tests/test_pairing/`, `tests/test_api/`) |
| `tests/test_updater/test_updater.py` (new) | Tests for every `updater.py` function |
| `tests/test_ui/test_update_prompt_screen.py` (new) | `UpdatePromptScreen` visual-state and keyboard-navigation tests |
| `tests/test_ui/test_app.py` (edit) | `window` fixture updated per the test-safety hazard above; new tests for the `check_update`/`apply_update` wiring |

---

## Task 1: `updater.py` — version check, download, install

**Files:**
- Create: `src/sixpack/updater.py`
- Create: `tests/test_updater/__init__.py` (empty)
- Test: `tests/test_updater/test_updater.py`

**Interfaces:**
- Produces:
  - `CURRENT_VERSION: str` — module-level constant, `importlib.metadata.version("sixpack-abs")`.
  - `class ReleaseInfo` — dataclass, fields `version: str`, `zipball_url: str`.
  - `class UpdateError(Exception)` — raised by the apply-update path only; `fetch_latest_release`/`is_newer` never raise.
  - `async def fetch_latest_release() -> ReleaseInfo | None` — no arguments.
  - `def is_newer(latest: str, current: str) -> bool`.
  - `async def download_and_extract(zipball_url: str, dest_dir: Path) -> Path` — returns the path to the single extracted top-level directory.
  - `async def install(source_dir: Path) -> None`.
  - `async def apply_update(zipball_url: str) -> None` — the full download→extract→install sequence, owns its own temp directory (always cleaned up).
  - `def relaunch() -> None` — spawns a new detached `sixpack` process; does NOT exit the current process itself.

- [ ] **Step 1: Write the failing tests**

Read `tests/test_api/test_client.py` first for this project's `respx` conventions (module-scoped fixture-free `async with respx.mock(base_url=...) as mock:` blocks inside `@pytest.mark.asyncio` tests).

Create `tests/test_updater/__init__.py` (empty file).

Create `tests/test_updater/test_updater.py`:

```python
"""Tests for the auto-update module (GitHub release check, download,
install). Pure async/subprocess logic, independent of Qt."""
from __future__ import annotations

import zipfile
from pathlib import Path

import httpx
import pytest
import respx

from sixpack.updater import (
    ReleaseInfo,
    UpdateError,
    apply_update,
    download_and_extract,
    fetch_latest_release,
    install,
    is_newer,
    relaunch,
)


# ---- fetch_latest_release ----

@pytest.mark.asyncio
async def test_fetch_latest_release_success():
    async with respx.mock(base_url="https://api.github.com") as mock:
        mock.get("/repos/orinoco77/6pack-abs/releases/latest").mock(
            return_value=httpx.Response(
                200,
                json={
                    "tag_name": "v0.3.0",
                    "zipball_url": "https://api.github.com/repos/orinoco77/6pack-abs/zipball/v0.3.0",
                },
            )
        )
        release = await fetch_latest_release()

    assert release == ReleaseInfo(
        version="0.3.0",
        zipball_url="https://api.github.com/repos/orinoco77/6pack-abs/zipball/v0.3.0",
    )


@pytest.mark.asyncio
async def test_fetch_latest_release_strips_leading_v_only_if_present():
    async with respx.mock(base_url="https://api.github.com") as mock:
        mock.get("/repos/orinoco77/6pack-abs/releases/latest").mock(
            return_value=httpx.Response(
                200, json={"tag_name": "0.3.0", "zipball_url": "https://example.com/z.zip"}
            )
        )
        release = await fetch_latest_release()

    assert release.version == "0.3.0"


@pytest.mark.asyncio
async def test_fetch_latest_release_returns_none_on_404():
    """No releases published yet — a real state for this repo today."""
    async with respx.mock(base_url="https://api.github.com") as mock:
        mock.get("/repos/orinoco77/6pack-abs/releases/latest").mock(
            return_value=httpx.Response(404)
        )
        release = await fetch_latest_release()

    assert release is None


@pytest.mark.asyncio
async def test_fetch_latest_release_returns_none_on_malformed_json():
    async with respx.mock(base_url="https://api.github.com") as mock:
        mock.get("/repos/orinoco77/6pack-abs/releases/latest").mock(
            return_value=httpx.Response(200, content=b"not json")
        )
        release = await fetch_latest_release()

    assert release is None


@pytest.mark.asyncio
async def test_fetch_latest_release_returns_none_on_missing_fields():
    async with respx.mock(base_url="https://api.github.com") as mock:
        mock.get("/repos/orinoco77/6pack-abs/releases/latest").mock(
            return_value=httpx.Response(200, json={"tag_name": "v0.3.0"})  # no zipball_url
        )
        release = await fetch_latest_release()

    assert release is None


@pytest.mark.asyncio
async def test_fetch_latest_release_returns_none_on_network_error():
    async with respx.mock(base_url="https://api.github.com") as mock:
        mock.get("/repos/orinoco77/6pack-abs/releases/latest").mock(
            side_effect=httpx.ConnectError("connection refused")
        )
        release = await fetch_latest_release()

    assert release is None


# ---- is_newer ----

@pytest.mark.parametrize(
    "latest,current,expected",
    [
        ("0.3.0", "0.2.0", True),
        ("0.2.0", "0.3.0", False),
        ("0.2.0", "0.2.0", False),
        ("0.10.0", "0.9.0", True),  # numeric, not lexicographic, comparison
        ("abc", "0.1.0", False),    # unparseable latest -> fail safe, no update offered
        ("0.1.0", "abc", False),    # unparseable current -> same
    ],
)
def test_is_newer(latest, current, expected):
    assert is_newer(latest, current) is expected


# ---- download_and_extract ----

def _make_release_zip(tmp_path: Path, top_dir_name: str = "orinoco77-6pack-abs-abc1234") -> bytes:
    """Build an in-memory zip matching GitHub's generated-source-zip shape:
    exactly one top-level directory containing the repo contents."""
    zip_path = tmp_path / "source.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(f"{top_dir_name}/pyproject.toml", "[project]\nname = \"sixpack-abs\"\n")
        zf.writestr(f"{top_dir_name}/src/sixpack/__init__.py", "")
    return zip_path.read_bytes()


@pytest.mark.asyncio
async def test_download_and_extract_returns_the_single_top_level_dir(tmp_path):
    zip_bytes = _make_release_zip(tmp_path)
    dest_dir = tmp_path / "dest"
    dest_dir.mkdir()
    async with respx.mock(base_url="https://example.com") as mock:
        mock.get("/z.zip").mock(return_value=httpx.Response(200, content=zip_bytes))
        extracted = await download_and_extract("https://example.com/z.zip", dest_dir)

    assert extracted.name == "orinoco77-6pack-abs-abc1234"
    assert (extracted / "pyproject.toml").exists()


@pytest.mark.asyncio
async def test_download_and_extract_raises_on_non_200(tmp_path):
    dest_dir = tmp_path / "dest"
    dest_dir.mkdir()
    async with respx.mock(base_url="https://example.com") as mock:
        mock.get("/z.zip").mock(return_value=httpx.Response(404))
        with pytest.raises(UpdateError):
            await download_and_extract("https://example.com/z.zip", dest_dir)


@pytest.mark.asyncio
async def test_download_and_extract_raises_on_corrupt_zip(tmp_path):
    dest_dir = tmp_path / "dest"
    dest_dir.mkdir()
    async with respx.mock(base_url="https://example.com") as mock:
        mock.get("/z.zip").mock(return_value=httpx.Response(200, content=b"not a zip file"))
        with pytest.raises(UpdateError):
            await download_and_extract("https://example.com/z.zip", dest_dir)


@pytest.mark.asyncio
async def test_download_and_extract_raises_when_zip_has_no_single_top_level_dir(tmp_path):
    zip_path = tmp_path / "flat.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("pyproject.toml", "[project]\n")  # no top-level directory at all
    dest_dir = tmp_path / "dest"
    dest_dir.mkdir()
    async with respx.mock(base_url="https://example.com") as mock:
        mock.get("/z.zip").mock(return_value=httpx.Response(200, content=zip_path.read_bytes()))
        with pytest.raises(UpdateError):
            await download_and_extract("https://example.com/z.zip", dest_dir)


# ---- install ----

class _FakeProc:
    def __init__(self, returncode: int, stdout: bytes = b"", stderr: bytes = b"") -> None:
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    async def communicate(self):
        return self._stdout, self._stderr


@pytest.mark.asyncio
async def test_install_runs_uv_tool_install_reinstall(tmp_path, monkeypatch):
    calls = []

    async def fake_exec(*args, **kwargs):
        calls.append(args)
        return _FakeProc(returncode=0)

    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}" if name == "uv" else None)
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    await install(tmp_path)

    assert calls == [("/usr/bin/uv", "tool", "install", "--reinstall", str(tmp_path))]


@pytest.mark.asyncio
async def test_install_raises_on_nonzero_exit(tmp_path, monkeypatch):
    async def fake_exec(*args, **kwargs):
        return _FakeProc(returncode=1, stderr=b"boom")

    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}" if name == "uv" else None)
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    with pytest.raises(UpdateError, match="boom"):
        await install(tmp_path)


@pytest.mark.asyncio
async def test_install_raises_when_uv_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "no-such-home")

    with pytest.raises(UpdateError, match="uv"):
        await install(tmp_path)


@pytest.mark.asyncio
async def test_install_falls_back_to_home_local_bin(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    (fake_home / ".local" / "bin").mkdir(parents=True)
    uv_path = fake_home / ".local" / "bin" / "uv"
    uv_path.write_text("")
    calls = []

    async def fake_exec(*args, **kwargs):
        calls.append(args)
        return _FakeProc(returncode=0)

    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    await install(tmp_path)

    assert calls == [(str(uv_path), "tool", "install", "--reinstall", str(tmp_path))]


# ---- apply_update (integration of download_and_extract + install) ----

@pytest.mark.asyncio
async def test_apply_update_cleans_up_temp_dir_on_success(tmp_path, monkeypatch):
    zip_bytes = _make_release_zip(tmp_path)
    captured_source_dirs = []

    async def fake_exec(*args, **kwargs):
        captured_source_dirs.append(Path(args[-1]))
        return _FakeProc(returncode=0)

    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}" if name == "uv" else None)
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    async with respx.mock(base_url="https://example.com") as mock:
        mock.get("/z.zip").mock(return_value=httpx.Response(200, content=zip_bytes))
        await apply_update("https://example.com/z.zip")

    assert len(captured_source_dirs) == 1
    assert not captured_source_dirs[0].exists()  # temp dir cleaned up after install


@pytest.mark.asyncio
async def test_apply_update_cleans_up_temp_dir_on_download_failure(monkeypatch):
    async with respx.mock(base_url="https://example.com") as mock:
        mock.get("/z.zip").mock(return_value=httpx.Response(500))
        with pytest.raises(UpdateError):
            await apply_update("https://example.com/z.zip")
    # No assertion beyond "did not raise a different/unexpected error" -- the
    # tempfile.TemporaryDirectory context manager guarantees cleanup; there's
    # no leftover path to inspect since it was never returned to the caller.


# ---- relaunch ----

def test_relaunch_spawns_detached_sixpack_process(monkeypatch):
    calls = []

    def fake_popen(args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr("shutil.which", lambda name: "/home/user/.local/bin/sixpack" if name == "sixpack" else None)
    monkeypatch.setattr("subprocess.Popen", fake_popen)

    relaunch()

    assert calls == [(["/home/user/.local/bin/sixpack"], {"start_new_session": True})]


def test_relaunch_raises_when_sixpack_not_found(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "no-such-home")

    with pytest.raises(UpdateError, match="sixpack"):
        relaunch()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_updater/ -v --no-cov`
Expected: FAIL — `ModuleNotFoundError: No module named 'sixpack.updater'`.

- [ ] **Step 3: Implement**

Create `src/sixpack/updater.py`:

```python
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
import zipfile
from dataclasses import dataclass
from pathlib import Path

import httpx

REPO = "orinoco77/6pack-abs"
CURRENT_VERSION = importlib.metadata.version("sixpack-abs")
_API_TIMEOUT = 5.0
_DOWNLOAD_TIMEOUT = 60.0


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
        async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
            async with client.stream("GET", zipball_url) as response:
                if response.status_code != 200:
                    raise UpdateError(f"Download failed: HTTP {response.status_code}")
                with open(zip_path, "wb") as f:
                    async for chunk in response.aiter_bytes():
                        f.write(chunk)
    except httpx.HTTPError as exc:
        raise UpdateError(f"Download failed: {exc}") from exc

    try:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(dest_dir)
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
    stdout, stderr = await proc.communicate()
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
    """Spawn a new, detached sixpack process. Caller is responsible for
    quitting the current process/QApplication immediately after -- this
    function does not exit the current process itself, keeping it
    testable without tearing down the test process.
    """
    sixpack = _find_executable("sixpack")
    subprocess.Popen([sixpack], start_new_session=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_updater/ -v --no-cov`
Expected: all tests PASS.

Then run with coverage to confirm the module clears the gate on its own:
Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_updater/ --cov=sixpack.updater --cov-report=term-missing`
Expected: PASS, coverage on `sixpack/updater.py` at or near 100% — the test list above already exercises every branch, including the malformed-JSON `ValueError` path (`test_fetch_latest_release_returns_none_on_malformed_json`). If `--cov-report=term-missing` shows any line genuinely uncovered, add the missing case rather than leaving it — don't treat this module as exempt from the coverage gate the way `ui/app.py` is.

- [ ] **Step 5: Commit**

```bash
git add src/sixpack/updater.py tests/test_updater/
git commit -m "Add updater module: GitHub release check, download, and install"
```

---

## Task 2: `UpdatePromptScreen`

**Files:**
- Create: `src/sixpack/ui/screens/update_prompt.py`
- Test: `tests/test_ui/test_update_prompt_screen.py`

**Interfaces:**
- Consumes: `sixpack.input.actions.InputAction`, `sixpack.input.keyboard.key_to_action` (same navigation primitives every other screen uses — see `src/sixpack/ui/screens/browse.py`'s module-level imports of both), `sixpack.ui.theme` constants (`BG`, `ACCENT`, `SURFACE_HIGH`, `TEXT_PRIMARY`, `TEXT_SECONDARY`, `TEXT_MUTED`, `FONT_TITLE`, `FONT_BODY`, `FONT_META`).
- Produces: `class UpdatePromptScreen(QWidget)` with:
  - `show_prompt(current_version: str, new_version: str) -> None`
  - `show_installing() -> None`
  - `show_error(message: str) -> None`
  - Signals: `install_requested = pyqtSignal()`, `later_requested = pyqtSignal()`, `continue_requested = pyqtSignal()`

- [ ] **Step 1: Write the failing tests**

Read `tests/test_ui/test_screens.py`'s `test_login_dpad_up_down_across_discovered_list_and_fields` (around line 479) first — this project's convention for testing D-pad navigation is real `qtbot.keyClick(...)` events against the screen (which holds real Qt focus), never calling internal navigation methods directly.

Create `tests/test_ui/test_update_prompt_screen.py`:

```python
"""Tests for UpdatePromptScreen -- the startup prompt offering to install
a newer release."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest

from sixpack.ui.screens.update_prompt import UpdatePromptScreen


def _make_screen(qtbot):
    screen = UpdatePromptScreen()
    qtbot.addWidget(screen)
    screen.show()
    qtbot.waitExposed(screen)
    screen.activateWindow()
    QTest.qWaitForWindowActive(screen)
    return screen


def test_show_prompt_displays_both_versions(qtbot):
    screen = _make_screen(qtbot)
    screen.show_prompt("0.2.0", "0.3.0")
    assert "0.2.0" in screen._version_label.text()
    assert "0.3.0" in screen._version_label.text()
    assert screen._button_row.isVisible()


def test_show_prompt_defaults_focus_to_install(qtbot):
    screen = _make_screen(qtbot)
    screen.show_prompt("0.2.0", "0.3.0")
    assert screen._focus_index == 0


def test_select_on_install_emits_install_requested(qtbot):
    screen = _make_screen(qtbot)
    screen.show_prompt("0.2.0", "0.3.0")
    received = []
    screen.install_requested.connect(lambda: received.append(True))

    qtbot.keyClick(screen, Qt.Key.Key_Return)

    assert received == [True]


def test_right_then_select_emits_later_requested(qtbot):
    screen = _make_screen(qtbot)
    screen.show_prompt("0.2.0", "0.3.0")
    received = []
    screen.later_requested.connect(lambda: received.append(True))

    qtbot.keyClick(screen, Qt.Key.Key_Right)
    assert screen._focus_index == 1
    qtbot.keyClick(screen, Qt.Key.Key_Return)

    assert received == [True]


def test_right_does_not_move_past_later(qtbot):
    screen = _make_screen(qtbot)
    screen.show_prompt("0.2.0", "0.3.0")
    qtbot.keyClick(screen, Qt.Key.Key_Right)
    qtbot.keyClick(screen, Qt.Key.Key_Right)
    assert screen._focus_index == 1


def test_left_does_not_move_before_install(qtbot):
    screen = _make_screen(qtbot)
    screen.show_prompt("0.2.0", "0.3.0")
    qtbot.keyClick(screen, Qt.Key.Key_Left)
    assert screen._focus_index == 0


def test_show_installing_hides_buttons_and_shows_status(qtbot):
    screen = _make_screen(qtbot)
    screen.show_prompt("0.2.0", "0.3.0")
    screen.show_installing()
    assert not screen._button_row.isVisible()
    assert screen._status_label.isVisible()
    assert screen._status_label.text() != ""


def test_show_error_displays_message_and_continue_button(qtbot):
    screen = _make_screen(qtbot)
    screen.show_error("Something went wrong")
    assert "Something went wrong" in screen._status_label.text()
    assert screen._continue_btn.isVisible()
    assert not screen._button_row.isVisible()


def test_select_in_error_state_emits_continue_requested(qtbot):
    screen = _make_screen(qtbot)
    screen.show_error("Something went wrong")
    received = []
    screen.continue_requested.connect(lambda: received.append(True))

    qtbot.keyClick(screen, Qt.Key.Key_Return)

    assert received == [True]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_update_prompt_screen.py -v --no-cov`
Expected: FAIL — `ModuleNotFoundError: No module named 'sixpack.ui.screens.update_prompt'`.

- [ ] **Step 3: Implement**

Create `src/sixpack/ui/screens/update_prompt.py`:

```python
"""Startup screen offering to install a newer release. Follows
LoginScreen's convention: real Qt focus stays on self; keyPressEvent
interprets InputAction and manually restyles whichever button is
logically focused (see LoginScreen._reflect_discovered_focus for the
established version of this pattern).
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from sixpack.input.actions import InputAction
from sixpack.input.keyboard import key_to_action
from sixpack.ui import theme


class UpdatePromptScreen(QWidget):
    """Full-screen prompt shown at startup when a newer release is found.

    Three states, entered via show_prompt/show_installing/show_error. Only
    show_prompt has interactive, keyboard-navigable buttons (Install /
    Later); show_error has a single Continue button; show_installing has
    no interactive elements.
    """

    install_requested = pyqtSignal()
    later_requested = pyqtSignal()
    continue_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._focus_index = 0  # 0 = Install, 1 = Later
        self._build_ui()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def _build_ui(self) -> None:
        self.setStyleSheet(f"background: {theme.BG};")
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(24)

        self._title_label = QLabel("Update available")
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_label.setStyleSheet(
            f"font-size: {theme.FONT_TITLE}pt; font-weight: bold; color: {theme.TEXT_PRIMARY};"
        )
        layout.addWidget(self._title_label)

        self._version_label = QLabel("")
        self._version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._version_label.setStyleSheet(
            f"font-size: {theme.FONT_BODY}pt; color: {theme.TEXT_SECONDARY};"
        )
        layout.addWidget(self._version_label)

        layout.addSpacing(16)

        self._button_row = QWidget()
        button_layout = QHBoxLayout(self._button_row)
        button_layout.setSpacing(16)
        self._install_btn = QPushButton("Install")
        self._install_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._install_btn.clicked.connect(self._activate_install)
        self._later_btn = QPushButton("Later")
        self._later_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._later_btn.clicked.connect(self._activate_later)
        button_layout.addWidget(self._install_btn)
        button_layout.addWidget(self._later_btn)
        layout.addWidget(self._button_row)
        self._buttons = [self._install_btn, self._later_btn]

        self._status_label = QLabel("")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet(
            f"font-size: {theme.FONT_META}pt; color: {theme.TEXT_MUTED}; font-style: italic;"
        )
        self._status_label.setVisible(False)
        layout.addWidget(self._status_label)

        self._continue_btn = QPushButton("Continue")
        self._continue_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._continue_btn.clicked.connect(self._activate_continue)
        self._continue_btn.setVisible(False)
        layout.addWidget(self._continue_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self._reflect_focus()

    # ------------------------------------------------------------------
    # State entry points
    # ------------------------------------------------------------------

    def show_prompt(self, current_version: str, new_version: str) -> None:
        self._title_label.setText("Update available")
        self._version_label.setText(f"v{current_version} → v{new_version}")
        self._version_label.setVisible(True)
        self._button_row.setVisible(True)
        self._status_label.setVisible(False)
        self._continue_btn.setVisible(False)
        self._focus_index = 0
        self._reflect_focus()

    def show_installing(self) -> None:
        self._title_label.setText("Updating…")
        self._version_label.setVisible(False)
        self._button_row.setVisible(False)
        self._status_label.setText("Downloading and installing the new version…")
        self._status_label.setVisible(True)
        self._continue_btn.setVisible(False)

    def show_error(self, message: str) -> None:
        self._title_label.setText("Update failed")
        self._version_label.setVisible(False)
        self._button_row.setVisible(False)
        self._status_label.setText(message)
        self._status_label.setVisible(True)
        self._continue_btn.setVisible(True)

    # ------------------------------------------------------------------
    # Keyboard navigation
    # ------------------------------------------------------------------

    def keyPressEvent(self, event) -> None:
        action = key_to_action(event.key())

        if self._continue_btn.isVisible():
            if action == InputAction.SELECT:
                self._activate_continue()
                return
            super().keyPressEvent(event)
            return

        if not self._button_row.isVisible():
            super().keyPressEvent(event)
            return

        if action == InputAction.LEFT and self._focus_index > 0:
            self._focus_index -= 1
            self._reflect_focus()
        elif action == InputAction.RIGHT and self._focus_index < len(self._buttons) - 1:
            self._focus_index += 1
            self._reflect_focus()
        elif action == InputAction.SELECT:
            if self._focus_index == 0:
                self._activate_install()
            else:
                self._activate_later()
        else:
            super().keyPressEvent(event)

    def _reflect_focus(self) -> None:
        for i, btn in enumerate(self._buttons):
            active = i == self._focus_index
            border = theme.ACCENT if active else "transparent"
            btn.setStyleSheet(
                f"background: {theme.SURFACE_HIGH}; color: {theme.TEXT_PRIMARY}; "
                f"border: 2px solid {border}; border-radius: 6px; padding: 10px 24px; "
                f"font-size: {theme.FONT_BODY}pt;"
            )

    def _activate_install(self) -> None:
        self.install_requested.emit()

    def _activate_later(self) -> None:
        self.later_requested.emit()

    def _activate_continue(self) -> None:
        self.continue_requested.emit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_update_prompt_screen.py -v --no-cov`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/sixpack/ui/screens/update_prompt.py tests/test_ui/test_update_prompt_screen.py
git commit -m "Add UpdatePromptScreen (Install/Later, in-progress, and error states)"
```

---

## Task 3: Wire the update check into `app.py`

**Files:**
- Modify: `src/sixpack/ui/app.py`
- Modify: `tests/test_ui/test_app.py`

**Interfaces:**
- Consumes: everything Task 1 (`src/sixpack/updater.py`) and Task 2 (`src/sixpack/ui/screens/update_prompt.py`) produce.
- Produces: `MainWindow._pending_release: ReleaseInfo | None`, `MainWindow._update_prompt_screen: UpdatePromptScreen`, `MainWindow._on_update_install_requested() -> None`. `_try_autologin()`'s own signature and behavior are unchanged — it is simply no longer called directly from `__init__`.

- [ ] **Step 1: Write the failing tests**

First, three exact edits to make before writing new tests:

**1a. Imports** — in `src/sixpack/ui/app.py`, add to the existing import block (near `from sixpack.api.client import ABSClient, AuthenticationError, APIError`):

```python
from sixpack.updater import (
    CURRENT_VERSION,
    ReleaseInfo,
    apply_update,
    fetch_latest_release,
    is_newer,
    relaunch,
)
from sixpack.ui.screens.update_prompt import UpdatePromptScreen
```

(Match this project's existing import grouping/ordering style in the surrounding block — plain alphabetical-ish grouping of `sixpack.*` imports, matching what's already there.)

**1b. Update the shared `window` fixture** in `tests/test_ui/test_app.py` (currently at lines 65-86) — this MUST land before any test exercises the real `_build_ui()` startup path, because after Task 3's Step 3 implementation lands, `MainWindow.__init__` fires a real `check_update` job on the real background thread on every construction. Replace the fixture with:

```python
@pytest.fixture
def window(qtbot, monkeypatch):
    """Fully-constructed MainWindow with a fake AudioPlayer (see
    _FakeAudioPlayer docstring for why the real one can't be used in tests)
    and a stubbed update check (so tests never hit the real GitHub API --
    mirrors the AudioPlayer stub for the same "no real external resources
    in tests" reason).
    """
    from sixpack.config import AppConfig
    from sixpack.ui import app as app_module

    # Avoid constructing a real python-mpv/libmpv backend in the test
    # process (see _FakeAudioPlayer docstring).
    monkeypatch.setattr(app_module, "AudioPlayer", _FakeAudioPlayer)

    async def _fake_fetch_latest_release():
        return None

    monkeypatch.setattr(app_module, "fetch_latest_release", _fake_fetch_latest_release)

    win = app_module.MainWindow(AppConfig())
    qtbot.addWidget(win)
    # _try_autologin() no longer runs synchronously inside __init__ -- it
    # now only runs once the (stubbed, but still genuinely asynchronous,
    # real-background-thread) check_update round-trip completes. Wait for
    # that to settle before handing the window to a test, so every
    # existing assumption about post-construction state (previously true
    # synchronously) still holds.
    qtbot.waitUntil(lambda: win._stack.currentWidget() is not win._splash_screen, timeout=2000)

    yield win

    # MainWindow.closeEvent() stops the AsyncWorker's background QThread;
    # without this the thread survives past the test, which reliably
    # aborts the interpreter at process exit.
    win.close()
```

**1c. Do not call `QApplication.instance().quit()` for real in any test.** Any new test exercising `_on_result("apply_update", ...)`'s success path must monkeypatch both `relaunch` (Task 1's function, imported into `app_module`) and `QApplication.quit` first — see the exact test below. Calling the real `.quit()` tears down the *shared* test-session `QApplication` and aborts the rest of the pytest run.

Now append these tests to `tests/test_ui/test_app.py` (after the existing playlist-back-target test block, in the same style — each test does its own local `from sixpack.ui import app as app_module` / `from sixpack.updater import ReleaseInfo` imports, matching this file's established per-test local-import convention):

```python
# ---- Auto-update wiring ----

def test_main_window_fires_check_update_on_startup(qtbot, monkeypatch):
    """Verifies the real dispatch wiring exists -- constructs its own
    MainWindow (not the shared `window` fixture, which stubs the check
    entirely) with AsyncWorker.run patched at the class level so no real
    coroutine executes."""
    from sixpack.config import AppConfig
    from sixpack.ui import app as app_module

    monkeypatch.setattr(app_module, "AudioPlayer", _FakeAudioPlayer)
    dispatched = []
    monkeypatch.setattr(
        app_module.AsyncWorker, "run", lambda self, tag, coro: dispatched.append(tag)
    )

    win = app_module.MainWindow(AppConfig())
    qtbot.addWidget(win)
    try:
        assert dispatched == ["check_update"]
    finally:
        win.close()


def test_on_result_check_update_shows_prompt_when_newer_release_available(window, monkeypatch):
    from sixpack.ui import app as app_module
    from sixpack.updater import ReleaseInfo

    monkeypatch.setattr(app_module, "CURRENT_VERSION", "0.1.0")
    release = ReleaseInfo(version="0.2.0", zipball_url="http://example.com/z.zip")

    window._on_result("check_update", release)

    assert window._stack.currentWidget() is window._update_prompt_screen
    assert window._pending_release is release


def test_on_result_check_update_proceeds_to_login_when_release_not_newer(window, monkeypatch):
    from sixpack.ui import app as app_module
    from sixpack.updater import ReleaseInfo

    monkeypatch.setattr(app_module, "CURRENT_VERSION", "9.9.9")
    release = ReleaseInfo(version="0.2.0", zipball_url="http://example.com/z.zip")

    window._on_result("check_update", release)

    assert window._stack.currentWidget() is window._login_screen


def test_on_result_check_update_proceeds_to_login_when_no_release(window):
    window._on_result("check_update", None)
    assert window._stack.currentWidget() is window._login_screen


def test_on_error_check_update_proceeds_to_login(window):
    """Defensive backstop -- fetch_latest_release() fails soft internally
    and should never actually raise, but _on_error must still degrade
    gracefully if it somehow did."""
    window._on_error("check_update", "boom")
    assert window._stack.currentWidget() is window._login_screen


def test_update_prompt_later_proceeds_to_login(window):
    from sixpack.updater import ReleaseInfo

    window._pending_release = ReleaseInfo(version="0.2.0", zipball_url="http://example.com/z.zip")
    window._update_prompt_screen.show_prompt("0.1.0", "0.2.0")
    window._stack.setCurrentWidget(window._update_prompt_screen)

    window._update_prompt_screen.later_requested.emit()

    assert window._stack.currentWidget() is window._login_screen


def test_on_update_install_requested_fires_apply_update_job(window, monkeypatch):
    from sixpack.updater import ReleaseInfo

    window._pending_release = ReleaseInfo(version="0.2.0", zipball_url="http://example.com/z.zip")
    dispatched = []
    monkeypatch.setattr(window._worker, "run", lambda tag, coro: dispatched.append(tag))

    window._on_update_install_requested()

    assert dispatched == ["apply_update"]
    assert not window._update_prompt_screen._button_row.isVisible()


def test_on_update_install_requested_is_noop_without_pending_release(window, monkeypatch):
    window._pending_release = None
    dispatched = []
    monkeypatch.setattr(window._worker, "run", lambda tag, coro: dispatched.append(tag))

    window._on_update_install_requested()

    assert dispatched == []


def test_on_result_apply_update_relaunches_and_quits(window, monkeypatch):
    """CRITICAL: must monkeypatch both relaunch and QApplication.quit --
    see this plan's Global Constraints. Calling the real .quit() would
    tear down the shared test-session QApplication."""
    from PyQt6.QtWidgets import QApplication
    from sixpack.ui import app as app_module

    relaunch_calls = []
    monkeypatch.setattr(app_module, "relaunch", lambda: relaunch_calls.append(True))
    quit_calls = []
    monkeypatch.setattr(QApplication, "quit", lambda self: quit_calls.append(True))

    window._on_result("apply_update", None)

    assert relaunch_calls == [True]
    assert quit_calls == [True]


def test_on_error_apply_update_shows_error_state(window):
    window._on_error("apply_update", "Download failed: connection refused")
    assert window._stack.currentWidget() is window._update_prompt_screen
    assert "connection refused" in window._update_prompt_screen._status_label.text()
    assert window._update_prompt_screen._continue_btn.isVisible()


def test_update_prompt_continue_after_error_proceeds_to_login(window):
    window._on_error("apply_update", "boom")
    window._update_prompt_screen.continue_requested.emit()
    assert window._stack.currentWidget() is window._login_screen
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_app.py -v --no-cov 2>&1 | tail -60`
Expected: FAIL — the `window` fixture itself fails first, with
`AttributeError: <module 'sixpack.ui.app' ...> does not have the attribute 'fetch_latest_release'` (Task 1's names aren't imported into `app.py` yet), which cascades to every test in the file failing at fixture setup. This is the expected failure shape for this step — proceed to Step 3.

- [ ] **Step 3: Implement**

In `src/sixpack/ui/app.py`:

1. Add the imports from Step 1a above.

2. In `MainWindow.__init__` (currently ~line 78-107), add `self._pending_release: ReleaseInfo | None = None` alongside the other `_pending_*` attributes (e.g. right after `self._pending_podcast_episode: PodcastEpisode | None = None` at line 90), and change the last two lines of `__init__` from:

```python
        self._init_player()
        self._init_worker()
        self._build_ui()
        self._try_autologin()
```

to:

```python
        self._init_player()
        self._init_worker()
        self._build_ui()
```

(`_build_ui()` itself now fires the update check as its last action, replacing the direct `_try_autologin()` call — see the next edit.)

3. In `_build_ui()` (currently ~line 129-204), add the new screen alongside the existing `_stack.addWidget(...)` calls (near where `_login_screen` etc. are added, before `self._setup_quit_shortcut()`):

```python
        self._update_prompt_screen = UpdatePromptScreen()
        self._stack.addWidget(self._update_prompt_screen)
        self._update_prompt_screen.install_requested.connect(self._on_update_install_requested)
        self._update_prompt_screen.later_requested.connect(self._try_autologin)
        self._update_prompt_screen.continue_requested.connect(self._try_autologin)
```

Then change the final two lines of `_build_ui()` from:

```python
        self._setup_quit_shortcut()
        self._show_splash()
```

to:

```python
        self._setup_quit_shortcut()
        self._show_splash()
        self._worker.run("check_update", fetch_latest_release())
```

4. Add a new method near `_try_autologin()` (currently ~line 206):

```python
    def _on_update_install_requested(self) -> None:
        if self._pending_release is None:
            return
        self._update_prompt_screen.show_installing()
        self._worker.run("apply_update", apply_update(self._pending_release.zipball_url))
```

5. In `_on_result` (the big `elif tag == ...:` chain), add two new branches. Place them anywhere in the chain — order among tags doesn't matter, `_on_result` dispatches purely by string match:

```python
        elif tag == "check_update":
            release = result
            if release is not None and is_newer(release.version, CURRENT_VERSION):
                self._pending_release = release
                self._update_prompt_screen.show_prompt(CURRENT_VERSION, release.version)
                self._stack.setCurrentWidget(self._update_prompt_screen)
            else:
                self._try_autologin()

        elif tag == "apply_update":
            relaunch()
            QApplication.instance().quit()
```

6. In `_on_error` (the corresponding error-dispatch chain), add:

```python
        elif tag == "check_update":
            # fetch_latest_release() fails soft internally and should
            # never actually raise -- this is a defensive backstop, not
            # an expected path.
            self._try_autologin()

        elif tag == "apply_update":
            self._update_prompt_screen.show_error(error_message)
```

(Match the exact parameter name `_on_error` already uses for the error-message argument — check the method's current signature, e.g. `def _on_error(self, tag: str, error_message: str) -> None:`, and use that same name rather than introducing a new one.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_ui/test_app.py -v --no-cov 2>&1 | tail -80`
Expected: all tests PASS, including every pre-existing test in the file (the fixture change must not have broken any of them).

Then run the full suite twice (this project's established verification habit before any commit that touches shared infrastructure like a fixture):

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --no-cov`
Expected: PASS, twice in a row.

Then run with the coverage gate to confirm nothing regressed it:
Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest`
Expected: PASS, `--cov-fail-under=80` satisfied.

Then a diff-scoped lint check (this codebase has pre-existing, unrelated ruff violations elsewhere -- never conflate them with new ones):
Run: `.venv/bin/ruff check src/sixpack/updater.py src/sixpack/ui/screens/update_prompt.py tests/test_updater/ tests/test_ui/test_update_prompt_screen.py`
Expected: clean (these are all new files with no pre-existing violations to inherit). For `src/sixpack/ui/app.py` and `tests/test_ui/test_app.py`, run `.venv/bin/ruff check src/sixpack/ui/app.py tests/test_ui/test_app.py --diff` and confirm any reported issues are pre-existing (unrelated import-ordering, etc. -- already present before this task) rather than on the lines this task actually touched.

- [ ] **Step 5: Commit**

```bash
git add src/sixpack/ui/app.py tests/test_ui/test_app.py
git commit -m "Wire startup update check and install flow into MainWindow"
```
