"""Entry point for SixPack."""
from __future__ import annotations

import locale
import logging
import os
import sys

# libmpv requires LC_NUMERIC=C (decimal point must be '.' not ',')
locale.setlocale(locale.LC_NUMERIC, "C")

from PyQt6.QtWidgets import QApplication

from sixpack.config import AppConfig
from sixpack.ui import theme
from sixpack.ui.app import MainWindow


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    # Force offscreen rendering in CI / headless environments
    if "QT_QPA_PLATFORM" not in os.environ and not os.environ.get("DISPLAY"):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"

    app = QApplication(sys.argv)
    app.setApplicationName("SixPack")
    app.setOrganizationName("sixpack")

    theme.apply(app)

    config = AppConfig.load()
    window = MainWindow(config)
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
