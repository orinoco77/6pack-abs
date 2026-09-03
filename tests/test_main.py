"""Tests for the main entry point's crash-guard exception hook."""
from __future__ import annotations

import logging
import sys

from sixpack.main import _log_uncaught_exception


def test_log_uncaught_exception_logs_instead_of_raising(caplog):
    try:
        raise ValueError("boom")
    except ValueError:
        exc_info = sys.exc_info()

    with caplog.at_level(logging.CRITICAL):
        _log_uncaught_exception(*exc_info)  # must not raise / must not abort

    assert "boom" in caplog.text


def test_log_uncaught_exception_passes_keyboard_interrupt_to_default_hook(monkeypatch):
    calls = []
    monkeypatch.setattr(sys, "__excepthook__", lambda *a: calls.append(a))
    try:
        raise KeyboardInterrupt()
    except KeyboardInterrupt:
        exc_info = sys.exc_info()

    _log_uncaught_exception(*exc_info)

    assert len(calls) == 1
    assert calls[0][0] is KeyboardInterrupt
