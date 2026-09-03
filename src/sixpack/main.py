"""Entry point for SixPack."""
from __future__ import annotations

import locale
import logging
import os
import sys

# libmpv requires LC_NUMERIC=C (decimal point must be '.' not ',') -- this
# must run before importing anything that might touch Qt/libmpv, so the
# imports below are deliberately not at the top of the file.
locale.setlocale(locale.LC_NUMERIC, "C")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from sixpack.config import AppConfig  # noqa: E402
from sixpack.ui import theme  # noqa: E402
from sixpack.ui.app import MainWindow  # noqa: E402


def _log_uncaught_exception(exc_type, exc_value, traceback_obj) -> None:
    """Log an uncaught exception instead of letting it escape to Python's
    default excepthook.

    PyQt6 aborts the *entire process* (SIGABRT, not a catchable Python
    exception) if an exception propagates out of a slot invoked via a
    queued cross-thread connection -- confirmed directly, not assumed.
    That covers most of this app's background work: every mpv playback
    callback (position/duration/state/end-of-track, all marshaled via
    QMetaObject.invokeMethod from mpv's own thread), every CoverCache
    fetch-completion signal (QThreadPool worker thread -> GUI thread),
    and AsyncWorker's own result/error signals (its asyncio thread ->
    GUI thread). A single incidental bug in any one of those -- e.g. a
    still-in-flight network callback touching a widget that's since
    been torn down -- would otherwise take the whole app down with it,
    unpredictably and without a Python traceback the user could report.

    Installing this as sys.excepthook is the standard fix: PyQt6 only
    skips its abort-on-escaped-exception behavior when *some* custom
    hook is installed at all. This one logs (so it lands in the same
    place every other log line does) and, critically, does not re-raise
    -- the app keeps running.
    """
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, traceback_obj)
        return
    logging.getLogger(__name__).critical(
        "Uncaught exception (app continues running)",
        exc_info=(exc_type, exc_value, traceback_obj),
    )


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    sys.excepthook = _log_uncaught_exception

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
