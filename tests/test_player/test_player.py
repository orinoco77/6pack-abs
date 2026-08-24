"""Tests for AudioPlayer using a mock mpv."""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

# ---- Mock mpv module ----

class _MockEndFileData:
    """Mirrors mpv.MpvEventEndFile's shape: a `.reason` int code."""

    def __init__(self, reason: int) -> None:
        self.reason = reason


class _MockEvent:
    """Mirrors mpv.MpvEvent's shape: event.data holds the typed payload,
    not a dict — see the real MpvEvent.data property in python-mpv."""

    def __init__(self, data) -> None:
        self.data = data


class MockMPV:
    """Minimal mock of the mpv.MPV class."""

    def __init__(self, **kwargs):
        self.pause = False
        self.time_pos = 0.0
        self.duration = 0.0
        self.chapter = 0
        self.chapter_list = []
        self.speed = 1.0
        self._http_header_fields = []
        self._played_url = None
        self._property_observers: dict = {}
        self._event_callbacks: dict = {}
        self._terminated = False

    def __setitem__(self, key, value):
        if key == "http-header-fields":
            self._http_header_fields = value

    def play(self, url):
        self._played_url = url

    def stop(self):
        self._played_url = None

    def seek(self, amount, reference="relative"):
        if reference == "relative":
            self.time_pos = (self.time_pos or 0) + amount
        else:
            self.time_pos = amount

    def wait_until_playing(self, timeout=None):
        pass

    def terminate(self):
        self._terminated = True

    def property_observer(self, prop):
        def decorator(fn):
            self._property_observers[prop] = fn
            return fn
        return decorator

    def event_callback(self, event):
        def decorator(fn):
            self._event_callbacks[event] = fn
            return fn
        return decorator

    def _fire_property(self, prop, value):
        if prop in self._property_observers:
            self._property_observers[prop](prop, value)

    def _fire_event(self, event, data=None):
        if event in self._event_callbacks:
            self._event_callbacks[event](_MockEvent(data))


_mock_mpv_module = MagicMock()
_mock_mpv_instance = None


def _make_mock_mpv(**kwargs):
    global _mock_mpv_instance
    _mock_mpv_instance = MockMPV(**kwargs)
    return _mock_mpv_instance


@pytest.fixture(autouse=True)
def patch_mpv():
    """Replace the mpv module with our mock before each test."""
    mock_module = MagicMock()
    mock_module.MPV.side_effect = _make_mock_mpv
    # Real reason codes from mpv.MpvEventEndFile — player.py compares
    # event.data.reason against these, not against a string.
    mock_module.MpvEventEndFile.EOF = 0
    mock_module.MpvEventEndFile.RESTARTED = 1
    mock_module.MpvEventEndFile.ABORTED = 2
    mock_module.MpvEventEndFile.QUIT = 3
    mock_module.MpvEventEndFile.ERROR = 4
    mock_module.MpvEventEndFile.REDIRECT = 5
    with patch.dict("sys.modules", {"mpv": mock_module}):
        # Re-import player to pick up patched mpv
        if "sixpack.player.player" in sys.modules:
            del sys.modules["sixpack.player.player"]
        yield mock_module
    if "sixpack.player.player" in sys.modules:
        del sys.modules["sixpack.player.player"]


@pytest.fixture
def player(patch_mpv):
    from sixpack.player.player import AudioPlayer
    p = AudioPlayer()
    return p


# ---- Construction ----

def test_player_creates_mpv(patch_mpv, player):
    patch_mpv.MPV.assert_called_once()


def test_player_initial_state(player):
    assert not player.is_playing
    assert not player.is_paused
    assert player.position == 0.0
    assert player.current_url == ""


# ---- Playback ----

def test_play_sets_url(player):
    player.play("http://abs.test/file.mp3")
    assert player.current_url == "http://abs.test/file.mp3"
    assert _mock_mpv_instance._played_url == "http://abs.test/file.mp3"


def test_play_with_auth_token(player):
    player.play("http://abs.test/file.mp3", auth_token="mytoken")
    assert "Authorization: Bearer mytoken" in _mock_mpv_instance._http_header_fields


def test_play_with_start_time(player):
    player.play("http://abs.test/file.mp3", start_time=300.0)
    assert _mock_mpv_instance.time_pos == 300.0


def test_play_no_start_time_no_seek(player):
    player.play("http://abs.test/file.mp3", start_time=0.0)
    assert _mock_mpv_instance.time_pos == 0.0


def test_play_unpauses_before_waiting_to_avoid_hang(player):
    """Regression: mpv's loadfile() (called by play()) doesn't reset the
    pause property. If a previous track was left paused, wait_until_playing()
    blocks until core-idle clears, which never happens while paused — so
    pause must be cleared BEFORE that wait, not after."""
    _mock_mpv_instance.pause = True  # simulate: previous track was paused

    pause_state_when_waited = []
    original_wait = _mock_mpv_instance.wait_until_playing

    def spy_wait(*args, **kwargs):
        pause_state_when_waited.append(_mock_mpv_instance.pause)
        return original_wait(*args, **kwargs)

    _mock_mpv_instance.wait_until_playing = spy_wait

    player.play("http://abs.test/file2.mp3", start_time=100.0)

    assert pause_state_when_waited == [False]


def test_play_wait_until_playing_timeout_does_not_raise(player):
    """A stall in mpv starting playback must not crash/hang the caller."""
    def raise_timeout(*args, **kwargs):
        raise TimeoutError("mpv never left core-idle")

    _mock_mpv_instance.wait_until_playing = raise_timeout

    player.play("http://abs.test/file.mp3", start_time=100.0)  # must not raise
    assert _mock_mpv_instance.time_pos == 100.0  # seek still attempted


def test_pause(player):
    player.play("http://abs.test/file.mp3")
    _mock_mpv_instance.pause = False
    player.pause()
    assert _mock_mpv_instance.pause is True


def test_resume(player):
    player.play("http://abs.test/file.mp3")
    _mock_mpv_instance.pause = True
    player.resume()
    assert _mock_mpv_instance.pause is False


def test_toggle_pause_from_playing(player):
    player.play("http://abs.test/file.mp3")
    _mock_mpv_instance.pause = False
    player.toggle_pause()
    assert _mock_mpv_instance.pause is True


def test_toggle_pause_from_paused(player):
    player.play("http://abs.test/file.mp3")
    _mock_mpv_instance.pause = True
    player.toggle_pause()
    assert _mock_mpv_instance.pause is False


def test_stop_clears_url(player):
    player.play("http://abs.test/file.mp3")
    player.stop()
    assert player.current_url == ""


# ---- Seeking ----

def test_seek_relative(player):
    player.play("http://abs.test/f.mp3")
    _mock_mpv_instance.time_pos = 100.0
    player.seek_relative(30.0)
    assert _mock_mpv_instance.time_pos == 130.0


def test_seek_absolute(player):
    player.play("http://abs.test/f.mp3")
    player.seek_absolute(600.0)
    assert _mock_mpv_instance.time_pos == 600.0


def test_seek_forward(player):
    player.play("http://abs.test/f.mp3")
    _mock_mpv_instance.time_pos = 100.0
    player.seek_forward()
    assert _mock_mpv_instance.time_pos == 130.0


def test_seek_back(player):
    player.play("http://abs.test/f.mp3")
    _mock_mpv_instance.time_pos = 100.0
    player.seek_back()
    assert _mock_mpv_instance.time_pos == 70.0


# ---- Chapters ----

def test_chapter_count_no_chapters(player):
    _mock_mpv_instance.chapter_list = []
    assert player.chapter_count == 0


def test_chapter_count(player):
    _mock_mpv_instance.chapter_list = [{"title": "Ch1"}, {"title": "Ch2"}]
    assert player.chapter_count == 2


def test_next_chapter(player):
    _mock_mpv_instance.chapter_list = [{"title": "Ch1"}, {"title": "Ch2"}, {"title": "Ch3"}]
    _mock_mpv_instance.chapter = 0
    player.next_chapter()
    assert _mock_mpv_instance.chapter == 1


def test_next_chapter_at_last(player):
    _mock_mpv_instance.chapter_list = [{"title": "Ch1"}]
    _mock_mpv_instance.chapter = 0
    player.next_chapter()
    assert _mock_mpv_instance.chapter == 0  # no change


def test_prev_chapter(player):
    _mock_mpv_instance.chapter_list = [{"title": "Ch1"}, {"title": "Ch2"}]
    _mock_mpv_instance.chapter = 1
    player.prev_chapter()
    assert _mock_mpv_instance.chapter == 0


def test_prev_chapter_at_first(player):
    _mock_mpv_instance.chapter_list = [{"title": "Ch1"}]
    _mock_mpv_instance.chapter = 0
    player.prev_chapter()
    assert _mock_mpv_instance.chapter == 0


def test_set_speed(player):
    player.set_speed(1.5)
    assert _mock_mpv_instance.speed == 1.5


def test_seek_to_chapter_in_range(player):
    _mock_mpv_instance.chapter_list = [{"title": "Ch1"}, {"title": "Ch2"}, {"title": "Ch3"}]
    player.seek_to_chapter(2)
    assert _mock_mpv_instance.chapter == 2


def test_seek_to_chapter_out_of_range_is_noop(player):
    _mock_mpv_instance.chapter_list = [{"title": "Ch1"}, {"title": "Ch2"}]
    _mock_mpv_instance.chapter = 0
    player.seek_to_chapter(5)
    assert _mock_mpv_instance.chapter == 0


def test_seek_to_chapter_negative_is_noop(player):
    _mock_mpv_instance.chapter_list = [{"title": "Ch1"}]
    _mock_mpv_instance.chapter = 0
    player.seek_to_chapter(-1)
    assert _mock_mpv_instance.chapter == 0


# ---- State queries ----

def test_is_playing(player):
    player.play("http://x.com/f.mp3")
    _mock_mpv_instance.pause = False
    assert player.is_playing is True


def test_is_not_playing_when_paused(player):
    player.play("http://x.com/f.mp3")
    _mock_mpv_instance.pause = True
    assert player.is_playing is False


def test_is_paused(player):
    player.play("http://x.com/f.mp3")
    _mock_mpv_instance.pause = True
    assert player.is_paused is True


def test_position(player):
    _mock_mpv_instance.time_pos = 42.5
    assert player.position == 42.5


def test_position_none(player):
    _mock_mpv_instance.time_pos = None
    assert player.position == 0.0


def test_duration(player):
    _mock_mpv_instance.duration = 3600.0
    assert player.duration == 3600.0


def test_duration_none(player):
    _mock_mpv_instance.duration = None
    player._duration = 1234.0
    assert player.duration == 1234.0


# ---- Callbacks ----

def test_position_callback(player):
    received = []
    player.on_position_changed(received.append)
    _mock_mpv_instance._fire_property("time-pos", 55.0)
    assert received == [55.0]


def test_duration_callback(player):
    received = []
    player.on_duration_changed(received.append)
    _mock_mpv_instance._fire_property("duration", 3600.0)
    assert received == [3600.0]


def test_state_callback_pause(player):
    received = []
    player.on_state_changed(received.append)
    _mock_mpv_instance._fire_property("pause", True)
    assert received == ["paused"]


def test_state_callback_resume(player):
    received = []
    player.on_state_changed(received.append)
    _mock_mpv_instance._fire_property("pause", False)
    assert received == ["playing"]


def test_eof_callback(player):
    received = []
    player.on_end_of_track(lambda: received.append(True))
    _mock_mpv_instance._fire_event("end-file", _MockEndFileData(reason=0))  # EOF
    assert received == [True]


def test_eof_callback_not_fired_for_stop(player):
    received = []
    player.on_end_of_track(lambda: received.append(True))
    _mock_mpv_instance._fire_event("end-file", _MockEndFileData(reason=3))  # QUIT
    assert received == []


def test_position_callback_none_ignored(player):
    received = []
    player.on_position_changed(received.append)
    _mock_mpv_instance._fire_property("time-pos", None)
    assert received == []


# ---- Shutdown ----

def test_shutdown(player):
    player.shutdown()
    assert _mock_mpv_instance._terminated is True


# ---- Import failure ----

def test_player_error_on_missing_mpv():
    import importlib
    with patch.dict("sys.modules", {"mpv": None}):
        if "sixpack.player.player" in sys.modules:
            del sys.modules["sixpack.player.player"]
        mod = importlib.import_module("sixpack.player.player")
        assert mod._MPV_AVAILABLE is False
        with pytest.raises(mod.PlayerError):
            mod.AudioPlayer()
    if "sixpack.player.player" in sys.modules:
        del sys.modules["sixpack.player.player"]
