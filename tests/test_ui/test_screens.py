"""UI screen tests using pytest-qt (headless)."""
from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from sixpack.api.models import (
    Chapter,
    LibraryItemMedia,
    MediaProgress,
    Series,
    SeriesBook,
)
from sixpack.ui.screens.login import LoginScreen
from sixpack.ui.screens.series_detail import SeriesDetailScreen


# ---- SplashScreen ----

def test_splash_screen_creates(qtbot):
    from sixpack.ui.screens.splash import SplashScreen
    from PyQt6.QtWidgets import QLabel
    screen = SplashScreen()
    qtbot.addWidget(screen)
    labels = screen.findChildren(QLabel)
    assert any("SixPack" in lbl.text() for lbl in labels)


def test_splash_screen_set_status(qtbot):
    from sixpack.ui.screens.splash import SplashScreen
    screen = SplashScreen()
    qtbot.addWidget(screen)
    screen.set_status("Checking saved session…")
    assert screen._status_label.text() == "Checking saved session…"


def test_splash_screen_default_status(qtbot):
    from sixpack.ui.screens.splash import SplashScreen
    screen = SplashScreen()
    qtbot.addWidget(screen)
    assert screen._status_label.text() == "Connecting…"


# ---- LoginScreen ----

def test_login_screen_creates(qtbot):
    screen = LoginScreen()
    qtbot.addWidget(screen)
    assert screen._url_input is not None
    assert screen._user_input is not None
    assert screen._pass_input is not None


def test_login_screen_error_hidden_initially(qtbot):
    screen = LoginScreen()
    qtbot.addWidget(screen)
    # isHidden() checks the widget's own state regardless of parent visibility
    assert screen._error_label.isHidden()


def test_login_screen_show_error(qtbot):
    screen = LoginScreen()
    qtbot.addWidget(screen)
    screen.show_error("Bad credentials")
    assert not screen._error_label.isHidden()
    assert "Bad credentials" in screen._error_label.text()


def test_login_screen_set_prefill(qtbot):
    screen = LoginScreen()
    qtbot.addWidget(screen)
    screen.set_prefill("http://abs.local:13378", "adam")
    assert screen._url_input.text() == "http://abs.local:13378"
    assert screen._user_input.text() == "adam"


def test_login_emits_signal_on_connect(qtbot):
    screen = LoginScreen()
    qtbot.addWidget(screen)
    screen._url_input.setText("http://abs.local:13378")
    screen._user_input.setText("adam")
    screen._pass_input.setText("secret")

    with qtbot.waitSignal(screen.login_requested, timeout=1000) as blocker:
        screen._login_btn.click()

    url, username, password = blocker.args
    assert url == "http://abs.local:13378"
    assert username == "adam"
    assert password == "secret"


def test_login_no_emit_without_url(qtbot):
    screen = LoginScreen()
    qtbot.addWidget(screen)
    screen._url_input.setText("")
    screen._user_input.setText("adam")

    with qtbot.assertNotEmitted(screen.login_requested):
        screen._login_btn.click()
    assert not screen._error_label.isHidden()


def test_login_no_emit_without_username(qtbot):
    screen = LoginScreen()
    qtbot.addWidget(screen)
    screen._url_input.setText("http://abs.local")
    screen._user_input.setText("")

    with qtbot.assertNotEmitted(screen.login_requested):
        screen._login_btn.click()


def test_login_button_disabled_during_connect(qtbot):
    screen = LoginScreen()
    qtbot.addWidget(screen)
    screen._url_input.setText("http://abs.local")
    screen._user_input.setText("adam")
    screen._pass_input.setText("pass")

    emitted = []
    screen.login_requested.connect(lambda *a: emitted.append(a))
    screen._login_btn.click()
    # After emitting, button should be disabled
    assert not screen._login_btn.isEnabled()
    # Reset state
    screen.show_error("failed")
    assert screen._login_btn.isEnabled()


# ---- SeriesDetailScreen ----

def _make_series() -> Series:
    media1 = LibraryItemMedia(metadata={"title": "Episode 1"}, duration=1800.0)
    media2 = LibraryItemMedia(metadata={"title": "Episode 2"}, duration=3600.0)
    b1 = SeriesBook(id="b1", libraryId="lib1", media=media1, sequence="1")
    b2 = SeriesBook(id="b2", libraryId="lib1", media=media2, sequence="2")
    return Series(id="s1", name="My Drama Series", books=[b1, b2])


def test_detail_screen_creates(qtbot):
    screen = SeriesDetailScreen()
    qtbot.addWidget(screen)
    assert screen._grid is not None


def test_detail_screen_load(qtbot):
    screen = SeriesDetailScreen()
    qtbot.addWidget(screen)
    series = _make_series()
    screen.load(series, {}, "http://localhost", "tok")
    assert screen._hero_backdrop._hero_title.text() == "My Drama Series"
    assert screen._grid.item_count == 2


def test_detail_screen_back_signal(qtbot):
    from sixpack.input.keyboard import key_to_action  # noqa: F401 — confirm import path used by screen
    screen = SeriesDetailScreen()
    qtbot.addWidget(screen)
    screen.load(_make_series(), {}, "http://localhost", "tok")
    screen.show()
    with qtbot.waitSignal(screen.back_requested, timeout=1000):
        qtbot.keyClick(screen, Qt.Key.Key_Backspace)


def test_detail_screen_item_emits_episode_activated(qtbot):
    screen = SeriesDetailScreen()
    qtbot.addWidget(screen)
    series = _make_series()
    screen.load(series, {}, "http://localhost", "tok")
    with qtbot.waitSignal(screen.episode_activated, timeout=1000) as blocker:
        screen._grid.item_activated.emit(0)
    assert blocker.args[0].id == "b1"


def test_detail_show_loading_renders_episodes(qtbot):
    screen = SeriesDetailScreen()
    qtbot.addWidget(screen)
    screen.show_loading(_make_series(), "http://localhost", "tok")
    assert screen._grid.item_count == 2


def test_detail_update_progress_refreshes_in_place(qtbot):
    screen = SeriesDetailScreen()
    qtbot.addWidget(screen)
    series = _make_series()
    screen.load(series, {}, "http://localhost", "tok")
    card_before = screen._grid._items[0]
    screen.update_progress({"b1": MediaProgress(currentTime=1800.0, duration=1800.0, isFinished=True)})
    assert screen._grid._items[0] is card_before


def test_detail_resume_index_all_finished(qtbot):
    screen = SeriesDetailScreen()
    qtbot.addWidget(screen)
    series = _make_series()
    progress = {
        "b1": MediaProgress(currentTime=1800.0, duration=1800.0, isFinished=True),
        "b2": MediaProgress(currentTime=3600.0, duration=3600.0, isFinished=True),
    }
    screen.load(series, progress, "http://localhost", "tok")
    assert screen._grid._focused_index == 0  # _find_resume_index falls back to 0


def test_detail_screen_focus_item_by_key(qtbot):
    screen = SeriesDetailScreen()
    qtbot.addWidget(screen)
    screen.load(_make_series(), {}, "http://localhost", "tok")
    screen.focus_item_by_key("b2")
    assert screen._grid._focused_index == 1


def test_detail_screen_hero_subtitle_includes_episode_title(qtbot):
    screen = SeriesDetailScreen()
    qtbot.addWidget(screen)
    series = _make_series()
    screen.load(series, {}, "http://localhost", "tok")
    sub = screen._hero_backdrop._hero_sub.text()
    assert "1" in sub
    assert "Episode 1" in sub


# ---- ChapterSelectScreen ----

def _make_chapters():
    return [
        Chapter(id=0, start=0.0, end=1500.0, title="Part One: The Arrival"),
        Chapter(id=1, start=1500.0, end=3000.0, title="Part Two: The Attack"),
        Chapter(id=2, start=3000.0, end=4200.0, title="Part Three: Aftermath"),
    ]


def _make_box_set_book():
    from sixpack.api.models import Chapter
    media = LibraryItemMedia(
        metadata={"title": "Invasion of Earth"},
        duration=4200.0,
        chapters=_make_chapters(),
    )
    return SeriesBook(id="bx1", libraryId="lib1", media=media, sequence="1")


def test_chapter_screen_creates(qtbot):
    from sixpack.ui.screens.chapter_select import ChapterSelectScreen
    screen = ChapterSelectScreen()
    qtbot.addWidget(screen)
    assert screen._list is not None


def test_chapter_screen_load(qtbot):
    from sixpack.ui.screens.chapter_select import ChapterSelectScreen
    screen = ChapterSelectScreen()
    qtbot.addWidget(screen)
    book = _make_box_set_book()
    screen.load(book, _make_chapters(), None)
    assert screen._list.count() == 3
    assert screen._hero_backdrop._hero_title.text() == "Invasion of Earth"
    assert "3 chapters" in screen._hero_backdrop._hero_sub.text()


def test_chapter_screen_hero_shows_book_title(qtbot):
    from sixpack.ui.screens.chapter_select import ChapterSelectScreen
    screen = ChapterSelectScreen()
    qtbot.addWidget(screen)
    book = _make_box_set_book()
    screen.load(book, _make_chapters(), None, "http://localhost", "tok")
    assert screen._hero_backdrop._hero_title.text() == book.title


def test_chapter_screen_play_signal(qtbot):
    from sixpack.ui.screens.chapter_select import ChapterSelectScreen
    screen = ChapterSelectScreen()
    qtbot.addWidget(screen)
    book = _make_box_set_book()
    screen.load(book, _make_chapters(), None)

    signals = []
    screen.play_requested.connect(lambda b, t: signals.append((b, t)))
    screen._list.itemActivated.emit(screen._list.item(1))  # Part Two starts at 1500.0

    assert len(signals) == 1
    assert signals[0][0] is book
    assert signals[0][1] == 1500.0


def test_chapter_screen_back_signal(qtbot):
    from sixpack.ui.screens.chapter_select import ChapterSelectScreen
    screen = ChapterSelectScreen()
    qtbot.addWidget(screen)
    screen.load(_make_box_set_book(), _make_chapters(), None)

    with qtbot.waitSignal(screen.back_requested, timeout=1000):
        qtbot.keyClick(screen, Qt.Key.Key_Escape)


def test_chapter_screen_resume_index_in_progress(qtbot):
    """Resume index points to the chapter containing current_time."""
    from sixpack.ui.screens.chapter_select import ChapterSelectScreen
    screen = ChapterSelectScreen()
    qtbot.addWidget(screen)
    book = _make_box_set_book()
    # current_time = 2000s → inside Part Two (1500–3000)
    prog = MediaProgress(libraryItemId="bx1", currentTime=2000.0, duration=4200.0)
    screen.load(book, _make_chapters(), prog)
    assert screen._list.currentRow() == 1


def test_chapter_screen_resume_index_finished(qtbot):
    """Finished book restarts from chapter 0."""
    from sixpack.ui.screens.chapter_select import ChapterSelectScreen
    screen = ChapterSelectScreen()
    qtbot.addWidget(screen)
    book = _make_box_set_book()
    prog = MediaProgress(libraryItemId="bx1", currentTime=4200.0, duration=4200.0, isFinished=True)
    screen.load(book, _make_chapters(), prog)
    assert screen._list.currentRow() == 0


def test_chapter_status_finished_book(qtbot):
    """All chapters show as finished when the book is finished."""
    from sixpack.ui.screens.chapter_select import ChapterSelectScreen, _chapter_status
    from sixpack.api.models import Chapter
    ch = Chapter(id=0, start=0.0, end=1500.0, title="Part One")
    assert _chapter_status(ch, 4200.0, is_finished=True) == "finished"
    assert _chapter_status(ch, 0.0, is_finished=True) == "finished"


def test_chapter_status_in_progress():
    from sixpack.ui.screens.chapter_select import _chapter_status
    from sixpack.api.models import Chapter
    ch = Chapter(id=1, start=1500.0, end=3000.0, title="Part Two")
    assert _chapter_status(ch, 2000.0, is_finished=False) == "in_progress"
    assert _chapter_status(ch, 3001.0, is_finished=False) == "finished"
    assert _chapter_status(ch, 1000.0, is_finished=False) == "unstarted"


def test_chapter_screen_load_from_library_item(qtbot):
    from sixpack.ui.screens.chapter_select import ChapterSelectScreen
    from sixpack.api.models import LibraryItem, LibraryItemMedia

    screen = ChapterSelectScreen()
    qtbot.addWidget(screen)
    li = LibraryItem(
        id="li1", libraryId="lib1", mediaType="book",
        media=LibraryItemMedia(
            metadata={"title": "Doctor Who: Invasion", "authorName": "BBC"},
            duration=4200.0, chapters=_make_chapters(),
        ),
    )
    screen.load_from_library_item(li, _make_chapters(), None)
    assert screen._list.count() == 3
    assert screen._hero_backdrop._hero_title.text() == "Doctor Who: Invasion"
    assert "3 chapters" in screen._hero_backdrop._hero_sub.text()
    assert screen._library_item is li
    assert screen._book is None
    assert screen._playlist_item is None


def test_chapter_screen_library_item_play_signal(qtbot):
    from sixpack.ui.screens.chapter_select import ChapterSelectScreen
    from sixpack.api.models import LibraryItem, LibraryItemMedia

    screen = ChapterSelectScreen()
    qtbot.addWidget(screen)
    li = LibraryItem(
        id="li1", libraryId="lib1", mediaType="book",
        media=LibraryItemMedia(metadata={"title": "Book A"}, duration=3000.0),
    )
    screen.load_from_library_item(li, _make_chapters(), None)

    play_signals, lib_signals = [], []
    screen.play_requested.connect(lambda b, t: play_signals.append((b, t)))
    screen.library_item_play_requested.connect(lambda item, t: lib_signals.append((item, t)))
    screen._list.itemActivated.emit(screen._list.item(0))

    assert len(play_signals) == 0
    assert len(lib_signals) == 1
    assert lib_signals[0][0] is li
    assert lib_signals[0][1] == 0.0


def test_chapter_screen_load_clears_library_item(qtbot):
    from sixpack.ui.screens.chapter_select import ChapterSelectScreen
    from sixpack.api.models import LibraryItem, LibraryItemMedia

    screen = ChapterSelectScreen()
    qtbot.addWidget(screen)
    li = LibraryItem(
        id="li1", libraryId="lib1", mediaType="book",
        media=LibraryItemMedia(metadata={"title": "Book"}, duration=1000.0),
    )
    screen.load_from_library_item(li, _make_chapters(), None)
    assert screen._library_item is li

    screen.load(_make_box_set_book(), _make_chapters(), None)
    assert screen._library_item is None


def test_chapter_screen_load_from_library_item_resume(qtbot):
    from sixpack.ui.screens.chapter_select import ChapterSelectScreen
    from sixpack.api.models import LibraryItem, LibraryItemMedia, MediaProgress

    screen = ChapterSelectScreen()
    qtbot.addWidget(screen)
    li = LibraryItem(
        id="li1", libraryId="lib1", mediaType="book",
        media=LibraryItemMedia(metadata={"title": "Book"}, duration=4200.0),
    )
    prog = MediaProgress(libraryItemId="li1", currentTime=2000.0, duration=4200.0)
    screen.load_from_library_item(li, _make_chapters(), prog)
    assert screen._list.currentRow() == 1  # chapter at 1500–3000


class _FakeCoverCache:
    """Captures fetch/fetch_backdrop calls instead of invoking them, so the
    test can assert exactly how many times each was invoked without a real
    network-backed CoverCache. Same pattern as
    tests/test_ui/test_browse_screen.py's _FakeCoverCache (~line 893).
    """

    def __init__(self):
        self.fetch_calls = []
        self.fetch_backdrop_calls = []

    def fetch(self, url, token, callback):
        self.fetch_calls.append((url, token, callback))

    def fetch_backdrop(self, url, token, callback):
        self.fetch_backdrop_calls.append((url, token, callback))


def test_chapter_screen_backdrop_fetched_once_not_per_focus_change(qtbot):
    """ChapterSelectScreen fetches the book's backdrop cover exactly ONCE
    per load() call and does NOT re-fetch it as focus moves between chapter
    rows — all chapters share the same book cover, so per-row re-fetching
    would be pure waste (see chapter_select.py's module docstring and
    _load_backdrop). This exercises the real production codepath: app.py
    always constructs ChapterSelectScreen with a real CoverCache, and this
    behavior was previously only checked via throwaway scripts outside the
    test suite.
    """
    from sixpack.ui.screens.chapter_select import ChapterSelectScreen

    fake_cache = _FakeCoverCache()
    screen = ChapterSelectScreen(cover_cache=fake_cache)
    qtbot.addWidget(screen)
    book = _make_box_set_book()
    screen.load(book, _make_chapters(), None, "http://localhost", "tok")

    assert len(fake_cache.fetch_backdrop_calls) == 1

    # Simulate focus moving across every chapter row.
    for row in range(screen._list.count()):
        screen._list.setCurrentRow(row)

    assert len(fake_cache.fetch_backdrop_calls) == 1


# ---- Config ----

def test_config_save_load(tmp_path, monkeypatch):
    from sixpack.config import AppConfig, ServerConfig, CONFIG_FILE, CONFIG_DIR
    monkeypatch.setattr("sixpack.config.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("sixpack.config.CONFIG_FILE", tmp_path / "config.json")

    cfg = AppConfig()
    cfg.add_or_update_server(ServerConfig(name="Home", url="http://abs.local", token="tok1"))
    cfg.save()

    loaded = AppConfig.load()
    assert len(loaded.servers) == 1
    assert loaded.servers[0].url == "http://abs.local"
    assert loaded.servers[0].token == "tok1"
    assert loaded.active_server_index == 0


def test_config_active_server_none():
    from sixpack.config import AppConfig
    cfg = AppConfig()
    assert cfg.active_server is None


def test_config_update_existing_server(tmp_path, monkeypatch):
    monkeypatch.setattr("sixpack.config.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("sixpack.config.CONFIG_FILE", tmp_path / "config.json")

    from sixpack.config import AppConfig, ServerConfig
    cfg = AppConfig()
    cfg.add_or_update_server(ServerConfig(name="Home", url="http://abs.local", token="old"))
    cfg.add_or_update_server(ServerConfig(name="Home", url="http://abs.local", token="new"))
    assert len(cfg.servers) == 1
    assert cfg.servers[0].token == "new"


def test_config_load_corrupt_file(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text("not json{{{{")
    monkeypatch.setattr("sixpack.config.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("sixpack.config.CONFIG_FILE", cfg_file)

    from sixpack.config import AppConfig
    cfg = AppConfig.load()
    assert cfg.servers == []


def test_config_active_server_index_clamp():
    from sixpack.config import AppConfig, ServerConfig
    cfg = AppConfig(
        servers=[ServerConfig(name="A", url="http://a")],
        active_server_index=999,
    )
    assert cfg.active_server is not None
    assert cfg.active_server.url == "http://a"


def test_config_last_library_id_persists(tmp_path, monkeypatch):
    monkeypatch.setattr("sixpack.config.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("sixpack.config.CONFIG_FILE", tmp_path / "config.json")

    from sixpack.config import AppConfig, ServerConfig
    cfg = AppConfig()
    cfg.add_or_update_server(
        ServerConfig(name="Home", url="http://abs.local", token="tok", last_library_id="lib42")
    )
    cfg.save()

    loaded = AppConfig.load()
    assert loaded.servers[0].last_library_id == "lib42"


def test_config_last_library_id_defaults_empty(tmp_path, monkeypatch):
    """Old config files without last_library_id load without error."""
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text('{"servers": [{"name": "H", "url": "http://x", "token": "t"}], "active_server_index": 0}')
    monkeypatch.setattr("sixpack.config.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("sixpack.config.CONFIG_FILE", cfg_file)

    from sixpack.config import AppConfig
    cfg = AppConfig.load()
    assert cfg.servers[0].last_library_id == ""
