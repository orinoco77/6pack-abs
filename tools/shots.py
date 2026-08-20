"""Dev-only: render SixPack screens to PNG using real merton.home data.

Not packaged, not tested. Usage:
    .venv/bin/python tools/shots.py out/            # renders out/browse.png
Requires an ABS API token at ~/.config/sixpack/token and reachable merton.home.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QApplication

from sixpack.api.client import ABSClient
from sixpack.ui import theme
from sixpack.ui.cover_cache import CoverCache
from sixpack.ui.screens.browse import BrowseScreen, RowType

SERVER = "http://merton.home:13378"
SIZE = QSize(1920, 1080)


def _token() -> str:
    return (Path.home() / ".config" / "sixpack" / "token").read_text().strip()


async def _load(token: str):
    async with ABSClient(SERVER, token=token) as c:
        libs = await c.get_libraries()
        lib = next((l for l in libs if l.name == "Audiobooks"), libs[0])
        recent = await c.get_library_items_recent(lib.id, 20)
        series = await c.get_series(lib.id)
        playlists = await c.get_playlists(lib.id)
        shelves = await c.get_personalized_shelves(lib.id)
    cont = []
    for s in shelves:
        if "continue" in s.label.lower():
            cont = s.entities[:20]
            break
    return libs, {
        RowType.CONTINUE_LISTENING: cont,
        RowType.RECENTLY_ADDED: recent,
        RowType.SERIES: series[:20],
        RowType.PLAYLISTS: playlists[:20],
    }


def _grab(widget, path: Path) -> None:
    pix = QPixmap(SIZE)
    pix.fill(Qt.GlobalColor.black)
    widget.render(pix)
    pix.save(str(path), "PNG")


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "out")
    out.mkdir(parents=True, exist_ok=True)
    token = _token()

    app = QApplication(sys.argv)
    theme.apply(app)
    loop = asyncio.new_event_loop()
    libs, rows = loop.run_until_complete(_load(token))

    cache = CoverCache()
    screen = BrowseScreen(cover_cache=cache)
    screen.resize(SIZE)
    screen.load_libraries(libs, SERVER, token)
    for rt, items in rows.items():
        screen.set_row_items(rt, items)
    screen.show_content()
    screen.show()

    # Let cover downloads + focus effects settle, then grab.
    app.processEvents()
    loop.run_until_complete(asyncio.sleep(2.0))
    app.processEvents()
    _grab(screen, out / "browse.png")
    print(f"wrote {out / 'browse.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
