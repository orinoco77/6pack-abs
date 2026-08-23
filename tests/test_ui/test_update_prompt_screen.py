"""Tests for UpdatePromptScreen -- the startup prompt offering to install
a newer release."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest

from sixpack.ui.screens.update_prompt import UpdatePromptScreen


def _make_screen(qtbot):
    screen = UpdatePromptScreen()
    qtbot.addWidget(screen)
    screen.show()
    qtbot.waitExposed(screen)
    screen.activateWindow()
    QTest.qWaitForWindowActive(screen)
    return screen


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
