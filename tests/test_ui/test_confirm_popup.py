"""Tests for ConfirmPopup -- the reusable Cancel/Confirm overlay shared by
PlayerScreen and DetailGridScreen."""
from __future__ import annotations

from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QWidget

from sixpack.input.actions import InputAction
from sixpack.ui.widgets.confirm_popup import ConfirmPopup


def test_background_actually_paints_opaque(qtbot):
    """Bug repro: ConfirmPopup subclasses plain QWidget, whose stylesheet
    `background` property is silently NOT painted unless
    WA_StyledBackground is set -- the same well-known Qt quirk this
    codebase already works around in chapter_select.py and browse.py.
    Without it, the popup's border still shows but its interior stays
    whatever's behind it (the book grid), making the confirm/cancel text
    hard to read exactly as reported."""
    popup = ConfirmPopup()
    qtbot.addWidget(popup)
    assert popup.testAttribute(Qt.WidgetAttribute.WA_StyledBackground)


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


def test_autorepeat_select_keypress_is_ignored(qtbot):
    """Bug repro: the popup is opened by a long-press-and-hold on Select
    (FocusGrid's 500ms hold gesture), so the Select key is often still
    physically down at the moment show_confirm() grabs real Qt focus. The
    OS keeps sending auto-repeated KeyPress(Select) events for as long as
    that key stays down, now delivered straight to this newly-focused
    popup -- which must NOT treat one of those as a real activation, or
    the still-held key instantly "clicks" whichever button is focused
    (Cancel, by default) before the user ever sees the popup. Only a
    genuine (non-autorepeat) press -- after the key has actually been
    released and pressed again -- may activate a button."""
    popup = ConfirmPopup()
    qtbot.addWidget(popup)
    popup.show_confirm("Are you sure?")
    received = []
    popup.cancelled.connect(lambda: received.append(True))
    popup.confirmed.connect(lambda: received.append(True))

    repeat_event = QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier, "", True
    )
    popup.keyPressEvent(repeat_event)

    assert received == []
    assert popup.isVisible()


def test_non_autorepeat_select_keypress_still_activates(qtbot):
    """The real, deliberate press (after the long-press key was released)
    must still work -- only autorepeat presses are ignored."""
    popup = ConfirmPopup()
    qtbot.addWidget(popup)
    popup.show_confirm("Are you sure?")
    received = []
    popup.cancelled.connect(lambda: received.append(True))

    fresh_event = QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier, "", False
    )
    popup.keyPressEvent(fresh_event)

    assert received == [True]
    assert not popup.isVisible()


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


# ---------------------------------------------------------------------------
# Modal mouse-input shield ("scrim")
#
# ConfirmPopup is a small centered widget, not full-screen -- keyboard input
# is already gated (this popup takes real Qt focus in show_confirm(), so
# keyPressEvent naturally routes here regardless of what else is on screen),
# but mouse input isn't gated by focus at all. Without a full-host shield,
# clicking/hovering a card elsewhere on the host screen would still reach
# it and fire its own signals -- see the fix's real-world repro: hovering a
# different card while this popup is open would call FocusGrid.focus_item()
# -> self.setFocus(), stealing real Qt focus away from the still-visible
# popup.
# ---------------------------------------------------------------------------


def test_scrim_parented_to_host_not_to_popup(qtbot):
    """The scrim must cover the whole host screen, not just this popup's
    own small area -- so it has to be a sibling of the popup (parented to
    the same host the popup itself was constructed with), not a child."""
    host = QWidget()
    qtbot.addWidget(host)
    popup = ConfirmPopup(host)
    qtbot.addWidget(popup)

    assert popup._scrim.parentWidget() is host
    assert popup._scrim.parentWidget() is not popup


def test_show_confirm_shows_and_sizes_scrim_to_host(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    host.resize(1000, 700)
    host.show()
    popup = ConfirmPopup(host)
    qtbot.addWidget(popup)

    popup.show_confirm("Are you sure?")

    assert popup._scrim.isVisible()
    assert popup._scrim.geometry() == host.rect()


def test_show_confirm_raises_popup_above_scrim(qtbot):
    """The popup's own Cancel/Confirm buttons must stay clickable -- the
    popup itself has to end up on top of its own shield, not underneath
    it."""
    host = QWidget()
    qtbot.addWidget(host)
    host.resize(600, 400)
    popup = ConfirmPopup(host)
    qtbot.addWidget(popup)

    popup.show_confirm("Are you sure?")

    # The point at the popup's own center is covered by the popup (or one
    # of its descendants, e.g. a button/label), never by the scrim sitting
    # underneath it.
    pos = popup.mapTo(host, popup.rect().center())
    topmost = host.childAt(pos)
    assert topmost is not popup._scrim


def test_scrim_hidden_when_popup_never_had_a_host(qtbot):
    """Regression: constructing ConfirmPopup() with no parent (as several
    existing tests in this file do) must not crash show_confirm() -- there
    is no host to shield, so the scrim simply stays hidden."""
    popup = ConfirmPopup()
    qtbot.addWidget(popup)

    popup.show_confirm("Are you sure?")  # must not raise

    assert not popup._scrim.isVisible()


def test_activate_cancel_hides_scrim(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    host.resize(600, 400)
    host.show()
    popup = ConfirmPopup(host)
    qtbot.addWidget(popup)
    popup.show_confirm("Are you sure?")
    assert popup._scrim.isVisible()

    popup.handle_key(InputAction.SELECT)  # Cancel is focused by default

    assert not popup._scrim.isVisible()


def test_activate_confirm_hides_scrim(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    host.resize(600, 400)
    host.show()
    popup = ConfirmPopup(host)
    qtbot.addWidget(popup)
    popup.show_confirm("Are you sure?")
    popup.handle_key(InputAction.RIGHT)  # move to Confirm
    assert popup._scrim.isVisible()

    popup.handle_key(InputAction.SELECT)

    assert not popup._scrim.isVisible()


def test_update_scrim_geometry_follows_host_resize(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    host.resize(600, 400)
    popup = ConfirmPopup(host)
    qtbot.addWidget(popup)
    popup.show_confirm("Are you sure?")

    host.resize(1200, 900)
    popup.update_scrim_geometry()

    assert popup._scrim.geometry() == host.rect()


def test_scrim_shields_a_different_card_from_real_hover_and_click(qtbot):
    """End-to-end regression, mirroring the real bug: with the popup open
    on a host screen, a real mouse hover/click over some OTHER widget
    elsewhere on that screen must land on the shield, not on that widget --
    Qt delivers mouse/enter/leave events to whichever widget is topmost
    under the cursor, so the shield (once raised) makes it impossible for
    the event to ever reach the widget underneath, regardless of what
    signal that widget would otherwise have emitted."""
    host = QWidget()
    qtbot.addWidget(host)
    host.resize(400, 300)
    other = QWidget(host)
    other.setGeometry(20, 20, 100, 50)
    other.show()
    popup = ConfirmPopup(host)
    qtbot.addWidget(popup)
    # Positioned away from `other`, mirroring how a real host's resizeEvent
    # centers this popup on itself -- this test isolates the shield's own
    # coverage, not the popup's own (separately tested) on-top-of-its-shield
    # stacking.
    popup.setGeometry(250, 150, 100, 80)
    host.show()
    qtbot.waitExposed(host)

    pos = other.mapTo(host, other.rect().center())
    assert host.childAt(pos) is other  # sanity check before the popup opens

    popup.show_confirm("Are you sure?")

    assert host.childAt(pos) is popup._scrim
