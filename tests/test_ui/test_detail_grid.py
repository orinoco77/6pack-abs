"""Tests for the DetailGridScreen base (series/playlist item grid shell)."""
from __future__ import annotations

from sixpack.ui.screens.detail_grid import DetailGridScreen


class _FakeItem:
    def __init__(self, key, title, subtitle="", cover_url=None):
        self.key = key
        self.title_ = title
        self.subtitle_ = subtitle
        self.cover_url = cover_url


class _TestScreen(DetailGridScreen):
    """Minimal concrete subclass for testing the base in isolation."""

    def _item_key(self, item):
        return item.key

    def _item_progress(self, item, progress):
        p = progress.get(item.key)
        if p is None:
            return 0.0, False
        return p.get("fraction", 0.0), p.get("finished", False)

    def _item_title(self, item):
        return item.title_

    def _item_subtitle(self, item):
        return item.subtitle_

    def _item_cover_url(self, item, server_url, token):
        return item.cover_url  # None unless a test opts in


def _items():
    return [_FakeItem("a", "Item A"), _FakeItem("b", "Item B"), _FakeItem("c", "Item C")]


class _FakeCoverCache:
    """Captures fetch/fetch_backdrop calls instead of invoking them, so the
    test can assert exactly how many times each was invoked without a real
    network-backed CoverCache. Same pattern as
    tests/test_ui/test_screens.py's _FakeCoverCache (~line 405).
    """

    def __init__(self):
        self.fetch_calls = []
        self.fetch_backdrop_calls = []

    def fetch(self, url, token, callback):
        self.fetch_calls.append((url, token, callback))

    def fetch_backdrop(self, url, token, callback):
        self.fetch_backdrop_calls.append((url, token, callback))


def test_detail_grid_populate_sets_hero_title_and_cards(qtbot):
    screen = _TestScreen()
    qtbot.addWidget(screen)
    screen._populate("My Series", _items(), {}, "http://s", "t")
    assert screen._hero_backdrop._hero_title.text() == "My Series"
    assert screen._grid.item_count == 3


def test_detail_grid_populate_focuses_resume_index(qtbot):
    screen = _TestScreen()
    qtbot.addWidget(screen)
    progress = {"a": {"fraction": 1.0, "finished": True}}
    screen._populate("My Series", _items(), progress, "http://s", "t")
    # item "a" is finished, "b" should be the resume point
    assert screen._grid._focused_index == 1


def test_detail_grid_populate_reflects_focused_item_in_hero_subtitle(qtbot):
    screen = _TestScreen()
    qtbot.addWidget(screen)
    screen._populate("My Series", _items(), {}, "http://s", "t")
    assert screen._hero_backdrop._hero_sub.text() == "Item A"


def test_detail_grid_item_activated_emits_raw_item(qtbot):
    screen = _TestScreen()
    qtbot.addWidget(screen)
    screen._populate("My Series", _items(), {}, "http://s", "t")
    with qtbot.waitSignal(screen.item_activated, timeout=1000) as blocker:
        screen._grid.item_activated.emit(1)
    assert blocker.args[0].key == "b"


def test_detail_grid_refresh_progress_updates_in_place_without_rebuild(qtbot):
    screen = _TestScreen()
    qtbot.addWidget(screen)
    screen._populate("My Series", _items(), {}, "http://s", "t")
    card_before = screen._grid._items[0]
    screen._refresh_progress({"a": {"fraction": 1.0, "finished": True}})
    assert screen._grid._items[0] is card_before  # same card instances, not rebuilt
    assert screen._grid.item_count == 3


def test_detail_grid_refresh_progress_sets_finished_badge(qtbot):
    """_refresh_progress's card.set_finished(finished) call has an observable
    effect: MediaCard.set_finished stores the flag on _finished (and shows
    the finished badge), not just a no-op cosmetic call.
    """
    screen = _TestScreen()
    qtbot.addWidget(screen)
    screen._populate("My Series", _items(), {}, "http://s", "t")
    card = screen._grid._items[0]
    assert card._finished is False  # sanity: starts unfinished
    screen._refresh_progress({"a": {"fraction": 1.0, "finished": True}})
    assert card._finished is True
    assert card._finished_badge.isVisibleTo(card._body)


def test_detail_grid_focus_item_by_key(qtbot):
    screen = _TestScreen()
    qtbot.addWidget(screen)
    screen._populate("My Series", _items(), {}, "http://s", "t")
    screen.focus_item_by_key("c")
    assert screen._grid._focused_index == 2


def test_detail_grid_focus_item_by_key_missing_is_noop(qtbot):
    screen = _TestScreen()
    qtbot.addWidget(screen)
    screen._populate("My Series", _items(), {}, "http://s", "t")
    screen.focus_item_by_key("does-not-exist")
    assert screen._grid._focused_index == 0  # unchanged


def test_detail_grid_back_key_emits_back_requested(qtbot):
    from PyQt6.QtCore import Qt
    screen = _TestScreen()
    qtbot.addWidget(screen)
    screen._populate("My Series", _items(), {}, "http://s", "t")
    screen.show()
    with qtbot.waitSignal(screen.back_requested, timeout=1000):
        qtbot.keyClick(screen, Qt.Key.Key_Backspace)


def test_detail_grid_populate_fetches_backdrop_exactly_once(qtbot):
    """_populate() calls FocusGrid.focus_item(), which itself emits
    focus_changed -> _on_grid_focus_changed -> _reflect_focus(). A redundant
    explicit _reflect_focus() call right after focus_item() would fire
    _reflect_focus() twice back-to-back for the initially-focused item,
    which calls Backdrop.show_color()/show_image() twice in immediate
    succession and resets/defeats the cross-fade animation (see
    backdrop.py's show_image, which stops and restarts `_anim` on every
    call). Assert fetch_backdrop is invoked exactly once, not twice.
    """
    fake_cache = _FakeCoverCache()
    screen = _TestScreen(cover_cache=fake_cache)
    qtbot.addWidget(screen)
    items = [
        _FakeItem("a", "Item A", cover_url="http://s/cover/a"),
        _FakeItem("b", "Item B", cover_url="http://s/cover/b"),
    ]
    screen._populate("My Series", items, {}, "http://s", "t")
    assert len(fake_cache.fetch_backdrop_calls) == 1
