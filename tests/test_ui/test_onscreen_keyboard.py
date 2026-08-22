"""Tests for OnScreenKeyboard — D-pad-navigable text entry."""
from __future__ import annotations

from PyQt6.QtCore import Qt

from sixpack.ui.widgets.onscreen_keyboard import OnScreenKeyboard


def test_creates(qtbot):
    kb = OnScreenKeyboard()
    qtbot.addWidget(kb)
    assert kb is not None


def test_select_on_default_focus_emits_first_key(qtbot):
    kb = OnScreenKeyboard()
    qtbot.addWidget(kb)
    kb.show()
    qtbot.waitExposed(kb)
    received = []
    kb.key_pressed.connect(received.append)
    qtbot.keyClick(kb, Qt.Key.Key_Return)
    assert received == ["1"]  # top-left key, per the row layout


def test_right_then_select_emits_second_key(qtbot):
    kb = OnScreenKeyboard()
    qtbot.addWidget(kb)
    kb.show()
    qtbot.waitExposed(kb)
    received = []
    kb.key_pressed.connect(received.append)
    qtbot.keyClick(kb, Qt.Key.Key_Right)
    qtbot.keyClick(kb, Qt.Key.Key_Return)
    assert received == ["2"]


def test_down_moves_to_letter_row(qtbot):
    kb = OnScreenKeyboard()
    qtbot.addWidget(kb)
    kb.show()
    qtbot.waitExposed(kb)
    received = []
    kb.key_pressed.connect(received.append)
    qtbot.keyClick(kb, Qt.Key.Key_Down)
    qtbot.keyClick(kb, Qt.Key.Key_Return)
    assert received == ["q"]


def test_back_emits_back_requested(qtbot):
    kb = OnScreenKeyboard()
    qtbot.addWidget(kb)
    kb.show()
    qtbot.waitExposed(kb)
    with qtbot.waitSignal(kb.back_requested, timeout=1000):
        qtbot.keyClick(kb, Qt.Key.Key_Escape)


def test_navigating_to_bottom_row_and_selecting_backspace(qtbot):
    kb = OnScreenKeyboard()
    qtbot.addWidget(kb)
    kb.show()
    qtbot.waitExposed(kb)
    for _ in range(4):
        qtbot.keyClick(kb, Qt.Key.Key_Down)  # from row 0 down to the bottom row
    # After 4 Downs, focus lands on the Space key (bottom row, column 0).
    # In OnScreenKeyboard's grid, Space's widget reference is repeated
    # across grid columns 0-6 (its colSpan), Backspace occupies column 7,
    # and Done spans columns 8-9. _move_focus_horizontal walks
    # column-by-column within a single keypress until it finds a
    # *different* widget than the one currently focused — so one Right
    # press moves focus off Space's whole 7-column span directly onto
    # Backspace at column 7, without needing one press per column.
    # Verified by hand-tracing the grid and confirming empirically against
    # the actual implementation (see task-3-report.md).
    with qtbot.waitSignal(kb.backspace_pressed, timeout=1000):
        qtbot.keyClick(kb, Qt.Key.Key_Right)
        qtbot.keyClick(kb, Qt.Key.Key_Return)
