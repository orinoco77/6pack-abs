"""
Gamepad input via evdev, running in a background thread.
Emits InputActions through a callback. Handles Xbox/generic HID gamepads.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from .actions import InputAction

logger = logging.getLogger(__name__)

try:
    import evdev
    from evdev import ecodes

    _EVDEV_AVAILABLE = True
except ImportError:
    _EVDEV_AVAILABLE = False
    evdev = None  # type: ignore[assignment]
    ecodes = None  # type: ignore[assignment]


# Mapping: (event_type, code, value) -> InputAction
# EV_KEY events: value 1 = press, 0 = release, 2 = repeat
# EV_ABS events: we only care about "pressed" (value != 0 for hat axes)
_BUTTON_MAP: dict[int, InputAction] = {}

# These are populated after evdev is confirmed available
def _build_button_map() -> dict[int, InputAction]:
    if not _EVDEV_AVAILABLE:
        return {}
    return {
        ecodes.BTN_SOUTH: InputAction.SELECT,       # A / Cross
        ecodes.BTN_EAST: InputAction.BACK,           # B / Circle
        ecodes.BTN_WEST: InputAction.PLAY_PAUSE,     # X / Square
        ecodes.BTN_TL: InputAction.PREV_CHAPTER,     # LB
        ecodes.BTN_TR: InputAction.NEXT_CHAPTER,     # RB
        ecodes.BTN_SELECT: InputAction.BACK,
        # Y/Triangle and Start were mapped to InputAction.MENU, but no
        # keyboard key produces MENU anymore (this app's keyboard model
        # retired it in favour of SELECT -- see keyboard.py's _PLAYER_MAP
        # comments). Since gamepad actions are dispatched by synthesizing
        # the equivalent keyboard key event (see app.py's
        # _dispatch_gamepad_key), MENU has no synthesizable key to route
        # through and is left unmapped; the chapter overlay it used to
        # open directly is still reachable via the universal path (D-pad
        # to the chapters button, then Select), same as any basic remote.
    }


# D-pad hat axis codes and values
_HAT_MAP: dict[tuple[int, int], InputAction] = {}


def _build_hat_map() -> dict[tuple[int, int], InputAction]:
    if not _EVDEV_AVAILABLE:
        return {}
    return {
        (ecodes.ABS_HAT0X, -1): InputAction.LEFT,
        (ecodes.ABS_HAT0X, 1): InputAction.RIGHT,
        (ecodes.ABS_HAT0Y, -1): InputAction.UP,
        (ecodes.ABS_HAT0Y, 1): InputAction.DOWN,
    }


def _open_if_gamepad(path: str) -> evdev.InputDevice | None:
    """None if `path` can't be opened, or opens but isn't a gamepad (no
    BTN_SOUTH capability)."""
    try:
        dev = evdev.InputDevice(path)
        caps = dev.capabilities()
        if ecodes.EV_KEY in caps and ecodes.BTN_SOUTH in caps[ecodes.EV_KEY]:
            return dev
    except (OSError, PermissionError):
        pass
    return None


def _find_gamepads() -> list:
    if not _EVDEV_AVAILABLE:
        return []
    devices = [_open_if_gamepad(path) for path in evdev.list_devices()]
    return [d for d in devices if d is not None]


class GamepadListener:
    """
    Listens for gamepad events on all detected gamepads in background threads.
    Call start() to begin listening, stop() to shut down.
    """

    def __init__(self, callback: Callable[[InputAction], None]) -> None:
        self._callback = callback
        self._threads: list[threading.Thread] = []
        self._stop_event = threading.Event()
        self._button_map = _build_button_map()
        self._hat_map = _build_hat_map()

    def start(self) -> None:
        if not _EVDEV_AVAILABLE:
            logger.warning("evdev not available — gamepad support disabled")
            return
        gamepads = _find_gamepads()
        if not gamepads:
            logger.info("No gamepads detected")
            return
        for device in gamepads:
            t = threading.Thread(
                target=self._listen,
                args=(device,),
                daemon=True,
                name=f"gamepad-{device.name}",
            )
            self._threads.append(t)
            t.start()
            logger.info("Listening on gamepad: %s", device.name)

    def stop(self) -> None:
        self._stop_event.set()

    def _listen(self, device: evdev.InputDevice) -> None:
        try:
            for event in device.read_loop():
                if self._stop_event.is_set():
                    break
                action = self._map_event(event)
                if action is not None:
                    self._callback(action)
        except OSError as exc:
            logger.warning("Gamepad %s disconnected: %s", device.name, exc)

    def _map_event(self, event: evdev.InputEvent) -> InputAction | None:
        if not _EVDEV_AVAILABLE:
            return None
        if event.type == ecodes.EV_KEY and event.value == 1:
            return self._button_map.get(event.code)
        if event.type == ecodes.EV_ABS and event.value != 0:
            return self._hat_map.get((event.code, event.value))
        return None
