# SixPack

A 10-foot Linux client for [Audiobookshelf](https://www.audiobookshelf.org/), built for a TV screen and a remote/gamepad rather than a mouse and keyboard.

SixPack talks to your own self-hosted Audiobookshelf server, and is designed to be fully operable with nothing more than **Up / Down / Left / Right / Select / Back** — the baseline every basic remote and every gamepad can produce — with keyboard shortcuts and gamepad extras layered on top as bonus paths, never the only path to anything.

## Features

- Cinematic dark UI: library browsing by rows (Continue Listening, Recently Added, Series, Playlists), series/playlist/podcast detail grids, and a full-screen now-playing view with cover art, description, and a themed transport control row.
- Playback via [mpv](https://mpv.io/) (through [python-mpv](https://github.com/jaseg/python-mpv)), with resume position, progress sync back to the server, and chapter navigation.
- Pairing flow for setting up a new device without a keyboard: scan a QR code from your phone, or discover servers automatically on your LAN.
- In-app auto-update, checking GitHub releases and self-installing new versions.
- Keyboard, gamepad (via `evdev`), and remote-control input, all mapped to the same underlying set of actions.

## Installing

Requires Linux (X11 or Wayland), Python 3.10+, and [`uv`](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/orinoco77/6pack-abs.git
cd 6pack-abs
bash install.sh
```

`install.sh` installs system dependencies it can detect (`libmpv`, Qt's XCB platform plugin libraries) via `apt` where available, then installs SixPack itself with `uv tool install`, and adds a desktop entry so it shows up in your app launcher. Launch it with `sixpack`, or via the launcher entry.

To uninstall:

```bash
bash install.sh --uninstall
```

On first launch, pair a device (via the on-screen QR code or LAN auto-discovery) or log in directly with your Audiobookshelf server's URL and your account credentials.

### Optional: gamepad support

Gamepad input needs the `evdev` extra:

```bash
uv tool install --reinstall '.[gamepad]'
```

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,gamepad]"
```

Run the test suite:

```bash
pytest
```

Tests run headless (`QT_QPA_PLATFORM=offscreen`, set automatically by `tests/conftest.py`) and in parallel via `pytest-xdist` by default. Lint with:

```bash
ruff check src/ tests/
```

Both are gated in CI on every pull request against `main` (see `.github/workflows/ci.yml`).

### Project layout

- `src/sixpack/ui/` — screens and widgets (PyQt6)
- `src/sixpack/api/` — the Audiobookshelf REST client and Pydantic models
- `src/sixpack/player/` — the mpv-backed audio player
- `src/sixpack/input/` — keyboard/gamepad-to-action mapping
- `src/sixpack/pairing/`, `src/sixpack/discovery/` — the no-keyboard device pairing flow
- `src/sixpack/updater.py` — the in-app auto-updater

## Releasing

Versioning and releases are automated: every push to `main` bumps `pyproject.toml`'s patch version (`.github/workflows/bump-version.yml`), and `.github/workflows/release.yml` is a manually-triggered workflow that tags the current version and publishes a GitHub Release, which is what the in-app updater checks against.

## License

MIT — see [LICENSE](LICENSE).
