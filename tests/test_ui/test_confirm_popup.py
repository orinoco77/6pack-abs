"""Tests for ConfirmPopup -- the reusable Cancel/Confirm overlay shared by
PlayerScreen and DetailGridScreen."""
from __future__ import annotations

from sixpack.input.actions import InputAction
from sixpack.ui.widgets.confirm_popup import ConfirmPopup


def test_starts_hidden(qtbot):
    popup = ConfirmPopup()
    qtbot.addWidget(popup)
    assert not popup.isVisible()


def test_show_confirm_sets_message_and_labels(qtbot):
    popup = ConfirmPopup()
    qtbot.addWidget(popup)
    popup.show_confirm("Mark 'Book A' as finished?", confirm_label="Mark Finished")
    assert popup._message_label.text() == "Mark 'Book A' as finished?"
    assert popup._confirm_btn.text() == "Mark Finished"
    assert popup._cancel_btn.text() == "Cancel"
    assert popup.isVisible()


def test_show_confirm_defaults_focus_to_cancel(qtbot):
    popup = ConfirmPopup()
    qtbot.addWidget(popup)
    popup.show_confirm("Are you sure?")
    assert popup._focus_index == 0


def test_right_moves_focus_to_confirm(qtbot):
    popup = ConfirmPopup()
    qtbot.addWidget(popup)
    popup.show_confirm("Are you sure?")
    popup.handle_key(InputAction.RIGHT)
    assert popup._focus_index == 1


def test_right_does_not_move_past_confirm(qtbot):
    popup = ConfirmPopup()
    qtbot.addWidget(popup)
    popup.show_confirm("Are you sure?")
    popup.handle_key(InputAction.RIGHT)
    popup.handle_key(InputAction.RIGHT)
    assert popup._focus_index == 1


def test_left_does_not_move_before_cancel(qtbot):
    popup = ConfirmPopup()
    qtbot.addWidget(popup)
    popup.show_confirm("Are you sure?")
    popup.handle_key(InputAction.LEFT)
    assert popup._focus_index == 0


def test_select_on_confirm_emits_confirmed_and_hides(qtbot):
    popup = ConfirmPopup()
    qtbot.addWidget(popup)
    popup.show_confirm("Are you sure?")
    popup.handle_key(InputAction.RIGHT)
    received = []
    popup.confirmed.connect(lambda: received.append(True))

    popup.handle_key(InputAction.SELECT)

    assert received == [True]
    assert not popup.isVisible()


def test_select_on_cancel_emits_cancelled_and_hides(qtbot):
    popup = ConfirmPopup()
    qtbot.addWidget(popup)
    popup.show_confirm("Are you sure?")
    received = []
    popup.cancelled.connect(lambda: received.append(True))

    popup.handle_key(InputAction.SELECT)  # still focused on Cancel by default

    assert received == [True]
    assert not popup.isVisible()


def test_back_always_cancels_regardless_of_focus(qtbot):
    popup = ConfirmPopup()
    qtbot.addWidget(popup)
    popup.show_confirm("Are you sure?")
    popup.handle_key(InputAction.RIGHT)  # move to Confirm
    received = []
    popup.cancelled.connect(lambda: received.append(True))

    popup.handle_key(InputAction.BACK)

    assert received == [True]


def test_reopening_resets_focus_to_cancel(qtbot):
    popup = ConfirmPopup()
    qtbot.addWidget(popup)
    popup.show_confirm("First message")
    popup.handle_key(InputAction.RIGHT)
    assert popup._focus_index == 1

    popup.show_confirm("Second message")
    assert popup._focus_index == 0


def test_visible_popup_has_real_qt_focus_and_handles_keys_directly(qtbot):
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest

    popup = ConfirmPopup()
    qtbot.addWidget(popup)
    popup.show()
    qtbot.waitExposed(popup)
    popup.activateWindow()
    QTest.qWaitForWindowActive(popup)
    popup.show_confirm("Are you sure?")

    assert popup.hasFocus()

    qtbot.keyClick(popup, Qt.Key.Key_Right)
    assert popup._focus_index == 1
