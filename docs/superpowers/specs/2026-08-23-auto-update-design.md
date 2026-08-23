# Auto-Update Design

## Problem

SixPack is deployed to end-user machines (currently just `cholet`, a Linux
Mint TV box) by downloading a zip of the repo from GitHub, extracting it,
and running `install.sh`, which does `uv tool install --reinstall
<extracted-dir>`. There is no git dependency for end users — this must stay
true. Getting a new version onto the machine today means the user manually
repeating that whole process. This feature makes that automatic: the app
checks for a newer release at startup, and if one exists, offers to
download and install it itself.

## Non-goals

- Not building a fleet/multi-device update system — this is single-machine,
  single-user in practice.
- Not reinstalling system package dependencies (`apt` packages `install.sh`
  handles via `install_system_deps`). If a future release needs a new
  system library, that still requires a manual `install.sh` rerun. This is
  an accepted limitation, not something this feature covers.
- Not building a custom atomic-swap deployment mechanism. `uv tool install
  --reinstall` already keeps a single fixed venv directory per package name
  (keyed by the `sixpack-abs` package name) — there is no proliferation of
  installed copies with the existing mechanism, so no new versioned-venv/
  symlink scheme is being introduced. This feature only has to guarantee
  that *its own* transient files (downloaded zip, extracted contents) are
  always cleaned up, and that a failed update never leaves the app in a
  worse state than before the check ran.
- Not persisting a "skip this version" choice. Declining an offered update
  just asks again next launch.
- Not adding a manual "check for updates" entry point (e.g. in a settings
  screen). Startup-only for v1.

## Versioning

Semantic version in `pyproject.toml`'s `[project] version` field is the
source of truth. A release is: bump that field, merge to `main`, tag the
commit (`vX.Y.Z`), and create a GitHub Release from that tag (via the
GitHub web UI or `gh release create` — a manual, human step outside the
app's scope; there is no CI automation for this in v1). GitHub
automatically attaches a source zip to every release/tag — no build step or
custom release asset is required; it's the same content a user gets today
from the repo's "Download ZIP" button, just pinned to a tagged commit
instead of a floating branch HEAD.

The app determines its own current version via
`importlib.metadata.version("sixpack-abs")` at runtime (already true today
via `uv tool install`, no new file to maintain).

The repo is hardcoded as `orinoco77/6pack-abs` (matches the existing `git
remote -v` origin). There is no `[project.urls]` entry in `pyproject.toml`
today to derive this from.

## Architecture

A new `src/sixpack/updater.py` module owns the whole update lifecycle:
checking GitHub's Releases API, comparing versions, downloading the
release's auto-generated source zip, extracting it, and shelling out to
`uv tool install --reinstall <extracted-dir>` — the exact command
`install.sh` already runs. It reuses `httpx` (already a dependency, used by
`ABSClient`) for both the API call and the zip download, and plugs into the
existing `AsyncWorker`/`_on_result` tag-dispatch pattern already used
throughout `app.py` for every other async operation — no new concurrency
primitives.

On startup, right after the splash screen appears (before `_try_autologin`
runs), `MainWindow` fires a `check_update` job with a short timeout. If it
finds a newer semantic version, it shows a blocking modal-style screen
before the rest of startup (login/autologin, then Home) is reachable.
Confirming triggers `apply_update` (download → extract → `uv tool install
--reinstall`) → on success, spawn a new detached `sixpack` process and quit
the current one. Any failure at any stage (offline, GitHub unreachable,
malformed response, `uv` missing, bad zip, nonzero install exit) is caught,
logged, and simply lets the current install keep running untouched — never
a partial/broken state, never a crash. Declining, or the check finding
nothing newer, or the check itself failing, all fall through to today's
`_try_autologin()` unchanged — from the user's perspective, when there's
nothing to offer, startup looks and behaves exactly as it does today.

## Components

### `src/sixpack/updater.py` (new, plain Python — no Qt)

Pure logic, independently testable with `respx` (HTTP) and `monkeypatch`
(subprocess), matching how `ABSClient` and `CoverCache` are tested today.

```python
from __future__ import annotations

import asyncio
import importlib.metadata
import shutil
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
    version: str          # e.g. "0.3.0" (leading "v" stripped from tag_name)
    zipball_url: str


class UpdateError(Exception):
    """Raised by the apply-update path (download/extract/install failure).
    Never raised by fetch_latest_release, which fails soft (returns None).
    """


async def fetch_latest_release() -> ReleaseInfo | None:
    """Return the latest published GitHub release, or None if unavailable
    for any reason (offline, rate-limited, malformed response, no releases
    yet). Never raises — this must never block or break startup.
    """
    try:
        async with httpx.AsyncClient(timeout=_API_TIMEOUT) as client:
            response = await client.get(
                f"https://api.github.com/repos/{REPO}/releases/latest",
                headers={"Accept": "application/vnd.github+json"},
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
    """Dotted-integer version comparison, e.g. "0.10.0" > "0.9.0". Assumes
    well-formed "N.N.N"-style versions (this project controls both sides —
    no external packages publish versions here), falling back to False on
    anything that doesn't parse rather than risk a bad update loop.
    """
    try:
        latest_parts = tuple(int(p) for p in latest.split("."))
        current_parts = tuple(int(p) for p in current.split("."))
    except ValueError:
        return False
    return latest_parts > current_parts


async def download_and_extract(zipball_url: str, dest_dir: Path) -> Path:
    """Download the release zip into dest_dir and extract it. Returns the
    path to the single top-level directory GitHub's generated zips always
    contain (named "{repo}-{sha}"), which is what `uv tool install` needs
    pointed at (it must find pyproject.toml at its root).

    Raises UpdateError on any failure. Caller owns dest_dir's lifetime
    (create a fresh tempfile.TemporaryDirectory() per attempt, always
    cleaned up by the caller — nothing here is ever left behind).
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
        raise UpdateError(f"Expected exactly one extracted directory, found {len(extracted)}")
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
    raise UpdateError(f"Could not locate '{name}' — is it installed and on PATH?")


async def install(source_dir: Path) -> None:
    """Run the same install command install.sh's install_app() uses.
    Raises UpdateError on a nonzero exit; the existing install is uv's
    responsibility to leave in a working state (see Non-goals).
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
    quitting the current process/QApplication immediately after — this
    function does not exit the current process itself, keeping it testable
    without actually tearing down the test process.
    """
    import subprocess

    sixpack = _find_executable("sixpack")
    subprocess.Popen([sixpack], start_new_session=True)
```

### `src/sixpack/ui/screens/update_prompt.py` (new)

Follows `LoginScreen`'s convention: real Qt focus stays on `self`
(`setFocusPolicy(Qt.FocusPolicy.StrongFocus)`), `keyPressEvent` interprets
Left/Right to move between Install/Later and Enter/Return/Select to
activate, styling driven by `theme` constants (focus ring/accent color
matching the rest of the app).

Three visual states, driven by explicit methods (no internal state
machine beyond "which state am I showing" — a single `QStackedLayout` of
three simple sub-widgets, or three groups of widgets whose visibility is
toggled, whichever keeps the file smallest):

- `show_prompt(current_version: str, new_version: str)` — "Update
  available: v{current} → v{new}", with Install / Later. This is the only
  state with real button focus-navigation.
- `show_installing()` — "Updating…" (reuses the same styling as
  `SplashScreen._status_label`). No interactive elements.
- `show_error(message: str)` — the error message plus a single "Continue"
  button.

Signals: `install_requested`, `later_requested`, `continue_requested`.

### `app.py` wiring

Two new `AsyncWorker` tags:

- `check_update` — fired once, right after `_show_splash()`, in
  `_build_ui()`, via `self._worker.run("check_update",
  updater.fetch_latest_release())`. This runs concurrently with nothing
  else (autologin does not start until this resolves) so there's no
  ordering hazard with existing startup state.
- `apply_update` — fired when `UpdatePromptScreen.install_requested` fires,
  via `self._worker.run("apply_update",
  updater.apply_update(release.zipball_url))`. The pending `ReleaseInfo` is
  held on `self._pending_release` (set when `check_update` resolves with a
  release to offer), following the same "stash on self, consume in the
  result handler" convention already used for `_pending_playlist_item` etc.

`_on_result` additions:

```python
elif tag == "check_update":
    release = result
    if release is not None and updater.is_newer(release.version, updater.CURRENT_VERSION):
        self._pending_release = release
        self._update_prompt_screen.show_prompt(updater.CURRENT_VERSION, release.version)
        self._stack.setCurrentWidget(self._update_prompt_screen)
    else:
        self._try_autologin()

elif tag == "apply_update":
    updater.relaunch()
    QApplication.instance().quit()
```

`_on_error` addition:

```python
elif tag == "check_update":
    # fetch_latest_release() fails soft internally and should never raise —
    # this branch is a defensive backstop, not an expected path.
    self._try_autologin()

elif tag == "apply_update":
    self._update_prompt_screen.show_error(error_message)
```

`self._pending_release: ReleaseInfo | None = None` is added to
`MainWindow.__init__`'s attribute list, alongside the other
`_pending_*` fields (`_pending_book`, `_pending_playlist_item`, etc.).

New screen wiring in `_build_ui()`, alongside the existing
`_stack.addWidget(...)` calls:

```python
self._update_prompt_screen = UpdatePromptScreen()
self._stack.addWidget(self._update_prompt_screen)
self._update_prompt_screen.install_requested.connect(self._on_update_install_requested)
self._update_prompt_screen.later_requested.connect(self._try_autologin)
self._update_prompt_screen.continue_requested.connect(self._try_autologin)
```

```python
def _on_update_install_requested(self) -> None:
    if self._pending_release is None:
        return
    self._update_prompt_screen.show_installing()
    self._worker.run("apply_update", updater.apply_update(self._pending_release.zipball_url))
```

And in `_build_ui()`, replacing the direct call to `_try_autologin()` at
the end of `__init__` with the update check:

```python
self._worker.run("check_update", updater.fetch_latest_release())
```

(`_try_autologin()` itself is unchanged — it's just no longer called
directly from `__init__`; it's now called from the `check_update` result
handler, on Later, and on Continue-after-error. All three are exactly the
"proceed with startup as normal" path.)

## Data flow

**Happy path, nothing new:** splash → `check_update` resolves with `None`
or a not-newer version → `_try_autologin()` → today's flow, unchanged.

**Happy path, update offered and installed:** splash → `check_update`
resolves with a newer `ReleaseInfo` → `UpdatePromptScreen.show_prompt()` →
user presses Install → `show_installing()` → `apply_update` downloads,
extracts, runs `uv tool install --reinstall` → succeeds → `relaunch()`
spawns a new `sixpack` process → current `QApplication` quits.

**Declined:** update prompt shown → user presses Later →
`_try_autologin()` → today's flow. Asks again next launch (no persisted
skip state, per Non-goals).

**Update check itself fails:** any exception inside
`fetch_latest_release()` is caught internally and it returns `None` — this
looks identical to "no update available" from the caller's perspective.
The `_on_error("check_update", ...)` branch is a defensive backstop only;
under normal operation it should never fire.

**Apply-update fails:** any exception during download/extract/install
(surfaces as `UpdateError`, or any other exception) propagates out of the
`apply_update()` coroutine, is caught by `AsyncWorker._run_coro`'s existing
try/except, and reaches `_on_error("apply_update", message)`. Shows the
error state; "Continue" proceeds to `_try_autologin()` exactly as if no
update had ever been offered. The temp directory used for download/extract
is always cleaned up (it's a `tempfile.TemporaryDirectory()` context
manager in `apply_update()`, so this holds regardless of where in the
sequence the failure happened) — nothing from a failed attempt is left on
disk. The existing install itself is untouched unless `uv tool install
--reinstall` was actually invoked and partway through failure — that
failure mode is uv's own responsibility per Non-goals, not something this
feature adds custom recovery for.

## Error handling

| Failure | Where caught | Effect |
|---|---|---|
| GitHub unreachable / timeout / rate-limited | Inside `fetch_latest_release()` | Returns `None`; startup proceeds exactly as today |
| Malformed API response (missing tag/zipball fields) | Inside `fetch_latest_release()` | Returns `None`; same as above |
| Version string doesn't parse as dotted integers | Inside `is_newer()` | Returns `False`; no update offered |
| Zip download fails / non-200 | `download_and_extract()` raises `UpdateError` | Surfaces in error state via `_on_error` |
| Corrupt/invalid zip | `download_and_extract()` raises `UpdateError` | Same |
| `uv` not found on PATH or `~/.local/bin` | `_find_executable()` raises `UpdateError` | Same |
| `uv tool install --reinstall` nonzero exit | `install()` raises `UpdateError` | Same |
| `sixpack` not found at relaunch time (should be unreachable — install just succeeded) | `_find_executable()` raises `UpdateError` | Propagates as an unhandled exception in the `apply_update`-result handler; acceptable since reaching this state means the install step itself already reported success incorrectly, an edge case not worth defensive-coding around further |

## Testing

- `tests/test_updater.py` (new): `respx`-mocked tests for
  `fetch_latest_release()` (200 with valid/malformed payload, non-200,
  network error, timeout) and `download_and_extract()` (successful
  zip, non-200, corrupt zip, wrong extracted-entry count). `is_newer()`
  gets plain parametrized cases (including malformed version strings).
  `install()` and `relaunch()`/`_find_executable()` tested with
  `monkeypatch` faking `shutil.which`, `Path.home`, and
  `asyncio.create_subprocess_exec`/`subprocess.Popen` — no real
  subprocesses spawned in tests.
- `tests/test_ui/test_update_prompt_screen.py` (new): `pytest-qt` test for
  the three visual states and Left/Right/Enter keyboard navigation,
  following the same structure as `test_login_screen.py`.
- `tests/test_ui/test_app.py` additions: `check_update` /
  `apply_update` dispatch tests using the existing `window` fixture,
  following the same `_on_result`/`_on_error` pattern already used for
  every other tag (e.g. `test_on_result_playlist_single_chapter_sets_
  playlist_detail_back_target` from the most recent playlist fix).
