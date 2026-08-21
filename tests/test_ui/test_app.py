"""Smoke tests for the top-level application window (headless)."""
from __future__ import annotations


class _FakeAudioPlayer:
    """Minimal stand-in for sixpack.player.player.AudioPlayer.

    MainWindow's real AudioPlayer wraps python-mpv, which spawns a genuine
    libmpv event thread. Constructing that for real in a test process leaves
    background threads running past test teardown and reliably aborts the
    interpreter on shutdown (observed: "Fatal Python error: Aborted" inside
    mpv's `_event_generator`). This double satisfies the same interface
    MainWindow/PlayerScreen touch during construction, so the full screen
    stack (including PlayerScreen and its signal wiring) still gets built
    and connected, without touching real mpv/libmpv.
    """

    def on_position_changed(self, cb):
        pass

    def on_state_changed(self, cb):
        pass

    def on_end_of_track(self, cb):
        pass

    def on_duration_changed(self, cb):
        pass

    def seek_back(self):
        pass

    def seek_forward(self):
        pass

    def seek_back_long(self):
        pass

    def seek_forward_long(self):
        pass

    def toggle_pause(self):
        pass

    def stop(self):
        pass

    def next_chapter(self):
        pass

    def prev_chapter(self):
        pass

    def play(self, url, start_time=0.0, auth_token=""):
        pass

    def shutdown(self):
        pass


def test_main_window_constructs_without_error(qtbot, monkeypatch):
    """MainWindow must build its full screen stack and signal wiring without
    raising. This guards against dangling signal connections (e.g. to a
    signal removed from a screen but left wired in app.py) that no
    screen-level unit test can catch, since MainWindow is only ever
    constructed by the real app entry point.
    """
    from sixpack.config import AppConfig
    from sixpack.ui import app as app_module

    # Avoid constructing a real python-mpv/libmpv backend in the test
    # process (see _FakeAudioPlayer docstring).
    monkeypatch.setattr(app_module, "AudioPlayer", _FakeAudioPlayer)

    window = app_module.MainWindow(AppConfig())
    qtbot.addWidget(window)

    assert window is not None
    assert window._player_screen is not None

    # MainWindow.closeEvent() stops the AsyncWorker's background QThread;
    # without this the thread survives past the test, which reliably
    # aborts the interpreter at process exit.
    window.close()
