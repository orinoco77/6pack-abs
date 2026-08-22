"""Tests for PlayerScreen's up-next display and track_ended signal."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import Qt

from sixpack.player.player import AudioPlayer
from sixpack.ui.screens.player import PlayerScreen


class _FakePlayer:
    """Stands in for AudioPlayer — PlayerScreen only needs on_*/toggle_pause/
    seek_*/stop/set_speed/seek_to_chapter/chapter_count/current_chapter on it,
    matching AudioPlayer's real interface without constructing real mpv."""

    def __init__(self):
        self.speed_calls = []
        self.seek_to_chapter_calls = []
        self.chapter_count = 0
        self.current_chapter = 0

    def on_position_changed(self, cb): pass
    def on_state_changed(self, cb): pass
    def on_end_of_track(self, cb): pass
    def on_duration_changed(self, cb): pass
    def toggle_pause(self): pass
    def stop(self): pass
    def seek_forward(self): pass
    def seek_back(self): pass
    def seek_forward_long(self): pass
    def seek_back_long(self): pass
    def next_chapter(self): pass
    def prev_chapter(self): pass
    def set_speed(self, speed): self.speed_calls.append(speed)
    def seek_to_chapter(self, index): self.seek_to_chapter_calls.append(index)


@pytest.fixture
def screen(qtbot):
    s = PlayerScreen(player=_FakePlayer())
    qtbot.addWidget(s)
    s.show()
    return s


def test_show_up_next_sets_visible_text(screen):
    screen.show_up_next("Up next: Episode 2")
    assert screen._up_next_label.isVisible()
    assert screen._up_next_label.text() == "Up next: Episode 2"


def test_hide_up_next_clears_visibility(screen):
    screen.show_up_next("Up next: Episode 2")
    screen.hide_up_next()
    assert not screen._up_next_label.isVisible()


def test_up_next_label_hidden_initially(screen):
    assert not screen._up_next_label.isVisible()


def test_track_ended_emitted_not_next_item(qtbot, screen):
    """Regression: the automatic end-of-track path must use the new
    track_ended signal, NOT the existing next_item signal — next_item is
    reserved for the manual skip-forward remote button/key, which must keep
    auto-playing immediately (see this plan's Global Constraints)."""
    next_item_calls = []
    track_ended_calls = []
    screen.next_item.connect(lambda: next_item_calls.append(True))
    screen.track_ended.connect(lambda: track_ended_calls.append(True))

    screen._handle_end_of_track()

    assert track_ended_calls == [True]
    assert next_item_calls == []
