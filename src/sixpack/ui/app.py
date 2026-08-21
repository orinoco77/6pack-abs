"""Main application window with screen navigation stack."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from PyQt6.QtCore import QEvent, QObject, QThread, QTimer, pyqtSignal, pyqtSlot, Qt
from PyQt6.QtGui import QCursor, QKeyEvent, QKeySequence, QShortcut
from PyQt6.QtWidgets import QMainWindow, QStackedWidget, QApplication

from sixpack.api.client import ABSClient, AuthenticationError, APIError
from sixpack.api.models import Library, LibraryItem, Series, SeriesBook, MediaProgress, Playlist, PlaylistItem
from sixpack.config import AppConfig, ServerConfig
from sixpack.player.player import AudioPlayer, PlayerError
from sixpack.ui import theme
from sixpack.ui.cover_cache import CoverCache
from sixpack.ui.screens.browse import BrowseScreen, RowType
from sixpack.ui.screens.login import LoginScreen
from sixpack.ui.screens.playlist_detail import PlaylistDetailScreen
from sixpack.ui.screens.chapter_select import ChapterSelectScreen
from sixpack.ui.screens.series_detail import SeriesDetailScreen
from sixpack.ui.screens.player import PlayerScreen
from sixpack.ui.screens.splash import SplashScreen

logger = logging.getLogger(__name__)


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
            self.error.emit(tag, str(exc))


class MainWindow(QMainWindow):
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
        self._libraries: list[Library] = []
        # Back-navigation context: "detail" | "browse" | "playlist_detail"
        self._chapter_back_target = "detail"
        # Back-navigation context: "detail" | "chapter" | "browse" | "playlist_detail"
        self._player_back_target = "detail"

        self._init_player()
        self._init_worker()
        self._build_ui()
        self._try_autologin()

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

    def _build_ui(self) -> None:
        self.setWindowTitle("SixPack — Audiobookshelf")
        self.showFullScreen()
        self._setup_cursor_autohide()

        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        self._cover_cache = CoverCache(parent=self)

        self._splash_screen = SplashScreen()
        self._login_screen = LoginScreen()
        self._browse_screen = BrowseScreen(cover_cache=self._cover_cache)
        self._detail_screen = SeriesDetailScreen(cover_cache=self._cover_cache)
        self._playlist_detail_screen = PlaylistDetailScreen(cover_cache=self._cover_cache)
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
        self._stack.addWidget(self._chapter_screen)

        if self._player_screen:
            self._stack.addWidget(self._player_screen)
            self._player_screen.back_requested.connect(self._on_player_back)
            self._player_screen.next_item.connect(self._on_next_item)
            self._player_screen.prev_item.connect(self._on_prev_item)
            self._player_screen.progress_update.connect(self._on_progress_update)

        self._login_screen.login_requested.connect(self._on_login_requested)
        self._browse_screen.series_selected.connect(self._on_series_selected)
        self._browse_screen.playlist_selected.connect(self._on_playlist_selected)
        self._browse_screen.book_selected.connect(self._on_browse_book_selected)
        self._browse_screen.library_changed.connect(self._on_browse_library_changed)
        self._browse_screen.see_all_requested.connect(self._on_see_all_requested)
        self._detail_screen.play_requested.connect(self._on_detail_play_requested)
        self._detail_screen.episode_activated.connect(self._on_episode_activated)
        self._detail_screen.back_requested.connect(self._show_browse)
        self._playlist_detail_screen.play_requested.connect(self._on_playlist_item_play_requested)
        self._playlist_detail_screen.item_activated.connect(self._on_playlist_item_activated)
        self._playlist_detail_screen.back_requested.connect(self._show_browse)
        self._chapter_screen.play_requested.connect(self._on_play_requested)
        self._chapter_screen.playlist_item_play_requested.connect(self._on_playlist_item_play_requested)
        self._chapter_screen.library_item_play_requested.connect(self._on_browse_item_play_requested)
        self._chapter_screen.back_requested.connect(self._on_chapter_back)

        self._setup_quit_shortcut()
        self._show_splash()

    def _try_autologin(self) -> None:
        server = self._config.active_server
        if server and server.token:
            self._login_screen.set_prefill(server.url, server.username)
            self._do_connect_with_token(server.url, server.token)
        else:
            self._show_login()

    # ------------------------------------------------------------------
    # Screen navigation
    # ------------------------------------------------------------------

    def _show_splash(self) -> None:
        self._stack.setCurrentWidget(self._splash_screen)

    def _show_login(self) -> None:
        self._stack.setCurrentWidget(self._login_screen)

    def _show_browse(self) -> None:
        self._stack.setCurrentWidget(self._browse_screen)

    def _show_detail(self) -> None:
        self._stack.setCurrentWidget(self._detail_screen)

    def _show_playlist_detail(self) -> None:
        self._stack.setCurrentWidget(self._playlist_detail_screen)

    def _on_player_back(self) -> None:
        target = self._player_back_target
        if target == "chapter":
            self._stack.setCurrentWidget(self._chapter_screen)
        elif target == "playlist_detail":
            self._show_playlist_detail()
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
        else:
            self._show_detail()

    # ------------------------------------------------------------------
    # Login / auth
    # ------------------------------------------------------------------

    def _on_login_requested(self, url: str, username: str, password: str) -> None:
        self._server_url = url
        self._client = ABSClient(url)
        self._worker.run("login", self._async_login(username, password))

    async def _async_login(self, username: str, password: str):
        async with ABSClient(self._server_url) as client:
            result = await client.login(username, password)
            self._client = ABSClient(self._server_url, token=result.user.token)
            return result

    def _do_connect_with_token(self, url: str, token: str) -> None:
        self._server_url = url
        self._token = token
        self._client = ABSClient(url, token=token)
        self._worker.run("autologin", self._async_get_libraries())

    async def _async_get_libraries(self):
        async with ABSClient(self._server_url, token=self._token) as client:
            return await client.get_libraries()

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

    def _fetch_browse_content(self, library_id: str) -> None:
        self._worker.run("browse_content", self._async_get_browse_content(library_id))

    async def _async_get_browse_content(self, library_id: str) -> tuple:
        async with ABSClient(self._server_url, token=self._token) as client:
            shelves, recent, series_list, playlists = await asyncio.gather(
                client.get_personalized_shelves(library_id),
                client.get_library_items_recent(library_id, 20),
                client.get_series(library_id),
                client.get_playlists(library_id),
            )
        continue_listening: list = []
        for shelf in shelves:
            if "continue" in shelf.label.lower():
                continue_listening = shelf.entities[:20]
                break
        rows = {
            RowType.CONTINUE_LISTENING: continue_listening,
            RowType.RECENTLY_ADDED: recent[:20],
            RowType.SERIES: series_list[:20],
            RowType.PLAYLISTS: playlists[:20],
        }
        return library_id, rows

    def _on_see_all_requested(self, row_type: RowType) -> None:
        lib = getattr(self, "_current_library", None)
        if not lib:
            return
        self._worker.run("see_all", self._async_get_see_all(row_type, lib.id))

    async def _async_get_see_all(self, row_type: RowType, library_id: str) -> tuple:
        async with ABSClient(self._server_url, token=self._token) as client:
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
            else:  # PLAYLISTS
                items = await client.get_playlists(library_id)
        return row_type, items

    def _on_browse_book_selected(self, item: LibraryItem) -> None:
        self._pending_browse_item = item
        self._chapter_back_target = "browse"
        self._player_back_target = "browse"
        self._worker.run("browse_book", self._async_get_browse_book(item.id))

    async def _async_get_browse_book(self, item_id: str):
        async with ABSClient(self._server_url, token=self._token) as client:
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

    async def _async_get_series(self, library_id: str):
        async with ABSClient(self._server_url, token=self._token) as client:
            return await client.get_series(library_id)

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

        async with ABSClient(self._server_url, token=self._token) as client:
            pairs = await asyncio.gather(
                *(_fetch_one(client, book.id) for book in series.sorted_books)
            )
        return (series, dict(pairs))

    # ------------------------------------------------------------------
    # Playlists
    # ------------------------------------------------------------------

    async def _async_get_playlists(self, library_id: str | None):
        async with ABSClient(self._server_url, token=self._token) as client:
            return await client.get_playlists(library_id)

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

        async with ABSClient(self._server_url, token=self._token) as client:
            pairs = await asyncio.gather(
                *(_fetch_one(client, item.library_item_id) for item in playlist.items)
            )
        return (playlist, dict(pairs))

    def _on_playlist_item_activated(self, item: PlaylistItem) -> None:
        self._pending_playlist_item = item
        self._chapter_back_target = "playlist_detail"
        self._player_back_target = "chapter"
        self._worker.run("playlist_item_chapters", self._async_get_book_chapters(item.library_item_id))

    def _on_playlist_item_play_requested(self, item: PlaylistItem, start_time: float) -> None:
        if not self._player or not self._player_screen:
            return
        self._player_back_target = "chapter" if self._chapter_back_target == "playlist_detail" else "playlist_detail"
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
        self._worker.run("start_session", self._async_start_session(item.library_item_id, start_time))
        self._stack.setCurrentWidget(self._player_screen)
        self._player_screen.setFocus()

    # ------------------------------------------------------------------
    # Chapter selection
    # ------------------------------------------------------------------

    def _on_episode_activated(self, book: SeriesBook) -> None:
        self._pending_book = book
        self._chapter_back_target = "detail"
        self._player_back_target = "chapter"
        self._worker.run("book_chapters", self._async_get_book_chapters(book.id))

    async def _async_get_book_chapters(self, book_id: str):
        async with ABSClient(self._server_url, token=self._token) as client:
            return await client.get_library_item(book_id)

    # ------------------------------------------------------------------
    # Playback
    # ------------------------------------------------------------------

    def _on_detail_play_requested(self, book: SeriesBook, start_time: float) -> None:
        """Direct play from SeriesDetailScreen (no chapter select involved)."""
        self._player_back_target = "detail"
        self._on_play_requested(book, start_time)

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

    async def _async_start_session(self, item_id: str, start_time: float):
        async with ABSClient(self._server_url, token=self._token) as client:
            return await client.start_playback_session(item_id, start_time)

    def _on_next_item(self) -> None:
        if self._current_series is None:
            return
        books = self._current_series.sorted_books
        idx = self._player_screen._current_index if self._player_screen else 0
        next_idx = idx + 1
        if next_idx < len(books):
            self._on_play_requested(books[next_idx], 0.0)

    def _on_prev_item(self) -> None:
        if self._current_series is None:
            return
        books = self._current_series.sorted_books
        idx = self._player_screen._current_index if self._player_screen else 0
        prev_idx = idx - 1
        if prev_idx >= 0:
            self._on_play_requested(books[prev_idx], 0.0)

    @pyqtSlot(str, float, float, bool)
    def _on_progress_update(self, item_id: str, current_time: float, duration: float, is_finished: bool) -> None:
        self._worker.run(
            "progress",
            self._async_update_progress(item_id, current_time, duration, is_finished),
        )

    async def _async_update_progress(self, item_id: str, current_time: float, duration: float, is_finished: bool):
        async with ABSClient(self._server_url, token=self._token) as client:
            await client.update_progress(item_id, current_time, duration, is_finished)

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
            self._libraries = result
            if not result:
                self._show_browse()
                return
            self._browse_screen.load_libraries(result, self._server_url, self._token)
            server = self._config.active_server
            last_id = server.last_library_id if server else ""
            initial_lib = (
                next((lib for lib in result if lib.id == last_id), None)
                or result[0]
            )
            self._current_library = initial_lib
            self._fetch_browse_content(initial_lib.id)
            self._show_browse()

        elif tag == "browse_content":
            result_lib_id, rows = result
            current_lib = getattr(self, "_current_library", None)
            if current_lib and result_lib_id != current_lib.id:
                return  # stale result from a previously selected library
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

        elif tag == "playlist_detail":
            playlist, progress_map = result
            logger.debug("Playlist detail loaded: %s (%d items)", playlist.name, playlist.item_count)
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

        elif tag == "playlist_item_chapters":
            library_item = result
            item = self._pending_playlist_item
            if item is None:
                return
            chapters = library_item.media.chapters
            if len(chapters) > 1:
                prog = self._playlist_detail_screen._progress.get(item.library_item_id)
                self._chapter_screen.load_from_playlist_item(item, chapters, prog, self._server_url, self._token)
                self._stack.setCurrentWidget(self._chapter_screen)
            else:
                prog = self._playlist_detail_screen._progress.get(item.library_item_id)
                start_time = prog.current_time if prog and not prog.is_finished else 0.0
                self._on_playlist_item_play_requested(item, start_time)

        elif tag == "start_session":
            # result is a PlaybackSession — build URL and start playback
            session = result
            if session.audio_tracks and self._player_screen:
                track = session.audio_tracks[0]
                url = f"{self._server_url}{track.content_url}"
                self._player_screen.set_audio_tracks(url, session.current_time, self._token)

        elif tag == "progress":
            pass  # fire-and-forget

    @pyqtSlot(str, str)
    def _on_error(self, tag: str, message: str) -> None:
        logger.error("Async error [%s]: %s", tag, message)
        if tag == "login":
            self._login_screen.show_error(f"Login failed: {message}")
        elif tag == "autologin":
            self._show_login()
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

    def _setup_quit_shortcut(self) -> None:
        for seq in ("Ctrl+Q", "Q"):
            sc = QShortcut(QKeySequence(seq), self)
            sc.activated.connect(self.close)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Q or (
            event.key() == Qt.Key.Key_Q
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self.close()
        else:
            super().keyPressEvent(event)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        if self._player:
            self._player.shutdown()
        self._worker.stop_loop()
        self._thread.quit()
        self._thread.wait(2000)
        super().closeEvent(event)
