"""Tests for the DetailGridScreen base (series/playlist item grid shell)."""
from __future__ import annotations

from sixpack.api.models import MediaProgress
from sixpack.ui.screens.detail_grid import DetailGridScreen


class _FakeItem:
    def __init__(self, key, title, subtitle="", cover_url=None, duration=100.0):
        self.key = key
        self.title_ = title
        self.subtitle_ = subtitle
        self.cover_url = cover_url
        self.duration = duration


class _TestScreen(DetailGridScreen):
    """Minimal concrete subclass for testing the base in isolation."""

    def _item_key(self, item):
        return item.key

    def _item_progress(self, item, progress):
        p: MediaProgress | None = progress.get(item.key)
        if p is None or not item.duration:
            return 0.0, False
        finished = bool(p.is_finished)
        fraction = 0.0 if finished else max(0.0, min(1.0, p.current_time / item.duration))
        return fraction, finished

    def _item_progress_ids(self, item):
        return item.key, None

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
    progress = {"a": MediaProgress(currentTime=100.0, duration=100.0, isFinished=True)}
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
    screen._refresh_progress(
        {"a": MediaProgress(currentTime=100.0, duration=100.0, isFinished=True)}
    )
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
    screen._refresh_progress(
        {"a": MediaProgress(currentTime=100.0, duration=100.0, isFinished=True)}
    )
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


def test_detail_grid_populate_empty_clears_stale_hero_subtitle_and_backdrop(qtbot):
    """Populating with items sets a hero subtitle from focus reflection;
    re-populating the SAME (reused) screen instance with an empty list must
    not leave that stale subtitle (or the stale cover-wash backdrop) visible
    under the new, correct hero title — see detail_grid.py's _populate
    ``else`` branch.
    """
    screen = _TestScreen()
    qtbot.addWidget(screen)
    screen._populate("My Series", _items(), {}, "http://s", "t")
    assert screen._hero_backdrop._hero_sub.text() == "Item A"  # sanity: stale state exists

    screen._populate("Empty Series", [], {}, "http://s", "t")
    assert screen._hero_backdrop._hero_sub.text() == ""
    assert screen._grid.item_count == 0


def test_detail_grid_refresh_progress_preserves_navigated_focus(qtbot):
    """Regression: series/playlist detail screens populate instantly
    (show_loading(), no progress yet), then _refresh_progress() lands
    shortly after with the real progress data (update_progress(), once the
    async fetch resolves). If the user has already navigated away from the
    auto-focused card by then, _refresh_progress() must not snap focus
    back to the resume index."""
    screen = _TestScreen()
    qtbot.addWidget(screen)
    screen._populate("My Series", _items(), {}, "http://s", "t")
    assert screen._grid._focused_index == 0  # sanity: auto-focused item A

    screen._grid.focus_item(2)  # user navigates to item C

    screen._refresh_progress(
        {"a": MediaProgress(currentTime=100.0, duration=100.0, isFinished=True)}
    )
    assert screen._grid._focused_index == 2  # untouched, not reset to "b"


def test_detail_grid_refresh_progress_still_focuses_resume_if_untouched(qtbot):
    """If the user hasn't navigated since _populate()'s auto-focus, a
    landing _refresh_progress() call should still jump to the
    now-progress-aware resume index -- this is the existing, desired
    behavior the fix above must not break."""
    screen = _TestScreen()
    qtbot.addWidget(screen)
    screen._populate("My Series", _items(), {}, "http://s", "t")
    assert screen._grid._focused_index == 0  # untouched since populate

    screen._refresh_progress(
        {"a": MediaProgress(currentTime=100.0, duration=100.0, isFinished=True)}
    )
    assert screen._grid._focused_index == 1  # now resumes at item B


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


def test_item_progress_ids_default_from_test_screen(qtbot):
    screen = _TestScreen()
    qtbot.addWidget(screen)
    item_id, episode_id = screen._item_progress_ids(_FakeItem("a", "Item A"))
    assert item_id == "a"
    assert episode_id is None


def test_toggle_finished_on_unfinished_item_marks_finished_at_full_duration(qtbot):
    screen = _TestScreen()
    qtbot.addWidget(screen)
    screen._populate("My Series", _items(), {}, "http://s", "t")

    received = []
    screen.finished_changed.connect(lambda *args: received.append(args))
    screen._toggle_finished(0)

    assert received == [("a", 100.0, 100.0, True, "")]
    _fraction, finished = screen._item_progress(_items()[0], screen._progress)
    assert finished is True
    assert screen._grid._items[0]._finished is True


def test_toggle_finished_on_finished_item_marks_unfinished_preserving_position(qtbot):
    screen = _TestScreen()
    qtbot.addWidget(screen)
    progress = {"a": MediaProgress(currentTime=42.0, duration=100.0, isFinished=True)}
    screen._populate("My Series", _items(), progress, "http://s", "t")

    received = []
    screen.finished_changed.connect(lambda *args: received.append(args))
    screen._toggle_finished(0)

    assert received == [("a", 42.0, 100.0, False, "")]
    assert screen._grid._items[0]._finished is False


def test_toggle_finished_reverting_with_no_recorded_position_uses_zero(qtbot):
    """Marking an item unfinished when its recorded position is already
    0.0 (e.g. it was finished without ever really being played) must not
    fabricate a nonzero position -- distinct from the "preserving position"
    test above, which covers a nonzero recorded position."""
    screen = _TestScreen()
    qtbot.addWidget(screen)
    progress = {"a": MediaProgress(currentTime=0.0, duration=100.0, isFinished=True)}
    screen._populate("My Series", _items(), progress, "http://s", "t")

    received = []
    screen.finished_changed.connect(lambda *args: received.append(args))
    screen._toggle_finished(0)

    assert received == [("a", 0.0, 100.0, False, "")]


def test_toggle_finished_out_of_range_index_is_noop(qtbot):
    screen = _TestScreen()
    qtbot.addWidget(screen)
    screen._populate("My Series", _items(), {}, "http://s", "t")
    received = []
    screen.finished_changed.connect(lambda *args: received.append(args))
    screen._toggle_finished(99)
    assert received == []


def test_grid_long_press_opens_popup_with_correct_message(qtbot):
    screen = _TestScreen()
    qtbot.addWidget(screen)
    screen._populate("My Series", _items(), {}, "http://s", "t")
    screen.show()

    screen._grid.long_press_activated.emit(0)

    assert screen._finish_popup.isVisible()
    assert "Item A" in screen._finish_popup._message_label.text()
    assert "finished" in screen._finish_popup._message_label.text().lower()


def test_grid_long_press_on_finished_item_offers_unfinish_wording(qtbot):
    screen = _TestScreen()
    qtbot.addWidget(screen)
    progress = {"a": MediaProgress(currentTime=100.0, duration=100.0, isFinished=True)}
    screen._populate("My Series", _items(), progress, "http://s", "t")
    screen.show()

    screen._grid.long_press_activated.emit(0)

    assert "unfinished" in screen._finish_popup._message_label.text().lower()


def test_confirming_popup_toggles_finished_state(qtbot):
    screen = _TestScreen()
    qtbot.addWidget(screen)
    screen._populate("My Series", _items(), {}, "http://s", "t")
    screen.show()

    received = []
    screen.finished_changed.connect(lambda *args: received.append(args))
    screen._grid.long_press_activated.emit(0)
    screen._finish_popup.confirmed.emit()

    assert received == [("a", 100.0, 100.0, True, "")]


def test_cancelling_popup_does_not_toggle(qtbot):
    screen = _TestScreen()
    qtbot.addWidget(screen)
    screen._populate("My Series", _items(), {}, "http://s", "t")
    screen.show()

    received = []
    screen.finished_changed.connect(lambda *args: received.append(args))
    screen._grid.long_press_activated.emit(0)
    screen._finish_popup.cancelled.emit()

    assert received == []


def test_keypress_while_popup_visible_does_not_fall_through_to_back(qtbot):
    from PyQt6.QtCore import Qt

    screen = _TestScreen()
    qtbot.addWidget(screen)
    screen._populate("My Series", _items(), {}, "http://s", "t")
    screen.show()
    screen._grid.long_press_activated.emit(0)
    screen._finish_popup.setFocus()  # matches show_confirm()'s own setFocus() call --
    # once the popup is open, it (not the grid) is production's real focus holder.

    back_received = []
    screen.back_requested.connect(lambda: back_received.append(True))
    # BACK, sent to the popup -- matches production focus.
    qtbot.keyClick(screen._finish_popup, Qt.Key.Key_Backspace)

    assert back_received == []
    assert not screen._finish_popup.isVisible()  # BACK cancelled the popup instead


# ---------------------------------------------------------------------------
# Mark-finished popup's modal mouse-input shield ("scrim")
#
# Real bug: opening the mark-finished ConfirmPopup and then hovering any
# OTHER card calls FocusGrid.focus_item() -> self.setFocus() for that other
# card (widget.hovered is wired directly in FocusGrid.add_item()), stealing
# real Qt focus away from the still-visible popup -- after which arrow
# keys/Enter act on the grid underneath the open popup instead of the popup
# itself. The popup takes real focus but is a small centered widget, not
# full-screen, so mouse routing (which Qt resolves purely by widget
# stacking, not by who currently has focus) can still reach the other
# cards unless something covers them too.
# ---------------------------------------------------------------------------


def test_finish_popup_scrim_shows_and_covers_host_screen(qtbot):
    screen = _TestScreen()
    qtbot.addWidget(screen)
    screen.resize(900, 600)
    screen._populate("My Series", _items(), {}, "http://s", "t")
    screen.show()

    screen._grid.long_press_activated.emit(0)

    assert screen._finish_popup._scrim.isVisible()
    assert screen._finish_popup._scrim.geometry() == screen.rect()


def test_finish_popup_scrim_hidden_before_popup_opens(qtbot):
    screen = _TestScreen()
    qtbot.addWidget(screen)
    screen._populate("My Series", _items(), {}, "http://s", "t")
    assert not screen._finish_popup._scrim.isVisible()


def test_finish_popup_scrim_hidden_after_cancel(qtbot):
    """Uses handle_key() (Cancel is focused by default), not a raw
    `cancelled.emit()` -- the latter would skip straight to whatever's
    connected to the signal without going through _activate_cancel(),
    which is what actually hides the popup and its scrim in production."""
    from sixpack.input.actions import InputAction

    screen = _TestScreen()
    qtbot.addWidget(screen)
    screen._populate("My Series", _items(), {}, "http://s", "t")
    screen.show()
    screen._grid.long_press_activated.emit(0)
    assert screen._finish_popup._scrim.isVisible()

    screen._finish_popup.handle_key(InputAction.SELECT)

    assert not screen._finish_popup._scrim.isVisible()


def test_finish_popup_scrim_shields_a_different_card_from_real_hover(qtbot):
    """End-to-end regression proving the exact reported bug is fixed: with
    the mark-finished popup open on item 2, a real hover over a DIFFERENT
    card (item 0, deliberately chosen to sit outside the popup's own
    centered rect so this test isolates the shield's own coverage rather
    than incidental overlap with the popup itself) must land on the
    shield, not on that card -- so FocusGrid never receives its hovered
    signal, and self.setFocus() (the actual focus-stealing call) is never
    reached at all."""
    screen = _TestScreen()
    qtbot.addWidget(screen)
    screen.resize(900, 600)
    screen.show()
    qtbot.waitExposed(screen)
    screen._populate("My Series", _items(), {}, "http://s", "t")
    qtbot.wait(20)  # let the grid layout settle before hit-testing it

    other_card = screen._grid._items[0]
    pos = other_card.mapTo(screen, other_card.rect().center())
    assert screen.childAt(pos) is other_card or other_card.isAncestorOf(screen.childAt(pos))
    # Sanity: the popup's own rect must NOT already cover this point, or
    # this test wouldn't actually be exercising the shield.
    assert not screen._finish_popup.geometry().contains(pos)

    screen._grid.long_press_activated.emit(2)  # opens the popup for item 2

    assert screen.childAt(pos) is screen._finish_popup._scrim


def test_select_at_grid_while_popup_visible_confirms_not_plays(qtbot):
    """Regression: FocusGrid holds real Qt focus in production, not the
    host screen -- Select while the popup is open must confirm/toggle the
    pending item, not play the currently-focused card underneath."""
    from PyQt6.QtCore import Qt

    screen = _TestScreen()
    qtbot.addWidget(screen)
    screen._populate("My Series", _items(), {}, "http://s", "t")
    screen.show()

    activated = []
    screen.item_activated.connect(lambda item: activated.append(item))
    finished_received = []
    screen.finished_changed.connect(lambda *args: finished_received.append(args))

    screen._grid.long_press_activated.emit(0)
    screen._finish_popup.setFocus()  # matches show_confirm()'s own setFocus() call
    qtbot.keyClick(screen._finish_popup, Qt.Key.Key_Right)  # move to Confirm
    qtbot.keyClick(screen._finish_popup, Qt.Key.Key_Return)  # confirm

    assert finished_received == [("a", 100.0, 100.0, True, "")]
    assert activated == []  # must NOT have played the card underneath


def test_right_at_grid_while_popup_visible_does_not_move_card_focus(qtbot):
    """Regression: LEFT/RIGHT while the popup is open must move the
    popup's own Cancel/Confirm selection, not the grid's card focus
    underneath (which FocusGrid would otherwise consume first)."""
    from PyQt6.QtCore import Qt

    screen = _TestScreen()
    qtbot.addWidget(screen)
    screen._populate("My Series", _items(), {}, "http://s", "t")
    screen.show()
    grid_focus_before = screen._grid._focused_index

    screen._grid.long_press_activated.emit(0)
    screen._finish_popup.setFocus()
    qtbot.keyClick(screen._finish_popup, Qt.Key.Key_Right)

    assert screen._grid._focused_index == grid_focus_before  # unchanged
    assert screen._finish_popup._focus_index == 1  # popup's own selection moved


def test_confirming_popup_restores_focus_to_grid(qtbot):
    from PyQt6.QtTest import QTest

    screen = _TestScreen()
    qtbot.addWidget(screen)
    screen._populate("My Series", _items(), {}, "http://s", "t")
    screen.show()
    qtbot.waitExposed(screen)
    screen.activateWindow()
    QTest.qWaitForWindowActive(screen)

    screen._grid.long_press_activated.emit(0)
    screen._finish_popup.confirmed.emit()

    assert screen._grid.hasFocus()


def test_cancelling_popup_clears_pending_index_and_restores_grid_focus(qtbot):
    from PyQt6.QtTest import QTest

    screen = _TestScreen()
    qtbot.addWidget(screen)
    screen._populate("My Series", _items(), {}, "http://s", "t")
    screen.show()
    qtbot.waitExposed(screen)
    screen.activateWindow()
    QTest.qWaitForWindowActive(screen)

    screen._grid.long_press_activated.emit(0)
    assert screen._pending_finish_index == 0
    screen._finish_popup.cancelled.emit()

    assert screen._pending_finish_index is None
    assert screen._grid.hasFocus()


def test_repopulating_hides_stale_popup_and_clears_pending_index(qtbot):
    screen = _TestScreen()
    qtbot.addWidget(screen)
    screen._populate("My Series", _items(), {}, "http://s", "t")
    screen.show()
    screen._grid.long_press_activated.emit(0)
    assert screen._finish_popup.isVisible()

    screen._populate("Different Series", _items(), {}, "http://s", "t")

    assert not screen._finish_popup.isVisible()
    assert screen._pending_finish_index is None


def test_toggle_finished_reverting_from_full_duration_resets_to_zero(qtbot):
    """Regression: un-finishing an item whose recorded position is already
    at/past duration (set that way by this exact feature's own 'mark
    finished' action, or by a natural ABS auto-finish) must not leave a
    100%-progress-bar-but-unfinished contradiction -- reset to 0.0 instead
    of preserving the stale full-duration value."""
    screen = _TestScreen()
    qtbot.addWidget(screen)
    progress = {"a": MediaProgress(currentTime=100.0, duration=100.0, isFinished=True)}
    screen._populate("My Series", _items(), progress, "http://s", "t")

    received = []
    screen.finished_changed.connect(lambda *args: received.append(args))
    screen._toggle_finished(0)

    assert received == [("a", 0.0, 100.0, False, "")]
