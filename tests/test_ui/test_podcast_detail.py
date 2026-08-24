"""Tests for PodcastDetailScreen."""
from __future__ import annotations

from sixpack.api.models import LibraryItem, LibraryItemMedia, MediaProgress, PodcastEpisode
from sixpack.ui.screens.podcast_detail import PodcastDetailScreen


def _episode(episode_id, title, duration=1800.0):
    return PodcastEpisode(
        id=episode_id, libraryItemId="show1", title=title,
        audioFile={"duration": duration},
    )


def _show(episodes):
    return LibraryItem(
        id="show1", libraryId="lib1", mediaType="podcast",
        media=LibraryItemMedia(metadata={"title": "My Show"}, episodes=episodes),
    )


def test_podcast_detail_screen_creates(qtbot):
    screen = PodcastDetailScreen()
    qtbot.addWidget(screen)
    assert screen._grid is not None


def test_podcast_detail_screen_load(qtbot):
    screen = PodcastDetailScreen()
    qtbot.addWidget(screen)
    show = _show([_episode("ep1", "Episode One"), _episode("ep2", "Episode Two")])
    screen.load(show, {}, "http://abs.test:13378", "tok")
    assert screen._hero_backdrop._hero_title.text() == "My Show"
    assert screen._grid.item_count == 2


def test_podcast_detail_screen_show_loading(qtbot):
    screen = PodcastDetailScreen()
    qtbot.addWidget(screen)
    show = _show([_episode("ep1", "Episode One")])
    screen.show_loading(show, "http://abs.test:13378", "tok")
    assert screen._grid.item_count == 1


def test_podcast_detail_screen_item_activated_emits_episode(qtbot):
    screen = PodcastDetailScreen()
    qtbot.addWidget(screen)
    show = _show([_episode("ep1", "Episode One")])
    screen.load(show, {}, "http://abs.test:13378", "tok")

    received = []
    screen.item_activated.connect(received.append)
    screen._on_item_activated(0)

    assert len(received) == 1
    assert received[0].id == "ep1"


def test_podcast_detail_screen_progress_keyed_by_episode_id(qtbot):
    screen = PodcastDetailScreen()
    qtbot.addWidget(screen)
    show = _show([_episode("ep1", "Episode One", duration=1000.0)])
    progress = {
        "ep1": MediaProgress(
            libraryItemId="show1", episodeId="ep1", currentTime=500.0, duration=1000.0
        )
    }
    screen.load(show, progress, "http://abs.test:13378", "tok")
    fraction, finished = screen._item_progress(show.media.episodes[0], progress)
    assert fraction == 0.5
    assert finished is False


def test_podcast_detail_screen_episode_cover_uses_show_cover(qtbot):
    """Episodes have no cover art of their own — every card in this grid
    uses the parent show's cover."""
    screen = PodcastDetailScreen()
    qtbot.addWidget(screen)
    show = _show([_episode("ep1", "Episode One")])
    screen.load(show, {}, "http://abs.test:13378", "tok")
    url = screen._item_cover_url(show.media.episodes[0], "http://abs.test:13378", "tok")
    assert url == show.cover_url("http://abs.test:13378", "tok")


def test_podcast_detail_screen_show_loading_with_no_episodes_shows_title_and_loading_hint(qtbot):
    """Browse-row podcast items carry NO episodes (Task 6) — show_loading()
    is called with that lightweight item before the full-item fetch
    resolves, so the grid is always empty at this point. The user must
    still see the show's real title plus a loading affordance, not a blank
    screen with no indication anything is happening (final whole-plan
    review, Fix 4)."""
    screen = PodcastDetailScreen()
    qtbot.addWidget(screen)
    show = _show([])  # no episodes yet — matches the real browse-row shape
    screen.show_loading(show, "http://abs.test:13378", "tok")
    assert screen._hero_backdrop._hero_title.text() == "My Show"
    assert "Loading" in screen._hero_backdrop._hero_sub.text()


def test_podcast_detail_screen_back_signal(qtbot):
    screen = PodcastDetailScreen()
    qtbot.addWidget(screen)
    received = []
    screen.back_requested.connect(lambda: received.append(True))
    screen.back_requested.emit()
    assert received == [True]


def test_podcast_detail_item_progress_ids(qtbot):
    screen = PodcastDetailScreen()
    qtbot.addWidget(screen)
    episode = _episode("ep1", "Episode One")
    assert screen._item_progress_ids(episode) == ("show1", "ep1")
