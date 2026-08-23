"""Tests for UpdatePromptScreen -- the startup prompt offering to install
a newer release."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QLabel, QStackedWidget

from sixpack.ui.screens.update_prompt import UpdatePromptScreen


def _make_screen(qtbot):
    screen = UpdatePromptScreen()
    qtbot.addWidget(screen)
    screen.show()
    qtbot.waitExposed(screen)
    screen.activateWindow()
    QTest.qWaitForWindowActive(screen)
    return screen


def test_gains_real_focus_when_switched_to_in_a_stack(qtbot):
    """Regression: the screen never actually worked with a keyboard/remote
    in the real app. _make_screen()'s isolated show()+activateWindow()
    happens to auto-focus a lone top-level StrongFocus widget, masking
    the bug -- every other screen test in this suite uses the same
    pattern for the same reason. But app.py never shows this screen
    standalone; it's one page of MainWindow's QStackedWidget, switched to
    via setCurrentWidget(), which does NOT hand a newly-current page real
    Qt focus by itself. Every other screen handles this with a showEvent
    override that calls self.setFocus() -- this screen was missing one.
    This test embeds the screen in a QStackedWidget exactly like app.py
    does, as a non-initial page, to catch that class of bug for real."""
    stack = QStackedWidget()
    qtbot.addWidget(stack)
    placeholder = QLabel("placeholder")
    stack.addWidget(placeholder)
    screen = UpdatePromptScreen()
    stack.addWidget(screen)
    screen.show_prompt("0.2.0", "0.3.0")

    stack.show()
    qtbot.waitExposed(stack)
    stack.activateWindow()
    QTest.qWaitForWindowActive(stack)
    stack.setCurrentWidget(screen)  # exactly what app.py's dispatch does

    assert screen.hasFocus()


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


def test_right_then_left_returns_focus_to_install(qtbot):
    screen = _make_screen(qtbot)
    screen.show_prompt("0.2.0", "0.3.0")
    qtbot.keyClick(screen, Qt.Key.Key_Right)
    assert screen._focus_index == 1
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
