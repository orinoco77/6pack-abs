"""mpv-based audio player with Qt signal integration."""
from __future__ import annotations

import locale
import threading
from typing import Callable

try:
    import mpv as _mpv

    _MPV_AVAILABLE = True
except (ImportError, OSError):
    _MPV_AVAILABLE = False
    _mpv = None  # type: ignore[assignment]


SEEK_SHORT = 30.0
SEEK_LONG = 300.0


class PlayerError(Exception):
    pass


class AudioPlayer:
    """
    Thin wrapper around python-mpv that exposes a simple playback interface
    and fires Python callbacks on position/state changes.

    All callbacks are invoked from the mpv event thread — callers that update
    Qt widgets must marshal to the GUI thread themselves (e.g. via
    QMetaObject.invokeMethod or a Qt signal).
    """

    def __init__(self) -> None:
        if not _MPV_AVAILABLE:
            raise PlayerError("python-mpv is not installed or libmpv is not found")

        # Qt (via X11/IBus/XIM) resets LC_NUMERIC to the system locale during
        # window initialisation. libmpv requires LC_NUMERIC=C to parse floats.
        # Set it immediately before creating the mpv context.
        locale.setlocale(locale.LC_NUMERIC, "C")

        self._mpv = _mpv.MPV(
            audio_display="no",
            vo="null",
            vid=False,
            terminal=False,
            input_default_bindings=False,
            input_vo_keyboard=False,
        )
        self._lock = threading.Lock()

        self._on_position: list[Callable[[float], None]] = []
        self._on_state_change: list[Callable[[str], None]] = []
        self._on_end_of_track: list[Callable[[], None]] = []
        self._on_duration: list[Callable[[float], None]] = []

        self._current_url: str = ""
        self._auth_token: str = ""
        self._duration: float = 0.0

        self._setup_observers()

    # ------------------------------------------------------------------
    # Callback registration
    # ------------------------------------------------------------------

    def on_position_changed(self, cb: Callable[[float], None]) -> None:
        self._on_position.append(cb)

    def on_state_changed(self, cb: Callable[[str], None]) -> None:
        self._on_state_change.append(cb)

    def on_end_of_track(self, cb: Callable[[], None]) -> None:
        self._on_end_of_track.append(cb)

    def on_duration_changed(self, cb: Callable[[float], None]) -> None:
        self._on_duration.append(cb)

    # ------------------------------------------------------------------
    # Internal observers
    # ------------------------------------------------------------------

    def _setup_observers(self) -> None:
        @self._mpv.property_observer("time-pos")
        def _pos_observer(_name: str, value: float | None) -> None:
            if value is not None:
                for cb in self._on_position:
                    cb(value)

        @self._mpv.property_observer("duration")
        def _dur_observer(_name: str, value: float | None) -> None:
            if value is not None:
                self._duration = value
                for cb in self._on_duration:
                    cb(value)

        @self._mpv.property_observer("pause")
        def _pause_observer(_name: str, value: bool | None) -> None:
            if value is None:
                return
            state = "paused" if value else "playing"
            for cb in self._on_state_change:
                cb(state)

        @self._mpv.event_callback("end-file")
        def _eof_handler(event) -> None:
            # `event` is an MpvEvent struct, not a dict — the end-file
            # payload (with its int `reason` code) lives at `event.data`.
            data = event.data
            if data is not None and data.reason == _mpv.MpvEventEndFile.EOF:
                for cb in self._on_end_of_track:
                    cb()

    # ------------------------------------------------------------------
    # Playback control
    # ------------------------------------------------------------------

    def play(self, url: str, start_time: float = 0.0, auth_token: str = "") -> None:
        with self._lock:
            self._current_url = url
            self._auth_token = auth_token
            if auth_token:
                self._mpv["http-header-fields"] = [f"Authorization: Bearer {auth_token}"]
            self._mpv.play(url)
            # Unpause BEFORE waiting for playback to start. mpv's loadfile
            # doesn't reset the pause property, so if a previous track was
            # paused, the new file loads but stays paused — and
            # wait_until_playing() below waits for core-idle to clear,
            # which never happens while paused, hanging forever.
            self._mpv.pause = False
            if start_time > 0:
                # Wait briefly for mpv to start before seeking. Bounded so a
                # stall here can't freeze the whole GUI thread.
                try:
                    self._mpv.wait_until_playing(timeout=10)
                except TimeoutError:
                    pass
                self._mpv.seek(start_time, reference="absolute")

    def pause(self) -> None:
        self._mpv.pause = True

    def resume(self) -> None:
        self._mpv.pause = False

    def toggle_pause(self) -> None:
        self._mpv.pause = not self._mpv.pause

    def stop(self) -> None:
        self._mpv.stop()
        self._current_url = ""

    def seek_relative(self, seconds: float) -> None:
        self._mpv.seek(seconds, reference="relative")

    def seek_absolute(self, seconds: float) -> None:
        self._mpv.seek(seconds, reference="absolute")

    def seek_forward(self) -> None:
        self.seek_relative(SEEK_SHORT)

    def seek_back(self) -> None:
        self.seek_relative(-SEEK_SHORT)

    def seek_forward_long(self) -> None:
        self.seek_relative(SEEK_LONG)

    def seek_back_long(self) -> None:
        self.seek_relative(-SEEK_LONG)

    # ------------------------------------------------------------------
    # Chapter navigation
    # ------------------------------------------------------------------

    @property
    def chapter_count(self) -> int:
        count = self._mpv.chapter_list
        return len(count) if count else 0

    @property
    def current_chapter(self) -> int:
        chapter = self._mpv.chapter
        return int(chapter) if chapter is not None else 0

    def next_chapter(self) -> None:
        chapter = self.current_chapter
        if chapter < self.chapter_count - 1:
            self._mpv.chapter = chapter + 1

    def prev_chapter(self) -> None:
        chapter = self.current_chapter
        if chapter > 0:
            self._mpv.chapter = chapter - 1

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    @property
    def is_playing(self) -> bool:
        try:
            return not bool(self._mpv.pause) and self._current_url != ""
        except Exception:
            return False

    @property
    def is_paused(self) -> bool:
        try:
            return bool(self._mpv.pause) and self._current_url != ""
        except Exception:
            return False

    @property
    def position(self) -> float:
        try:
            value = self._mpv.time_pos
            return float(value) if value is not None else 0.0
        except Exception:
            return 0.0

    @property
    def duration(self) -> float:
        try:
            value = self._mpv.duration
            return float(value) if value is not None else self._duration
        except Exception:
            return self._duration

    @property
    def current_url(self) -> str:
        return self._current_url

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        self._mpv.terminate()
