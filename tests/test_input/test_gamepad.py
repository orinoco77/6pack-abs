"""Tests for gamepad input handler."""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest


def _make_ecodes():
    ec = MagicMock()
    ec.EV_KEY = 1
    ec.EV_ABS = 3
    ec.BTN_SOUTH = 304
    ec.BTN_EAST = 305
    ec.BTN_NORTH = 307
    ec.BTN_WEST = 308
    ec.BTN_TL = 310
    ec.BTN_TR = 311
    ec.BTN_SELECT = 314
    ec.BTN_START = 315
    ec.ABS_HAT0X = 16
    ec.ABS_HAT0Y = 17
    return ec


def _make_event(type_, code, value):
    ev = MagicMock()
    ev.type = type_
    ev.code = code
    ev.value = value
    return ev


@pytest.fixture(autouse=True)
def patch_evdev():
    ec = _make_ecodes()
    mock_evdev = MagicMock()
    mock_evdev.ecodes = ec
    with patch.dict("sys.modules", {"evdev": mock_evdev, "evdev.ecodes": ec}):
        if "sixpack.input.gamepad" in sys.modules:
            del sys.modules["sixpack.input.gamepad"]
        yield mock_evdev
    if "sixpack.input.gamepad" in sys.modules:
        del sys.modules["sixpack.input.gamepad"]


@pytest.fixture
def listener(patch_evdev):
    from sixpack.input.gamepad import GamepadListener
    actions = []
    gl = GamepadListener(callback=actions.append)
    return gl, actions


def test_button_south_maps_to_select(listener):
    gl, _actions = listener
    ec = _make_ecodes()
    event = _make_event(ec.EV_KEY, ec.BTN_SOUTH, 1)
    action = gl._map_event(event)
    from sixpack.input.actions import InputAction
    assert action == (InputAction.SELECT, True)


def test_button_east_maps_to_back(listener):
    gl, _actions = listener
    ec = _make_ecodes()
    event = _make_event(ec.EV_KEY, ec.BTN_EAST, 1)
    action = gl._map_event(event)
    from sixpack.input.actions import InputAction
    assert action == (InputAction.BACK, True)


def test_button_release_reports_press_false(listener):
    gl, _actions = listener
    ec = _make_ecodes()
    event = _make_event(ec.EV_KEY, ec.BTN_SOUTH, 0)  # release
    result = gl._map_event(event)
    from sixpack.input.actions import InputAction
    assert result == (InputAction.SELECT, False)


def test_key_repeat_event_ignored(listener):
    """value == 2 (autorepeat) must be ignored for both press and release
    detection, matching keyboard.py's isAutoRepeat() handling."""
    gl, _actions = listener
    ec = _make_ecodes()
    event = _make_event(ec.EV_KEY, ec.BTN_SOUTH, 2)
    result = gl._map_event(event)
    assert result is None


def test_unmapped_button_release_returns_none(listener):
    gl, _actions = listener
    ec = _make_ecodes()
    event = _make_event(ec.EV_KEY, 999, 0)
    result = gl._map_event(event)
    assert result is None


def test_dpad_left(listener):
    gl, _actions = listener
    ec = _make_ecodes()
    event = _make_event(ec.EV_ABS, ec.ABS_HAT0X, -1)
    action = gl._map_event(event)
    from sixpack.input.actions import InputAction
    assert action == (InputAction.LEFT, True)


def test_dpad_right(listener):
    gl, _actions = listener
    ec = _make_ecodes()
    event = _make_event(ec.EV_ABS, ec.ABS_HAT0X, 1)
    action = gl._map_event(event)
    from sixpack.input.actions import InputAction
    assert action == (InputAction.RIGHT, True)


def test_dpad_up(listener):
    gl, _actions = listener
    ec = _make_ecodes()
    event = _make_event(ec.EV_ABS, ec.ABS_HAT0Y, -1)
    action = gl._map_event(event)
    from sixpack.input.actions import InputAction
    assert action == (InputAction.UP, True)


def test_dpad_down(listener):
    gl, _actions = listener
    ec = _make_ecodes()
    event = _make_event(ec.EV_ABS, ec.ABS_HAT0Y, 1)
    action = gl._map_event(event)
    from sixpack.input.actions import InputAction
    assert action == (InputAction.DOWN, True)


def test_dpad_center_ignored(listener):
    gl, _actions = listener
    ec = _make_ecodes()
    event = _make_event(ec.EV_ABS, ec.ABS_HAT0X, 0)
    action = gl._map_event(event)
    assert action is None


def test_lb_maps_to_prev_chapter(listener):
    gl, _actions = listener
    ec = _make_ecodes()
    event = _make_event(ec.EV_KEY, ec.BTN_TL, 1)
    action = gl._map_event(event)
    from sixpack.input.actions import InputAction
    assert action == (InputAction.PREV_CHAPTER, True)


def test_rb_maps_to_next_chapter(listener):
    gl, _actions = listener
    ec = _make_ecodes()
    event = _make_event(ec.EV_KEY, ec.BTN_TR, 1)
    action = gl._map_event(event)
    from sixpack.input.actions import InputAction
    assert action == (InputAction.NEXT_CHAPTER, True)


def test_start_is_unmapped(listener):
    """MENU has no synthesizable keyboard key to route through anymore
    (see gamepad.py's _build_button_map comment) -- Start is intentionally
    left unmapped rather than firing a dead action."""
    gl, _actions = listener
    ec = _make_ecodes()
    event = _make_event(ec.EV_KEY, ec.BTN_START, 1)
    action = gl._map_event(event)
    assert action is None


def test_unmapped_button_returns_none(listener):
    gl, _actions = listener
    ec = _make_ecodes()
    event = _make_event(ec.EV_KEY, 999, 1)
    action = gl._map_event(event)
    assert action is None


def test_listen_callback_receives_action_and_is_press(patch_evdev):
    from sixpack.input.gamepad import GamepadListener
    ec = _make_ecodes()

    class _FakeDevice:
        name = "fake"
        def read_loop(self):
            yield _make_event(ec.EV_KEY, ec.BTN_SOUTH, 1)
            yield _make_event(ec.EV_KEY, ec.BTN_SOUTH, 0)

    received = []
    gl = GamepadListener(callback=lambda action, is_press: received.append((action, is_press)))
    gl._listen(_FakeDevice())

    from sixpack.input.actions import InputAction
    assert received == [(InputAction.SELECT, True), (InputAction.SELECT, False)]


def test_start_with_no_gamepads_does_not_raise(patch_evdev):
    patch_evdev.list_devices.return_value = []
    from sixpack.input.gamepad import GamepadListener
    gl = GamepadListener(callback=lambda a: None)
    gl.start()  # should not raise


def test_stop_sets_event(patch_evdev):
    from sixpack.input.gamepad import GamepadListener
    gl = GamepadListener(callback=lambda a: None)
    gl.stop()
    assert gl._stop_event.is_set()


def test_no_evdev_start_logs_warning(patch_evdev):
    """When evdev is unavailable, start() should warn and not crash."""
    with patch.dict("sys.modules", {"evdev": None}):
        if "sixpack.input.gamepad" in sys.modules:
            del sys.modules["sixpack.input.gamepad"]
        import importlib
        mod = importlib.import_module("sixpack.input.gamepad")
        assert mod._EVDEV_AVAILABLE is False
        gl = mod.GamepadListener(callback=lambda a: None)
        gl.start()  # should not raise
    if "sixpack.input.gamepad" in sys.modules:
        del sys.modules["sixpack.input.gamepad"]
