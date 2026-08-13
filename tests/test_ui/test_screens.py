"""UI screen tests using pytest-qt (headless)."""
from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from sixpack.api.models import (
    Chapter,
    Library,
    LibraryItemMedia,
    MediaProgress,
    Series,
    SeriesBook,
)
from sixpack.ui.screens.login import LoginScreen
from sixpack.ui.screens.library import LibraryScreen
from sixpack.ui.screens.series import SeriesScreen
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


# ---- LibraryScreen ----

def _make_libraries():
    return [
        Library(id="lib1", name="Audiobooks", mediaType="book"),
        Library(id="lib2", name="Drama", mediaType="podcast"),
    ]


def test_library_screen_creates(qtbot):
    screen = LibraryScreen()
    qtbot.addWidget(screen)
    assert screen._list is not None


def test_library_screen_set_libraries(qtbot):
    screen = LibraryScreen()
    qtbot.addWidget(screen)
    screen.set_libraries(_make_libraries())
    assert screen._list.count() == 2


def test_library_screen_emits_on_activate(qtbot):
    screen = LibraryScreen()
    qtbot.addWidget(screen)
    libs = _make_libraries()
    screen.set_libraries(libs)

    with qtbot.waitSignal(screen.library_selected, timeout=1000) as blocker:
        screen._list.itemActivated.emit(screen._list.item(0))

    assert blocker.args[0].id == "lib1"


def test_library_screen_empty(qtbot):
    screen = LibraryScreen()
    qtbot.addWidget(screen)
    screen.set_libraries([])
    assert screen._list.count() == 0


def test_library_screen_enter_key(qtbot):
    screen = LibraryScreen()
    qtbot.addWidget(screen)
    screen.set_libraries(_make_libraries())
    screen._list.setCurrentRow(1)

    with qtbot.waitSignal(screen.library_selected, timeout=1000) as blocker:
        qtbot.keyClick(screen._list, Qt.Key.Key_Return)

    assert blocker.args[0].id == "lib2"


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


def test_detail_screen_load(qtbot):
    screen = SeriesDetailScreen()
    qtbot.addWidget(screen)
    series = _make_series()
    screen.load(series, {})
    assert screen._list.count() == 2
    assert screen._title_label.text() == "My Drama Series"


def test_detail_screen_back_signal(qtbot):
    screen = SeriesDetailScreen()
    qtbot.addWidget(screen)
    series = _make_series()
    screen.load(series, {})

    with qtbot.waitSignal(screen.back_requested, timeout=1000):
        qtbot.keyClick(screen, Qt.Key.Key_Escape)


def test_detail_screen_item_emits_episode_activated(qtbot):
    """Clicking any item always emits episode_activated (chapter check happens in app)."""
    screen = SeriesDetailScreen()
    qtbot.addWidget(screen)
    series = _make_series()
    screen.load(series, {})
    screen._list.setCurrentRow(0)

    with qtbot.waitSignal(screen.episode_activated, timeout=1000) as blocker:
        screen._list.itemActivated.emit(screen._list.item(0))

    assert blocker.args[0].id == "b1"


def test_detail_screen_item_does_not_emit_play_requested(qtbot):
    """Item click must not emit play_requested — that is handled by app after chapter fetch."""
    screen = SeriesDetailScreen()
    qtbot.addWidget(screen)
    screen.load(_make_series(), {})

    play_signals = []
    screen.play_requested.connect(lambda b, t: play_signals.append((b, t)))
    screen._list.itemActivated.emit(screen._list.item(0))
    assert play_signals == []


def test_detail_play_all_resumes_from_progress(qtbot):
    """Play All still emits play_requested at correct resume position."""
    screen = SeriesDetailScreen()
    qtbot.addWidget(screen)
    series = _make_series()
    progress = {"b1": MediaProgress(libraryItemId="b1", currentTime=900.0, duration=1800.0)}
    screen.load(series, progress)

    with qtbot.waitSignal(screen.play_requested, timeout=1000) as blocker:
        screen._play_all_btn.click()

    book, start_time = blocker.args
    assert book.id == "b1"
    assert start_time == 900.0


def test_detail_play_all_finished_restarts(qtbot):
    """Play All starts a fully-finished book from 0.0."""
    screen = SeriesDetailScreen()
    qtbot.addWidget(screen)
    series = _make_series()
    progress = {
        "b1": MediaProgress(libraryItemId="b1", currentTime=1800.0, duration=1800.0, isFinished=True),
        "b2": MediaProgress(libraryItemId="b2", currentTime=3600.0, duration=3600.0, isFinished=True),
    }
    screen.load(series, progress)

    with qtbot.waitSignal(screen.play_requested, timeout=1000) as blocker:
        screen._play_all_btn.click()

    _, start_time = blocker.args
    assert start_time == 0.0


def test_detail_screen_play_all_finds_resume(qtbot):
    screen = SeriesDetailScreen()
    qtbot.addWidget(screen)
    series = _make_series()
    progress = {
        "b1": MediaProgress(libraryItemId="b1", currentTime=1800.0, isFinished=True),
    }
    screen.load(series, progress)

    with qtbot.waitSignal(screen.play_requested, timeout=1000) as blocker:
        screen._play_all_btn.click()

    book, _ = blocker.args
    assert book.id == "b2"  # b1 is finished, so resume from b2


def test_detail_resume_index_all_finished(qtbot):
    screen = SeriesDetailScreen()
    qtbot.addWidget(screen)
    series = _make_series()
    progress = {
        "b1": MediaProgress(libraryItemId="b1", isFinished=True),
        "b2": MediaProgress(libraryItemId="b2", isFinished=True),
    }
    screen.load(series, progress)
    assert screen._find_resume_index() == 0  # all done → restart from first


def test_detail_show_loading_renders_episodes(qtbot):
    """show_loading() renders episodes immediately with grey dots."""
    screen = SeriesDetailScreen()
    qtbot.addWidget(screen)
    screen.show_loading(_make_series())
    assert screen._list.count() == 2
    assert not screen._loading_label.isHidden()


def test_detail_update_progress_hides_loading(qtbot):
    screen = SeriesDetailScreen()
    qtbot.addWidget(screen)
    screen.show_loading(_make_series())
    assert not screen._loading_label.isHidden()
    screen.update_progress({})
    assert screen._loading_label.isHidden()


def test_detail_update_progress_dot_colour(qtbot):
    """After update_progress, finished episode dot changes to SUCCESS colour."""
    from sixpack.ui import theme
    screen = SeriesDetailScreen()
    qtbot.addWidget(screen)
    screen.show_loading(_make_series())

    progress = {"b1": MediaProgress(libraryItemId="b1", isFinished=True)}
    screen.update_progress(progress)

    item = screen._list.item(0)
    widget = screen._list.itemWidget(item)
    assert theme.SUCCESS in widget._dot.styleSheet()


def test_detail_episode_item_update_progress(qtbot):
    media = LibraryItemMedia(metadata={"title": "Ep"}, duration=3600.0)
    book = SeriesBook(id="b1", libraryId="lib1", media=media, sequence="1")
    from sixpack.ui.screens.series_detail import EpisodeItem
    from sixpack.ui import theme
    widget = EpisodeItem(book, None)
    qtbot.addWidget(widget)

    assert theme.TEXT_MUTED in widget._dot.styleSheet()

    prog = MediaProgress(libraryItemId="b1", currentTime=1800.0, duration=3600.0)
    widget.update_progress(prog)
    assert theme.ACCENT in widget._dot.styleSheet()
    assert "30m" in widget._duration_label.text()


def test_detail_episode_item_has_cover_label(qtbot):
    from sixpack.ui.screens.series_detail import EpisodeItem
    media = LibraryItemMedia(metadata={"title": "Ep"}, duration=3600.0)
    book = SeriesBook(id="b1", libraryId="lib1", media=media)
    widget = EpisodeItem(book, None)
    qtbot.addWidget(widget)
    assert widget._cover_label is not None
    assert widget._cover_label.width() == 44


def test_detail_episode_item_chapter_badge(qtbot):
    """Chapter count label present when book has >1 chapters."""
    from sixpack.ui.screens.series_detail import EpisodeItem
    from sixpack.api.models import Chapter
    chapters = [Chapter(id=i, start=i * 900.0, end=(i + 1) * 900.0, title=f"Ch {i}") for i in range(4)]
    media = LibraryItemMedia(metadata={"title": "Box Set"}, duration=3600.0, chapters=chapters)
    book = SeriesBook(id="b1", libraryId="lib1", media=media)
    widget = EpisodeItem(book, None)
    qtbot.addWidget(widget)
    # Find the chapter count label by text
    from PyQt6.QtWidgets import QLabel
    labels = widget.findChildren(QLabel)
    ch_texts = [l.text() for l in labels if "ch" in l.text()]
    assert any("4 ch" in t for t in ch_texts)


def test_detail_episode_activated_any_book(qtbot):
    """episode_activated is emitted for any book (box-set or single), not play_requested."""
    chapters = [Chapter(id=i, start=i * 900.0, end=(i + 1) * 900.0, title=f"Ch {i}") for i in range(3)]
    media_box = LibraryItemMedia(metadata={"title": "Box Set"}, duration=2700.0, chapters=chapters)
    media_single = LibraryItemMedia(metadata={"title": "Single Book"}, duration=3600.0)
    book_box = SeriesBook(id="bx", libraryId="lib1", media=media_box, sequence="1")
    book_single = SeriesBook(id="bs", libraryId="lib1", media=media_single, sequence="2")
    series = Series(id="s1", name="Drama", books=[book_box, book_single])

    screen = SeriesDetailScreen()
    qtbot.addWidget(screen)
    screen.load(series, {})

    ep_signals = []
    play_signals = []
    screen.episode_activated.connect(lambda b: ep_signals.append(b))
    screen.play_requested.connect(lambda b, t: play_signals.append((b, t)))

    screen._list.itemActivated.emit(screen._list.item(0))
    screen._list.itemActivated.emit(screen._list.item(1))

    assert len(ep_signals) == 2
    assert ep_signals[0] is book_box
    assert ep_signals[1] is book_single
    assert play_signals == []


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
    assert screen._title_label.text() == "Invasion of Earth"
    assert "3 chapters" in screen._count_label.text()


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
    assert screen._title_label.text() == "Doctor Who: Invasion"
    assert "3 chapters" in screen._count_label.text()
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


# ---- SeriesScreen library combo ----

def _make_three_libraries():
    return [
        Library(id="lib1", name="Audio Dramas", mediaType="book", icon="database"),
        Library(id="lib2", name="Audiobooks", mediaType="book", icon="database"),
        Library(id="lib3", name="Podcasts", mediaType="podcast", icon="microphone"),
    ]


def test_series_screen_combo_populates(qtbot):
    screen = SeriesScreen()
    qtbot.addWidget(screen)
    libs = _make_three_libraries()
    screen.load(libs[0], [], "http://localhost", "tok", all_libraries=libs)

    menu = screen._make_library_menu()
    assert menu.actions()[0].text() == "Audio Dramas"
    assert menu.actions()[1].text() == "Audiobooks"
    assert len(menu.actions()) == 3


def test_series_screen_combo_selects_current_library(qtbot):
    screen = SeriesScreen()
    qtbot.addWidget(screen)
    libs = _make_three_libraries()
    screen.load(libs[1], [], "http://localhost", "tok", all_libraries=libs)

    menu = screen._make_library_menu()
    assert menu.actions()[1].isChecked()
    assert not menu.actions()[0].isChecked()


def test_series_screen_combo_switch_emits_signal(qtbot):
    screen = SeriesScreen()
    qtbot.addWidget(screen)
    libs = _make_three_libraries()
    screen.load(libs[0], [], "http://localhost", "tok", all_libraries=libs)

    with qtbot.waitSignal(screen.library_switch_requested, timeout=1000) as blocker:
        menu = screen._make_library_menu()
        menu.actions()[2].trigger()

    assert blocker.args[0].id == "lib3"


def test_series_screen_combo_no_signal_same_library(qtbot):
    screen = SeriesScreen()
    qtbot.addWidget(screen)
    libs = _make_three_libraries()
    screen.load(libs[0], [], "http://localhost", "tok", all_libraries=libs)

    signals = []
    screen.library_switch_requested.connect(lambda lib: signals.append(lib))
    # Reload same library — no switch signal
    screen.load(libs[0], [], "http://localhost", "tok", all_libraries=libs)
    assert signals == []


def test_series_screen_load_without_all_libraries(qtbot):
    """Calling load() without all_libraries keeps existing menu state."""
    screen = SeriesScreen()
    qtbot.addWidget(screen)
    libs = _make_three_libraries()
    screen.load(libs[0], [], "http://localhost", "tok", all_libraries=libs)
    # Second load without passing all_libraries — menu count unchanged
    screen.load(libs[1], [], "http://localhost", "tok")
    assert len(screen._make_library_menu().actions()) == 3
