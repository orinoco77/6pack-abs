"""Tests for QRCodeWidget."""
from __future__ import annotations

from sixpack.ui.widgets.qr_code import QRCodeWidget


def test_qr_code_widget_creates(qtbot):
    widget = QRCodeWidget()
    qtbot.addWidget(widget)
    assert widget is not None


def test_set_data_builds_matrix(qtbot):
    widget = QRCodeWidget()
    qtbot.addWidget(widget)
    widget.set_data("http://192.168.1.10:8080/?code=ABC123")
    assert widget._matrix
    assert len(widget._matrix) > 0
    assert all(len(row) == len(widget._matrix) for row in widget._matrix)  # QR matrices are square


def test_set_data_empty_string_does_not_crash(qtbot):
    widget = QRCodeWidget()
    qtbot.addWidget(widget)
    widget.set_data("")  # qrcode raises on empty data internally — confirm this is handled gracefully
