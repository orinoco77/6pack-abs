"""Main application window with screen navigation stack."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from PyQt6.QtCore import (
    Q_ARG,
    QEvent,
    QMetaObject,
    QObject,
    Qt,
    QThread,
    QTimer,
    pyqtSignal,
    pyqtSlot,
)
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication, QMainWindow, QStackedWidget

from sixpack.api.client import ABSClient
from sixpack.api.models import (
    Library,
    LibraryItem,
    MediaProgress,
    Playlist,
    PlaylistItem,
    PodcastEpisode,
    Series,
    SeriesBook,
)
from sixpack.config import AppConfig, ServerConfig
from sixpack.input.actions import InputAction
from sixpack.input.gamepad import GamepadListener
from sixpack.player.player import AudioPlayer, PlayerError
from sixpack.ui.browse_cache import BrowseCache
from sixpack.ui.cover_cache import CoverCache
from sixpack.ui.screens.browse import BrowseScreen, RowType
from sixpack.ui.screens.chapter_select import ChapterSelectScreen
from sixpack.ui.screens.login import LoginScreen
from sixpack.ui.screens.player import PlayerScreen
from sixpack.ui.screens.playlist_detail import PlaylistDetailScreen
from sixpack.ui.screens.podcast_detail import PodcastDetailScreen
from sixpack.ui.screens.series_detail import SeriesDetailScreen
from sixpack.ui.screens.splash import SplashScreen
from sixpack.ui.screens.update_prompt import UpdatePromptScreen
from sixpack.updater import (
    CURRENT_VERSION,
    ReleaseInfo,
    UpdateError,
    apply_update,
    fetch_latest_release,
    is_newer,
    relaunch,
)

logger = logging.getLogger(__name__)


def _author_surname_sort_key(item: LibraryItem) -> tuple[int, str, str]:
    """Sort key for the "All Books" row: alphabetical by the primary
    author's surname, case-insensitive.

    Audiobookshelf has no server-side "sort by surname" (only by the raw
    authorName string, which would file "Terry Pratchett" under T), so
    this is done client-side. A multi-author work stores its authors as
    one comma-joined string (e.g. "Terry Pratchett, Neil Gaiman") --
    this sorts by the FIRST-listed (primary) author only, and within
    that author's name by its last whitespace-separated token (a
    pragmatic heuristic, not true name parsing -- "Ursula K. Le Guin"
    sorts under "Guin" rather than "Le Guin"). Items with no author
    metadata sort after everything else. Title is the tiebreaker so the
    overall order is always fully deterministic.
    """
    author = (item.author or "").split(",", 1)[0].strip()
    title_key = (item.title or "").casefold()
    if not author:
        return (1, "", title_key)
    surname = author.split()[-1]
    return (0, surname.casefold(), title_key)


# Gamepad actions are delivered to the app by synthesizing the equivalent
# keyboard key event and sending it to whatever widget currently has focus
# -- reusing every screen's existing keyPressEvent/key_to_action handling
# instead of duplicating per-screen gamepad dispatch logic. Only keys that
# key_to_action maps identically in both _NAV_MAP and _PLAYER_MAP (see
# keyboard.py) are safe representatives here, since the receiving screen's
# mode isn't known from this side.
_GAMEPAD_ACTION_TO_KEY: dict[InputAction, Qt.Key] = {
    InputAction.UP: Qt.Key.Key_Up,
    InputAction.DOWN: Qt.Key.Key_Down,
    InputAction.LEFT: Qt.Key.Key_Left,
    InputAction.RIGHT: Qt.Key.Key_Right,
    InputAction.SELECT: Qt.Key.Key_Return,
    InputAction.BACK: Qt.Key.Key_Backspace,
    InputAction.PLAY_PAUSE: Qt.Key.Key_MediaTogglePlayPause,
    InputAction.PREV_CHAPTER: Qt.Key.Key_Comma,
    InputAction.NEXT_CHAPTER: Qt.Key.Key_Period,
}


class AsyncWorker(QObject):
    """
    Runs coroutines on a dedicated asyncio event loop in a QThread.
    Results are delivered back via Qt signals so callers don't block the GUI.
    """

    result = pyqtSignal(str, object)   # tag, result
    error = pyqtSignal(str, str)       # tag, error message

    def __init__(self) -> None:
        super().__init__()
        self._loop: asyncio.AbstractEventLoop | None = None

    def start_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def stop_loop(self) -> None:
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)

    def run(self, tag: str, coro) -> None:
        if self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._run_coro(tag, coro), self._loop)

    async def _run_coro(self, tag: str, coro) -> None:
        try:
            result = await coro
            self.result.emit(tag, result)
        except Exception as exc:
            logger.exception("Async task '%s' failed", tag)
            self.error.emit(tag, str(exc))


class MainWindow(QMainWindow):
    _UP_NEXT_DELAY_MS = 3000

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self._config = config
        self._client: ABSClient | None = None
        self._server_url = ""
        self._token = ""
        self._current_series: Series | None = None
        self._current_playlist: Playlist | None = None
        self._pending_book: SeriesBook | None = None
        self._pending_playlist_item: PlaylistItem | None = None
        self._pending_browse_item: LibraryItem | None = None
        self._current_podcast_show: LibraryItem | None = None
        self._pending_podcast_episode: PodcastEpisode | None = None
        self._pending_release: ReleaseInfo | None = None
        self._libraries: list[Library] = []
        # Back-navigation context: "detail" | "browse" | "playlist_detail" | "podcast_detail"
        self._chapter_back_target = "detail"
        # Back-navigation context:
        # "detail" | "chapter" | "browse" | "playlist_detail" | "podcast_detail"
        self._player_back_target = "detail"
        # Generation counter guarding the pending "up next" QTimer.singleShot
        # scheduled by _on_track_ended — see _on_track_ended/
        # _advance_after_up_next for why (an uncancellable stale timer can
        # otherwise fire after a manual next/prev/back action has already
        # started something else, and yank the user away from it).
        self._up_next_generation = 0

        self._init_player()
        self._init_worker()
        self._init_gamepad()
        self._build_ui()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _init_player(self) -> None:
        try:
            self._player = AudioPlayer()
        except PlayerError as exc:
            logger.warning("Audio player unavailable: %s", exc)
            self._player = None  # type: ignore[assignment]

    def _init_worker(self) -> None:
        self._worker = AsyncWorker()
        self._thread = QThread()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.start_loop)
        self._worker.result.connect(self._on_result)
        self._worker.error.connect(self._on_error)
        self._thread.start()

    def _init_gamepad(self) -> None:
        # GamepadListener.start() fails soft (logs and returns) if evdev
        # or no gamepad is available -- safe to construct/start
        # unconditionally, matching _init_player()'s "degrade, don't
        # crash" pattern for optional hardware.
        self._gamepad = GamepadListener(self._on_gamepad_action)
        self._gamepad.start()

    def _on_gamepad_action(self, action: InputAction, is_press: bool) -> None:
        # Called from GamepadListener's background reader thread (one per
        # detected device) -- must not touch any QWidget/QApplication state
        # directly from here. Marshal to the GUI thread via a queued
        # invokeMethod, mirroring PlayerScreen's mpv-callback pattern.
        key = _GAMEPAD_ACTION_TO_KEY.get(action)
        if key is None:
            return
        QMetaObject.invokeMethod(
            self, "_dispatch_gamepad_key",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(int, key.value),
            Q_ARG(bool, is_press),
        )

    @pyqtSlot(int, bool)
    def _dispatch_gamepad_key(self, key_value: int, is_press: bool) -> None:
        target = QApplication.focusWidget()
        if target is None:
            return
        event_type = QEvent.Type.KeyPress if is_press else QEvent.Type.KeyRelease
        event = QKeyEvent(event_type, Qt.Key(key_value), Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(target, event)

    def _build_ui(self) -> None:
        self.setWindowTitle("SixPack — Audiobookshelf")
        self.showFullScreen()
        self._setup_cursor_autohide()

        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        self._cover_cache = CoverCache(parent=self)
        self._browse_cache = BrowseCache()

        self._splash_screen = SplashScreen()
        self._login_screen = LoginScreen()
        self._browse_screen = BrowseScreen(cover_cache=self._cover_cache)
        self._detail_screen = SeriesDetailScreen(cover_cache=self._cover_cache)
        self._playlist_detail_screen = PlaylistDetailScreen(cover_cache=self._cover_cache)
        self._podcast_detail_screen = PodcastDetailScreen(cover_cache=self._cover_cache)
        self._chapter_screen = ChapterSelectScreen(cover_cache=self._cover_cache)

        if self._player:
            self._player_screen = PlayerScreen(self._player, cover_cache=self._cover_cache)
        else:
            self._player_screen = None  # type: ignore[assignment]

        self._stack.addWidget(self._splash_screen)
        self._stack.addWidget(self._login_screen)
        self._stack.addWidget(self._browse_screen)
        self._stack.addWidget(self._detail_screen)
        self._stack.addWidget(self._playlist_detail_screen)
        self._stack.addWidget(self._podcast_detail_screen)
        self._stack.addWidget(self._chapter_screen)

        if self._player_screen:
            self._stack.addWidget(self._player_screen)
            self._player_screen.back_requested.connect(self._on_player_back)
            self._player_screen.next_item.connect(self._on_next_item)
            self._player_screen.prev_item.connect(self._on_prev_item)
            self._player_screen.track_ended.connect(self._on_track_ended)
            self._player_screen.progress_update.connect(self._on_progress_update)

        self._login_screen.login_requested.connect(self._on_login_requested)
        self._login_screen.pairing_login_succeeded.connect(self._on_pairing_login_succeeded)
        self._browse_screen.series_selected.connect(self._on_series_selected)
        self._browse_screen.playlist_selected.connect(self._on_playlist_selected)
        self._browse_screen.book_selected.connect(self._on_browse_book_selected)
        self._browse_screen.library_changed.connect(self._on_browse_library_changed)
        self._browse_screen.see_all_requested.connect(self._on_see_all_requested)
        self._browse_screen.podcast_selected.connect(self._on_podcast_selected)
        self._browse_screen.podcast_episode_selected.connect(self._on_podcast_episode_selected)
        self._browse_screen.exit_requested.connect(self.close)
        self._browse_screen.finish_progress_requested.connect(
            self._on_browse_finish_progress_requested
        )
        self._browse_screen.finished_changed.connect(self._on_progress_update)
        self._detail_screen.episode_activated.connect(self._on_episode_activated)
        self._detail_screen.back_requested.connect(self._show_browse)
        self._detail_screen.finished_changed.connect(self._on_progress_update)
        self._playlist_detail_screen.item_activated.connect(self._on_playlist_item_activated)
        self._playlist_detail_screen.back_requested.connect(self._show_browse)
        self._playlist_detail_screen.finished_changed.connect(self._on_progress_update)
        self._podcast_detail_screen.item_activated.connect(self._on_podcast_episode_activated)
        self._podcast_detail_screen.back_requested.connect(self._show_browse)
        self._podcast_detail_screen.finished_changed.connect(self._on_progress_update)
        self._chapter_screen.play_requested.connect(self._on_play_requested)
        self._chapter_screen.playlist_item_play_requested.connect(self._on_playlist_item_play_requested)
        self._chapter_screen.library_item_play_requested.connect(self._on_browse_item_play_requested)
        self._chapter_screen.podcast_episode_play_requested.connect(self._on_podcast_episode_play_requested_from_chapter)
        self._chapter_screen.back_requested.connect(self._on_chapter_back)
        # Thread the chapter list the user just picked from through to
        # PlayerScreen's in-player chapter overlay. self._chapter_screen
        # still holds the exact chapters that were loaded for this book/item
        # at the moment one of its play_requested-family signals fires, so
        # these connections just forward that list — they don't change
        # _on_play_requested/etc.'s own signature or meaning. Each is
        # connected AFTER the matching _on_*_play_requested connection
        # above, on the same signal — see _forward_chapters_to_player's
        # docstring for why that ordering is load-bearing.
        self._chapter_screen.play_requested.connect(self._forward_chapters_to_player)
        self._chapter_screen.playlist_item_play_requested.connect(self._forward_chapters_to_player)
        self._chapter_screen.library_item_play_requested.connect(self._forward_chapters_to_player)
        self._chapter_screen.podcast_episode_play_requested.connect(self._forward_chapters_to_player)

        self._update_prompt_screen = UpdatePromptScreen()
        self._stack.addWidget(self._update_prompt_screen)
        self._update_prompt_screen.install_requested.connect(self._on_update_install_requested)
        self._update_prompt_screen.later_requested.connect(self._try_autologin)
        self._update_prompt_screen.continue_requested.connect(self._try_autologin)

        self._show_splash()
        self._splash_screen.set_status("Checking for updates…")
        self._worker.run("check_update", fetch_latest_release())

    def _try_autologin(self) -> None:
        server = self._config.active_server
        if server and server.token:
            self._login_screen.set_prefill(server.url, server.username)
            self._do_connect_with_token(server.url, server.token)
        else:
            self._show_login()

    def _on_update_install_requested(self) -> None:
        if self._pending_release is None:
            return
        self._update_prompt_screen.show_installing()
        self._worker.run("apply_update", apply_update(self._pending_release.zipball_url))

    # ------------------------------------------------------------------
    # Screen navigation
    # ------------------------------------------------------------------

    def _show_splash(self) -> None:
        self._stack.setCurrentWidget(self._splash_screen)

    def _show_login(self) -> None:
        self._login_screen.start_pairing()
        self._stack.setCurrentWidget(self._login_screen)

    def _show_browse(self) -> None:
        self._stack.setCurrentWidget(self._browse_screen)

    def _show_detail(self) -> None:
        self._stack.setCurrentWidget(self._detail_screen)

    def _show_playlist_detail(self) -> None:
        self._stack.setCurrentWidget(self._playlist_detail_screen)

    def _show_podcast_detail(self) -> None:
        self._stack.setCurrentWidget(self._podcast_detail_screen)

    def _on_player_back(self) -> None:
        # Invalidate any in-flight "up next" timer — a manual Back
        # supersedes whatever the automatic end-of-track flow had pending.
        # See _on_track_ended/_advance_after_up_next.
        self._up_next_generation += 1
        target = self._player_back_target
        if target == "chapter":
            self._stack.setCurrentWidget(self._chapter_screen)
        elif target == "playlist_detail":
            self._show_playlist_detail()
        elif target == "podcast_detail":
            self._show_podcast_detail()
        elif target == "browse":
            self._show_browse()
        else:
            self._show_detail()

    def _on_chapter_back(self) -> None:
        target = self._chapter_back_target
        if target == "browse":
            self._show_browse()
        elif target == "playlist_detail":
            self._show_playlist_detail()
        elif target == "podcast_detail":
            self._show_podcast_detail()
        else:
            self._show_detail()

    def _forward_chapters_to_player(self, *_args) -> None:
        """Connected AFTER _on_play_requested/_on_browse_item_play_requested/
        _on_playlist_item_play_requested on the same ChapterSelectScreen
        signals — must run second, since those handlers call into
        PlayerScreen's play_* methods, which reset PlayerScreen._chapters
        (via _reset_per_item_state) before this forwards the real value.
        Qt fires directly-connected slots in connection order, so this
        ordering is load-bearing: reversing it would have this forward the
        real chapter list, then have it immediately wiped by the play_*
        handler's reset, silently disabling the in-player chapter overlay.
        """
        if self._player_screen:
            self._player_screen.set_chapters(self._chapter_screen._chapters)

    # ------------------------------------------------------------------
    # Login / auth
    # ------------------------------------------------------------------

    def _set_client(self, client: ABSClient) -> None:
        """Replace self._client -- the session-lifetime ABSClient every
        _async_* method below reuses instead of opening a fresh connection
        per call (see the dedent refactor throughout this file). Closes the
        previous client's connection pool on the worker's event loop, since
        that's the loop its httpx.AsyncClient was actually used from."""
        old = self._client
        self._client = client
        if old is not None:
            self._worker.run("_close_stale_client", old.aclose())

    def _on_login_requested(self, url: str, username: str, password: str) -> None:
        self._server_url = url
        self._set_client(ABSClient(url))
        self._worker.run("login", self._async_login(username, password))

    async def _async_login(self, username: str, password: str):
        async with ABSClient(self._server_url) as client:
            result = await client.login(username, password)
            self._set_client(ABSClient(self._server_url, token=result.user.token))
            return result

    def _on_pairing_login_succeeded(self, url: str, username: str, token: str) -> None:
        self._server_url = url
        self._token = token
        self._set_client(ABSClient(url, token=token))
        self._config.add_or_update_server(
            ServerConfig(
                name=self._server_url,
                url=self._server_url,
                token=self._token,
                username=username,
            )
        )
        self._config.save()
        self._prime_browse_from_cache()
        self._worker.run("libraries", self._async_get_libraries())

    def _do_connect_with_token(self, url: str, token: str) -> None:
        self._server_url = url
        self._token = token
        self._set_client(ABSClient(url, token=token))
        self._prime_browse_from_cache()
        self._worker.run("autologin", self._async_get_libraries())

    def _prime_browse_from_cache(self) -> None:
        """Show cached library/browse content instantly, before the real
        network fetch (kicked off separately, right after this) resolves.
        Stale-while-revalidate: this is a first paint, never the final
        word — the caller always still fetches fresh data afterward.

        Deliberately reads from disk only and never dispatches a network
        request itself — the "libraries"/"autologin" result that follows
        right behind this always does that via
        _populate_browse_from_libraries()/_fetch_browse_content(). Calling
        _fetch_browse_content() from here too would fetch the initial
        library's content over the network twice on every cache-primed
        load, once from this priming pass and once from the real result.
        """
        cached_libraries = self._browse_cache.load_libraries(self._server_url)
        if not cached_libraries:
            return
        self._libraries = cached_libraries
        self._browse_screen.load_libraries(cached_libraries, self._server_url, self._token)
        initial_lib = self._resolve_initial_library(cached_libraries)
        self._current_library = initial_lib
        cached_rows = self._browse_cache.load_browse_content(self._server_url, initial_lib.id)
        if cached_rows:
            for row_type, items in cached_rows.items():
                self._browse_screen.set_row_items(row_type, items)
            self._browse_screen.show_content()
        self._show_browse()

    async def _async_get_libraries(self):
        sem = asyncio.Semaphore(10)

        async def _fetch_stats(client: ABSClient, library_id: str):
            async with sem:
                try:
                    return await client.get_library_stats(library_id)
                except Exception as exc:
                    logger.warning("Library stats fetch failed for %s: %s", library_id, exc)
                    return None

        client = self._client
        libraries = await client.get_libraries()
        stats = await asyncio.gather(*(_fetch_stats(client, lib.id) for lib in libraries))
        return [
            lib
            for lib, s in zip(libraries, stats, strict=True)
            if s is None or s.total_duration > 0 or s.num_audio_tracks > 0
        ]

    # ------------------------------------------------------------------
    # Browse screen
    # ------------------------------------------------------------------

    def _on_browse_library_changed(self, library: Library) -> None:
        self._current_library = library
        server = self._config.active_server
        if server and server.last_library_id != library.id:
            server.last_library_id = library.id
            self._config.save()
        self._fetch_browse_content(library.id)

    def _resolve_initial_library(self, libraries: list[Library]) -> Library:
        server = self._config.active_server
        last_id = server.last_library_id if server else ""
        return next((lib for lib in libraries if lib.id == last_id), None) or libraries[0]

    def _populate_browse_from_libraries(self, libraries: list[Library]) -> None:
        """Populate the sidebar from `libraries` and kick off loading the
        initial (last-viewed, or first) library's content over the
        network. Used for the real network result only — cache-priming
        uses _prime_browse_from_cache() instead, which does not dispatch
        a network fetch (see its docstring for why)."""
        self._libraries = libraries
        self._browse_screen.load_libraries(libraries, self._server_url, self._token)
        initial_lib = self._resolve_initial_library(libraries)
        self._current_library = initial_lib
        self._fetch_browse_content(initial_lib.id)

    def _fetch_browse_content(self, library_id: str) -> None:
        cached = self._browse_cache.load_browse_content(self._server_url, library_id)
        if cached:
            for row_type, items in cached.items():
                self._browse_screen.set_row_items(row_type, items)
            self._browse_screen.show_content()
        self._worker.run("browse_content", self._async_get_browse_content(library_id))

    async def _async_get_browse_content(self, library_id: str) -> tuple:
        client = self._client
        shelves, recent, series_list, all_books, playlists = await asyncio.gather(
            client.get_personalized_shelves(library_id),
            client.get_library_items_recent(library_id, 20),
            client.get_series(library_id),
            client.get_all_library_items(library_id),
            client.get_playlists(library_id),
        )
        continue_listening: list = []
        for shelf in shelves:
            if "continue" in shelf.label.lower():
                continue_listening = shelf.entities[:20]
                break
        all_books.sort(key=_author_surname_sort_key)
        rows = {
            RowType.CONTINUE_LISTENING: continue_listening,
            RowType.RECENTLY_ADDED: recent[:20],
            RowType.SERIES: series_list[:20],
            RowType.ALL_BOOKS: all_books[:20],
            RowType.PLAYLISTS: playlists[:20],
        }
        return library_id, rows

    def _on_see_all_requested(self, row_type: RowType) -> None:
        lib = getattr(self, "_current_library", None)
        if not lib:
            return
        self._worker.run("see_all", self._async_get_see_all(row_type, lib.id))

    async def _async_get_see_all(self, row_type: RowType, library_id: str) -> tuple:
        client = self._client
        if row_type == RowType.CONTINUE_LISTENING:
            shelves = await client.get_personalized_shelves(library_id)
            items = []
            for shelf in shelves:
                if "continue" in shelf.label.lower():
                    items = shelf.entities
                    break
        elif row_type == RowType.RECENTLY_ADDED:
            items = await client.get_library_items_recent(library_id, limit=100)
        elif row_type == RowType.SERIES:
            items = await client.get_series(library_id, limit=500)
        elif row_type == RowType.ALL_BOOKS:
            items = await client.get_all_library_items(library_id)
            items.sort(key=_author_surname_sort_key)
        else:  # PLAYLISTS
            items = await client.get_playlists(library_id)
        return row_type, items

    def _on_browse_book_selected(self, item: LibraryItem) -> None:
        self._pending_browse_item = item
        self._chapter_back_target = "browse"
        self._player_back_target = "browse"
        self._worker.run("browse_book", self._async_get_browse_book(item.id))

    async def _async_get_browse_book(self, item_id: str):
        client = self._client
        full_item, progress = await asyncio.gather(
            client.get_library_item(item_id),
            client.get_progress(item_id),
        )
        return full_item, progress

    def _on_browse_item_play_requested(self, item: LibraryItem, start_time: float) -> None:
        if not self._player or not self._player_screen:
            return
        self._player_screen.play_library_item(item, start_time, self._server_url, self._token)
        self._worker.run("start_session", self._async_start_session(item.id, start_time))
        self._stack.setCurrentWidget(self._player_screen)
        self._player_screen.setFocus()

    # ------------------------------------------------------------------
    # Library / series / detail flow
    # ------------------------------------------------------------------

    def _on_series_selected(self, series: Series) -> None:
        self._current_series = series
        logger.debug("Series selected: %s (%d books)", series.name, series.book_count)
        self._detail_screen.show_loading(series, self._server_url, self._token)
        self._show_detail()
        self._worker.run("series_detail", self._async_fetch_series_progress(series))

    async def _async_fetch_series_progress(self, series: Series):
        sem = asyncio.Semaphore(10)

        async def _fetch_one(client: ABSClient, book_id: str) -> tuple[str, MediaProgress | None]:
            async with sem:
                try:
                    return book_id, await client.get_progress(book_id)
                except Exception as exc:
                    logger.warning("Progress fetch failed for %s: %s", book_id, exc)
                    return book_id, None

        client = self._client
        pairs = await asyncio.gather(
            *(_fetch_one(client, book.id) for book in series.sorted_books)
        )
        return (series, dict(pairs))

    # ------------------------------------------------------------------
    # Playlists
    # ------------------------------------------------------------------

    def _on_playlist_selected(self, playlist: Playlist) -> None:
        self._current_playlist = playlist
        logger.debug("Playlist selected: %s (%d items)", playlist.name, playlist.item_count)
        self._playlist_detail_screen.show_loading(playlist, self._server_url, self._token)
        self._show_playlist_detail()
        self._worker.run("playlist_detail", self._async_fetch_playlist_progress(playlist))

    async def _async_fetch_playlist_progress(self, playlist: Playlist):
        sem = asyncio.Semaphore(10)

        async def _fetch_one(client: ABSClient, item_id: str) -> tuple[str, MediaProgress | None]:
            async with sem:
                try:
                    return item_id, await client.get_progress(item_id)
                except Exception as exc:
                    logger.warning("Progress fetch failed for %s: %s", item_id, exc)
                    return item_id, None

        client = self._client
        pairs = await asyncio.gather(
            *(_fetch_one(client, item.library_item_id) for item in playlist.items)
        )
        return (playlist, dict(pairs))

    def _on_playlist_item_activated(self, item: PlaylistItem) -> None:
        self._pending_playlist_item = item
        self._chapter_back_target = "playlist_detail"
        self._player_back_target = "playlist_detail"
        self._worker.run(
            "playlist_item_chapters", self._async_get_book_chapters(item.library_item_id)
        )

    def _on_playlist_item_play_requested(self, item: PlaylistItem, start_time: float) -> None:
        if not self._player or not self._player_screen:
            return
        self._current_playlist_item = item
        self._current_start_time = start_time
        playlist = self._current_playlist
        if playlist is None:
            return
        # Convert playlist items to a format the player can use
        # We'll create a simple series-like structure for the player
        self._player_screen.play_playlist_item(
            item, start_time, playlist, playlist.items,
            self._server_url, self._token,
        )
        self._worker.run(
            "start_session", self._async_start_session(item.library_item_id, start_time)
        )
        self._stack.setCurrentWidget(self._player_screen)
        self._player_screen.setFocus()

    # ------------------------------------------------------------------
    # Podcasts
    # ------------------------------------------------------------------

    def _on_podcast_selected(self, show: LibraryItem) -> None:
        # `show` here is the lightweight item BrowseScreen's rows carry (from
        # get_library_items_recent()/personalized shelves' non-continue
        # entities), which does NOT include media.episodes — same asymmetry
        # as SeriesBook (no chapters) and PlaylistItem (no chapters), both of
        # which app.py already re-fetches the full item for before showing
        # chapter-level detail (see _on_episode_activated/
        # _async_get_book_chapters, _on_browse_book_selected/
        # _async_get_browse_book). show_loading() is called with the
        # lightweight item purely for an instant title/cover-only loading
        # state; the real episode grid is populated once the full item
        # fetch below resolves.
        self._current_podcast_show = show
        self._podcast_detail_screen.show_loading(show, self._server_url, self._token)
        self._show_podcast_detail()
        self._worker.run("podcast_detail", self._async_fetch_podcast_detail(show))

    async def _async_fetch_podcast_detail(self, show: LibraryItem):
        sem = asyncio.Semaphore(10)

        async def _fetch_one(
            client: ABSClient, item_id: str, episode_id: str
        ) -> tuple[str, MediaProgress | None]:
            async with sem:
                try:
                    return episode_id, await client.get_progress(item_id, episode_id)
                except Exception as exc:
                    logger.warning("Progress fetch failed for %s/%s: %s", item_id, episode_id, exc)
                    return episode_id, None

        # One client shared by both the item-detail fetch and the
        # per-episode progress fan-out — matches _async_get_browse_book's
        # equivalent pattern for books.
        client = self._client
        full_show = await client.get_library_item(show.id)
        pairs = await asyncio.gather(
            *(_fetch_one(client, full_show.id, ep.id) for ep in full_show.media.episodes)
        )
        return full_show, dict(pairs)

    def _on_podcast_episode_activated(self, episode: PodcastEpisode) -> None:
        self._pending_podcast_episode = episode
        self._chapter_back_target = "podcast_detail"
        self._player_back_target = "podcast_detail"
        prog = self._podcast_detail_screen._progress.get(episode.id)
        start_time = prog.current_time if prog and not prog.is_finished else 0.0
        if len(episode.chapters) > 1:
            self._player_back_target = "chapter"
            self._chapter_screen.load_from_podcast_episode(
                self._current_podcast_show, episode, episode.chapters, prog,
                self._server_url, self._token,
            )
            self._stack.setCurrentWidget(self._chapter_screen)
        else:
            self._on_podcast_episode_play_requested(episode, start_time)
            if self._player_screen:
                self._player_screen.set_chapters(episode.chapters)

    def _on_podcast_episode_play_requested_from_chapter(
        self, show: LibraryItem, episode: PodcastEpisode, start_time: float
    ) -> None:
        self._current_podcast_show = show
        self._on_podcast_episode_play_requested(episode, start_time)

    def _on_podcast_episode_play_requested(
        self, episode: PodcastEpisode, start_time: float
    ) -> None:
        if not self._player or not self._player_screen:
            return
        show = self._current_podcast_show
        if show is None:
            return
        self._pending_podcast_episode = episode
        self._player_screen.play_podcast_episode(
            episode, show, start_time, self._server_url, self._token
        )
        # Prefer the episode's own library_item_id over self._current_podcast_show.id —
        # the episode is self-contained data, not mutable instance state
        # that can have drifted since this play request was queued.
        self._worker.run(
            "start_session",
            self._async_start_session(
                episode.library_item_id or show.id, start_time, episode_id=episode.id
            ),
        )
        self._stack.setCurrentWidget(self._player_screen)
        self._player_screen.setFocus()

    def _on_podcast_episode_selected(self, show: LibraryItem, episode: PodcastEpisode) -> None:
        self._current_podcast_show = show
        self._pending_podcast_episode = episode
        self._chapter_back_target = "browse"
        self._player_back_target = "browse"
        self._worker.run(
            "podcast_continue_progress",
            self._async_get_podcast_progress(show, episode),
        )

    async def _async_get_podcast_progress(
        self, show: LibraryItem, episode: PodcastEpisode
    ) -> tuple[LibraryItem, PodcastEpisode, MediaProgress | None]:
        # Returns (show, episode, progress) as one self-contained tuple —
        # not just the progress — so the "podcast_continue_progress" result
        # handler in _on_result never needs to re-read self._current_podcast_show/
        # self._pending_podcast_episode (mutable instance state that can
        # have changed while this fetch was in flight, e.g. the user
        # navigated to a different podcast show) to know which show/episode
        # this result belongs to.
        client = self._client
        progress = await client.get_progress(show.id, episode.id)
        return show, episode, progress

    def _on_browse_finish_progress_requested(self, item: LibraryItem) -> None:
        self._worker.run("browse_finish_progress", self._async_get_browse_item_progress(item))

    async def _async_get_browse_item_progress(
        self, item: LibraryItem
    ) -> tuple[LibraryItem, MediaProgress | None]:
        # (item, progress) as a self-contained tuple, same reasoning as
        # _async_get_podcast_progress above — BrowseScreen re-checks the
        # item is still the one it's waiting on itself (see
        # show_finish_confirm's docstring) rather than this handler
        # guessing at still-current UI state.
        client = self._client
        episode_id = item.recent_episode.id if item.recent_episode else None
        progress = await client.get_progress(item.id, episode_id)
        return item, progress

    # ------------------------------------------------------------------
    # Chapter selection
    # ------------------------------------------------------------------

    def _on_episode_activated(self, book: SeriesBook) -> None:
        self._pending_book = book
        self._chapter_back_target = "detail"
        self._player_back_target = "chapter"
        self._worker.run("book_chapters", self._async_get_book_chapters(book.id))

    async def _async_get_book_chapters(self, book_id: str):
        client = self._client
        return await client.get_library_item(book_id)

    # ------------------------------------------------------------------
    # Playback
    # ------------------------------------------------------------------

    def _on_play_requested(self, book: SeriesBook, start_time: float) -> None:
        if not self._player or not self._player_screen:
            return
        self._current_book = book
        self._current_start_time = start_time
        series = self._current_series
        if series is None:
            return
        self._player_screen.play_book(
            book, start_time, series, series.sorted_books,
            self._server_url, self._token,
        )
        self._worker.run("start_session", self._async_start_session(book.id, start_time))
        self._stack.setCurrentWidget(self._player_screen)
        self._player_screen.setFocus()

    async def _async_start_session(
        self, item_id: str, start_time: float, episode_id: str | None = None
    ):
        client = self._client
        return await client.start_playback_session(item_id, start_time, episode_id=episode_id)

    def _on_next_item(self) -> None:
        # Invalidate any in-flight "up next" timer and hide its label — a
        # manual skip supersedes whatever the automatic end-of-track flow
        # had pending. See _on_track_ended/_advance_after_up_next.
        self._up_next_generation += 1
        if self._player_screen:
            self._player_screen.hide_up_next()
        if self._current_series is None:
            return
        books = self._current_series.sorted_books
        idx = self._player_screen._current_index if self._player_screen else 0
        next_idx = idx + 1
        if next_idx < len(books):
            self._on_play_requested(books[next_idx], 0.0)

    def _on_prev_item(self) -> None:
        # See _on_next_item — same invalidation for manual skip-back.
        self._up_next_generation += 1
        if self._player_screen:
            self._player_screen.hide_up_next()
        if self._current_series is None:
            return
        books = self._current_series.sorted_books
        idx = self._player_screen._current_index if self._player_screen else 0
        prev_idx = idx - 1
        if prev_idx >= 0:
            self._on_play_requested(books[prev_idx], 0.0)

    def _on_track_ended(self) -> None:
        """Automatic end-of-track: do NOT auto-play. Show an up-next
        message, then navigate to the relevant grid with the next item
        pre-focused (or Browse if there's no series/playlist context)."""
        book = self._player_screen._current_book
        books = self._player_screen._series_books
        playlist_item = self._player_screen._current_playlist_item
        playlist_items = self._player_screen._playlist_items
        episode_id = self._player_screen._episode_id

        if book is not None and books:
            idx = books.index(book) if book in books else -1
            if 0 <= idx < len(books) - 1:
                target = ("series", books[idx + 1].id)
                message = f"Up next: {books[idx + 1].title}"
            else:
                target = ("series", None)
                message = "End of series"
        elif playlist_item is not None and playlist_items:
            idx = playlist_items.index(playlist_item) if playlist_item in playlist_items else -1
            if 0 <= idx < len(playlist_items) - 1:
                target = ("playlist", playlist_items[idx + 1].library_item_id)
                message = f"Up next: {playlist_items[idx + 1].title}"
            else:
                target = ("playlist", None)
                message = "End of playlist"
        elif episode_id:
            # Single-episode playback (spec: no next/prev-episode
            # navigation or auto-advance) — always return to the episode
            # list, with the just-finished episode re-focused. No "up
            # next" message, since there's never a next episode to name.
            target = ("podcast", episode_id)
            message = ""
        else:
            target = ("browse", None)
            message = ""

        if message:
            self._player_screen.show_up_next(message)
        # Capture and invalidate the current generation, so this scheduled
        # call owns exactly this generation. Any manual action that races
        # this delay (_on_next_item/_on_prev_item/_on_player_back) bumps
        # self._up_next_generation again, which makes the check in
        # _advance_after_up_next below a no-op for this now-stale timer.
        self._up_next_generation += 1
        generation = self._up_next_generation
        QTimer.singleShot(
            self._UP_NEXT_DELAY_MS,
            lambda: self._advance_after_up_next(target, generation),
        )

    def _advance_after_up_next(self, target: tuple[str, str | None], generation: int) -> None:
        if generation != self._up_next_generation:
            return  # a newer action (manual skip, back, another track ending) superseded this one
        self._player_screen.hide_up_next()
        kind, key = target
        if kind == "series":
            self._show_detail()
            if key is not None:
                self._detail_screen.focus_item_by_key(key)
        elif kind == "playlist":
            self._show_playlist_detail()
            if key is not None:
                self._playlist_detail_screen.focus_item_by_key(key)
        elif kind == "podcast":
            self._show_podcast_detail()
            if key is not None:
                self._podcast_detail_screen.focus_item_by_key(key)
        else:
            self._show_browse()

    @pyqtSlot(str, float, float, bool, str)
    def _on_progress_update(
        self,
        item_id: str,
        current_time: float,
        duration: float,
        is_finished: bool,
        episode_id: str,
    ) -> None:
        self._worker.run(
            "progress",
            self._async_update_progress(
                item_id, current_time, duration, is_finished, episode_id or None
            ),
        )

    async def _async_update_progress(
        self, item_id: str, current_time: float, duration: float, is_finished: bool,
        episode_id: str | None = None,
    ):
        client = self._client
        await client.update_progress(
            item_id, current_time, duration, is_finished, episode_id=episode_id
        )

    # ------------------------------------------------------------------
    # Async result handling
    # ------------------------------------------------------------------

    @pyqtSlot(str, object)
    def _on_result(self, tag: str, result: Any) -> None:
        if tag == "login":
            self._token = result.user.token
            self._config.add_or_update_server(
                ServerConfig(
                    name=self._server_url,
                    url=self._server_url,
                    token=self._token,
                    username=result.user.username,
                )
            )
            self._config.save()
            self._worker.run("libraries", self._async_get_libraries())

        elif tag in ("libraries", "autologin"):
            self._login_screen.stop_pairing()
            if not result:
                self._libraries = result
                self._show_browse()
                return
            self._browse_cache.save_libraries(self._server_url, result)
            self._populate_browse_from_libraries(result)
            self._show_browse()

        elif tag == "browse_content":
            result_lib_id, rows = result
            current_lib = getattr(self, "_current_library", None)
            if current_lib and result_lib_id != current_lib.id:
                return  # stale result from a previously selected library
            self._browse_cache.save_browse_content(self._server_url, result_lib_id, rows)
            for row_type, items in rows.items():
                self._browse_screen.set_row_items(row_type, items)
            self._browse_screen.show_content()

        elif tag == "see_all":
            row_type, items = result
            self._browse_screen.populate_grid(items)

        elif tag == "browse_book":
            full_item, progress = result
            item = self._pending_browse_item
            if item is None:
                return
            chapters = full_item.media.chapters
            if len(chapters) > 1:
                self._player_back_target = "chapter"
                self._chapter_screen.load_from_library_item(
                    item, chapters, progress, self._server_url, self._token
                )
                self._stack.setCurrentWidget(self._chapter_screen)
            else:
                start_time = progress.current_time if progress and not progress.is_finished else 0.0
                self._player_back_target = "browse"
                self._on_browse_item_play_requested(item, start_time)
                if self._player_screen:
                    self._player_screen.set_chapters(chapters)

        elif tag == "playlist_detail":
            playlist, progress_map = result
            logger.debug(
                "Playlist detail loaded: %s (%d items)", playlist.name, playlist.item_count
            )
            if self._current_playlist and playlist.id == self._current_playlist.id:
                clean_progress = {k: v for k, v in progress_map.items() if v is not None}
                self._playlist_detail_screen.update_progress(clean_progress)

        elif tag == "series_detail":
            series, progress_map = result
            logger.debug("Series detail loaded: %s (%d books)", series.name, series.book_count)
            if self._current_series and series.id == self._current_series.id:
                clean_progress = {k: v for k, v in progress_map.items() if v is not None}
                self._detail_screen.update_progress(clean_progress)

        elif tag == "book_chapters":
            library_item = result
            book = self._pending_book
            if book is None:
                return
            chapters = library_item.media.chapters
            if len(chapters) > 1:
                prog = self._detail_screen._progress.get(book.id)
                self._chapter_screen.load(book, chapters, prog, self._server_url, self._token)
                self._stack.setCurrentWidget(self._chapter_screen)
            else:
                prog = self._detail_screen._progress.get(book.id)
                start_time = prog.current_time if prog and not prog.is_finished else 0.0
                self._player_back_target = "detail"
                self._on_play_requested(book, start_time)
                if self._player_screen:
                    self._player_screen.set_chapters(chapters)

        elif tag == "playlist_item_chapters":
            library_item = result
            item = self._pending_playlist_item
            if item is None:
                return
            chapters = library_item.media.chapters
            if len(chapters) > 1:
                self._player_back_target = "chapter"
                prog = self._playlist_detail_screen._progress.get(item.library_item_id)
                self._chapter_screen.load_from_playlist_item(
                    item, chapters, prog, self._server_url, self._token
                )
                self._stack.setCurrentWidget(self._chapter_screen)
            else:
                prog = self._playlist_detail_screen._progress.get(item.library_item_id)
                start_time = prog.current_time if prog and not prog.is_finished else 0.0
                self._player_back_target = "playlist_detail"
                self._on_playlist_item_play_requested(item, start_time)
                if self._player_screen:
                    self._player_screen.set_chapters(chapters)

        elif tag == "podcast_detail":
            full_show, progress = result
            if self._current_podcast_show and full_show.id == self._current_podcast_show.id:
                self._current_podcast_show = full_show
                self._podcast_detail_screen.load(full_show, progress, self._server_url, self._token)

        elif tag == "podcast_continue_progress":
            # result is a self-contained (show, episode, progress) tuple —
            # see _async_get_podcast_progress's docstring for why this
            # branch never reads self._current_podcast_show/
            # self._pending_podcast_episode to pair them.
            show, episode, progress = result
            if show is None:
                return
            self._current_podcast_show = show
            self._pending_podcast_episode = episode
            if len(episode.chapters) > 1:
                self._player_back_target = "chapter"
                self._chapter_screen.load_from_podcast_episode(
                    show, episode, episode.chapters, progress,
                    self._server_url, self._token,
                )
                self._stack.setCurrentWidget(self._chapter_screen)
            else:
                start_time = progress.current_time if progress and not progress.is_finished else 0.0
                self._on_podcast_episode_play_requested(episode, start_time)
                if self._player_screen:
                    self._player_screen.set_chapters(episode.chapters)

        elif tag == "browse_finish_progress":
            item, progress = result
            self._browse_screen.show_finish_confirm(item, progress)

        elif tag == "start_session":
            # result is a PlaybackSession — build URL and start playback.
            # playback_url() concatenates every track into one mpv EDL for
            # multi-file items (see its docstring) — loading only
            # audio_tracks[0] here would overshoot that one file's own
            # duration as soon as a later chapter's absolute start time is
            # sought into it, firing a spurious end-of-track.
            session = result
            if session.audio_tracks and self._player_screen:
                url = session.playback_url(self._server_url)
                self._player_screen.set_audio_tracks(url, session.current_time, self._token)

        elif tag == "progress":
            pass  # fire-and-forget

        elif tag == "check_update":
            release = result
            if release is not None and is_newer(release.version, CURRENT_VERSION):
                self._pending_release = release
                self._update_prompt_screen.show_prompt(CURRENT_VERSION, release.version)
                self._stack.setCurrentWidget(self._update_prompt_screen)
            else:
                self._try_autologin()

        elif tag == "apply_update":
            try:
                relaunch()
            except UpdateError as exc:
                logger.error("Relaunch failed, staying on current version: %s", exc)
                return
            QApplication.instance().quit()

    @pyqtSlot(str, str)
    def _on_error(self, tag: str, message: str) -> None:
        logger.error("Async error [%s]: %s", tag, message)
        if tag == "login":
            self._login_screen.show_error(f"Login failed: {message}")
        elif tag == "autologin":
            self._show_login()
        elif tag == "libraries":
            # Order is load-bearing: _show_login() calls start_pairing(),
            # which (re)shows the pairing view and issues a fresh code —
            # if show_error() ran first, that would immediately clobber
            # the error's visibility by re-hiding the keyboard-fallback
            # view it just forced open. Showing the login screen (with a
            # fresh pairing code, since the old one was already consumed)
            # BEFORE show_error() lets show_error()'s own visibility fix
            # (Fix 3 Part A) be the last word, so the error is what the
            # user actually sees.
            self._login_screen.stop_pairing()
            self._show_login()
            self._login_screen.show_error(f"Couldn't load your libraries: {message}")
        elif tag == "book_chapters":
            book = self._pending_book
            if book:
                prog = self._detail_screen._progress.get(book.id)
                start_time = prog.current_time if prog and not prog.is_finished else 0.0
                self._on_play_requested(book, start_time)
        elif tag == "playlist_item_chapters":
            item = self._pending_playlist_item
            if item:
                prog = self._playlist_detail_screen._progress.get(item.library_item_id)
                start_time = prog.current_time if prog and not prog.is_finished else 0.0
                self._on_playlist_item_play_requested(item, start_time)
        elif tag == "series_detail":
            if self._current_series:
                self._detail_screen.update_progress({})
        elif tag == "playlist_detail":
            if self._current_playlist:
                self._playlist_detail_screen.update_progress({})
        elif tag == "podcast_detail":
            # Unlike series_detail/playlist_detail (whose detail screens
            # already show real, cover-fetched items instantly from the
            # browse row, so a progress-only fetch failure just means
            # missing progress bars), "podcast_detail" is also the ONLY
            # fetch that ever populates real episodes into the grid — the
            # browse-row item show_loading() used has none (see Task 6's
            # note in _on_podcast_selected). A failure here means the grid
            # will stay empty forever, so don't leave the user stranded on
            # it — bounce back to Browse instead.
            self._show_browse()
        elif tag == "check_update":
            # fetch_latest_release() fails soft internally and should
            # never actually raise -- this is a defensive backstop, not
            # an expected path.
            self._try_autologin()
        elif tag == "apply_update":
            self._update_prompt_screen.show_error(message)
            self._stack.setCurrentWidget(self._update_prompt_screen)

    # ------------------------------------------------------------------
    # Quit
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Cursor auto-hide (remote-control / 10-foot UX)
    # ------------------------------------------------------------------

    _CURSOR_HIDE_MS = 2000  # hide after 2 s of mouse inactivity

    def _setup_cursor_autohide(self) -> None:
        self._cursor_hidden = False
        self._cursor_timer = QTimer(self)
        self._cursor_timer.setSingleShot(True)
        self._cursor_timer.timeout.connect(self._hide_cursor)
        QApplication.instance().installEventFilter(self)  # type: ignore[union-attr]

    def _hide_cursor(self) -> None:
        if not self._cursor_hidden:
            QApplication.setOverrideCursor(Qt.CursorShape.BlankCursor)
            self._cursor_hidden = True

    def _show_cursor(self) -> None:
        if self._cursor_hidden:
            QApplication.restoreOverrideCursor()
            self._cursor_hidden = False
        self._cursor_timer.start(self._CURSOR_HIDE_MS)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.MouseMove:
            self._show_cursor()
        elif event.type() == QEvent.Type.KeyPress:
            # Any key press hides the cursor immediately
            if not self._cursor_hidden:
                QApplication.setOverrideCursor(Qt.CursorShape.BlankCursor)
                self._cursor_hidden = True
            self._cursor_timer.stop()
        return super().eventFilter(obj, event)


    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        self._login_screen.stop_pairing()
        self._gamepad.stop()
        if self._player:
            self._player.shutdown()
        self._worker.stop_loop()
        self._thread.quit()
        self._thread.wait(2000)
        super().closeEvent(event)
