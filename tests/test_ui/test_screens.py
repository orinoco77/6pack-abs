"""UI screen tests using pytest-qt (headless)."""
from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from sixpack.api.models import (
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


def test_detail_screen_play_from_beginning(qtbot):
    screen = SeriesDetailScreen()
    qtbot.addWidget(screen)
    series = _make_series()
    screen.load(series, {})
    screen._list.setCurrentRow(0)

    with qtbot.waitSignal(screen.play_requested, timeout=1000) as blocker:
        screen._list.itemActivated.emit(screen._list.item(0))

    book, start_time = blocker.args
    assert book.id == "b1"
    assert start_time == 0.0


def test_detail_screen_play_resumes(qtbot):
    screen = SeriesDetailScreen()
    qtbot.addWidget(screen)
    series = _make_series()
    progress = {
        "b1": MediaProgress(libraryItemId="b1", currentTime=900.0, duration=1800.0)
    }
    screen.load(series, progress)
    screen._list.setCurrentRow(0)

    with qtbot.waitSignal(screen.play_requested, timeout=1000) as blocker:
        screen._list.itemActivated.emit(screen._list.item(0))

    book, start_time = blocker.args
    assert book.id == "b1"
    assert start_time == 900.0


def test_detail_screen_finished_ep_starts_from_zero(qtbot):
    screen = SeriesDetailScreen()
    qtbot.addWidget(screen)
    series = _make_series()
    progress = {
        "b1": MediaProgress(
            libraryItemId="b1", currentTime=1800.0, duration=1800.0, isFinished=True
        )
    }
    screen.load(series, progress)
    screen._list.setCurrentRow(0)

    with qtbot.waitSignal(screen.play_requested, timeout=1000) as blocker:
        screen._list.itemActivated.emit(screen._list.item(0))

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
