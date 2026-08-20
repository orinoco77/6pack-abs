# tools/ (dev-only)

`shots.py` renders SixPack screens to PNG using real data from merton.home for
visual iteration. Not shipped in the package, not covered by tests.

    .venv/bin/python tools/shots.py out/

Requires an ABS API token at `~/.config/sixpack/token`.
