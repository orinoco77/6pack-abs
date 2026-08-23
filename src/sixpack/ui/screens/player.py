"""Now-playing full-screen overlay."""
from __future__ import annotations

import math

from PyQt6.QtCore import Qt, QTimer, QSize, pyqtSignal
from PyQt6.QtGui import QPixmap, QKeyEvent
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from sixpack.api.models import (
    Chapter,
    LibraryItem,
    MediaProgress,
    Playlist,
    PlaylistItem,
    PodcastEpisode,
    Series,
    SeriesBook,
)
from sixpack.player.player import AudioPlayer
from sixpack.ui import theme
from sixpack.ui.cover_cache import CoverCache
from sixpack.ui.screens.chapter_select import ChapterItem, _chapter_status, _chapter_fraction
from sixpack.ui.widgets.backdrop import Backdrop


_SPEED_STEPS = [1.0, 1.25, 1.5, 1.75, 2.0]

# Roughly 3 lines' worth of text for the description panel -- no scrolling,
# no expand interaction, just a preview. Truncated at a word boundary
# rather than measuring actual font metrics (good enough for a preview;
# doesn't need to be pixel-exact).
_DESCRIPTION_MAX_CHARS = 280


def _truncate_description(text: str) -> str:
    text = text.strip()
    if len(text) <= _DESCRIPTION_MAX_CHARS:
        return text
    return text[:_DESCRIPTION_MAX_CHARS].rsplit(" ", 1)[0] + "…"


def _fmt_time(seconds: float) -> str:
    if not math.isfinite(seconds) or seconds < 0:
        seconds = 0.0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


class PlayerScreen(QWidget):
    """
    Full-screen Now Playing screen.

    Signals:
      back_requested  — user pressed Back (returns to series detail)
      next_item       — manual skip to next episode (button/remote)
      prev_item       — manual skip to previous episode (button/remote)
      track_ended     — current track finished playing on its own
      progress_update — (item_id, current_time, duration, is_finished, episode_id)
    """

    back_requested = pyqtSignal()
    next_item = pyqtSignal()
    prev_item = pyqtSignal()
    track_ended = pyqtSignal()
    # item_id, current_time, duration, is_finished, episode_id
    progress_update = pyqtSignal(str, float, float, bool, str)

    def __init__(self, player: AudioPlayer, cover_cache: CoverCache | None = None, parent=None) -> None:
        super().__init__(parent)
        self._player = player
        self._cover_cache = cover_cache
        self._current_book: SeriesBook | None = None
        self._series: Series | None = None
        self._series_books: list[SeriesBook] = []
        self._current_playlist_item: PlaylistItem | None = None
        self._playlist: Playlist | None = None
        self._playlist_items: list[PlaylistItem] = []
        self._current_index = 0
        self._duration = 0.0
        self._position = 0.0
        self._item_id = ""
        self._episode_id = ""
        self._speed_index = 0
        self._chapters: list[Chapter] = []

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._build_ui()
        self._connect_player()

        # Progress sync timer — every 10 s
        self._sync_timer = QTimer(self)
        self._sync_timer.setInterval(10_000)
        self._sync_timer.timeout.connect(self._sync_progress)

    def _build_ui(self) -> None:
        self._backdrop = Backdrop(self)
        self._backdrop.lower()

        root = QVBoxLayout(self)
        root.setContentsMargins(60, 40, 60, 40)
        root.setSpacing(0)

        # Top row: back + series title
        top = QHBoxLayout()
        self._back_btn = QPushButton("← Back")
        self._back_btn.setFixedWidth(120)
        self._back_btn.setStyleSheet(f"font-size: {theme.FONT_BAR_BTN}pt;")
        self._back_btn.clicked.connect(self.back_requested)
        top.addWidget(self._back_btn)
        top.addStretch()
        self._series_label = QLabel()
        self._series_label.setStyleSheet(
            f"color: {theme.TEXT_SECONDARY}; font-size: {theme.FONT_META}pt; "
            f"background: transparent;"
        )
        top.addWidget(self._series_label)
        root.addLayout(top)

        root.addStretch(1)

        # Cover + info side-by-side
        middle = QHBoxLayout()
        middle.setSpacing(40)

        self._cover_label = QLabel()
        self._cover_label.setFixedSize(400, 400)
        self._cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cover_label.setStyleSheet(
            f"background-color: {theme.SURFACE_HIGH}; border-radius: 12px;"
        )
        middle.addWidget(self._cover_label)

        info = QVBoxLayout()
        info.setSpacing(12)
        info.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self._title_label = QLabel()
        self._title_label.setWordWrap(True)
        self._title_label.setStyleSheet(
            f"font-size: {theme.FONT_TITLE}pt; font-weight: bold; color: {theme.TEXT_PRIMARY}; "
            f"background: transparent;"
        )
        info.addWidget(self._title_label)

        self._episode_label = QLabel()
        self._episode_label.setStyleSheet(
            f"color: {theme.TEXT_SECONDARY}; font-size: {theme.FONT_BODY}pt; "
            f"background: transparent;"
        )
        info.addWidget(self._episode_label)

        self._description_label = QLabel()
        self._description_label.setWordWrap(True)
        self._description_label.setStyleSheet(
            f"color: {theme.TEXT_SECONDARY}; font-size: {theme.FONT_META}pt; "
            f"background: transparent;"
        )
        self._description_label.setVisible(False)
        info.addWidget(self._description_label)

        middle.addLayout(info, stretch=1)
        root.addLayout(middle)

        root.addSpacing(40)

        # Progress bar
        progress_area = QVBoxLayout()
        progress_area.setSpacing(8)

        self._progress_bar = QProgressBar()
        self._progress_bar.setFixedHeight(10)
        self._progress_bar.setRange(0, 10000)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background: {theme.SURFACE_HIGH};
                border: none;
                border-radius: 5px;
            }}
            QProgressBar::chunk {{
                background: {theme.ACCENT};
                border-radius: 5px;
            }}
        """)
        progress_area.addWidget(self._progress_bar)

        times = QHBoxLayout()
        self._elapsed_label = QLabel("0:00")
        self._elapsed_label.setStyleSheet(
            f"color: {theme.TEXT_SECONDARY}; background: transparent;"
        )
        times.addWidget(self._elapsed_label)
        times.addStretch()
        self._remaining_label = QLabel("0:00")
        self._remaining_label.setStyleSheet(
            f"color: {theme.TEXT_SECONDARY}; background: transparent;"
        )
        times.addWidget(self._remaining_label)
        progress_area.addLayout(times)
        root.addLayout(progress_area)

        root.addSpacing(24)

        # Transport controls
        controls = QHBoxLayout()
        controls.setAlignment(Qt.AlignmentFlag.AlignCenter)
        controls.setSpacing(20)

        # Chapters and speed bookend the core transport cluster, smaller and
        # more de-emphasized than the secondary transport buttons below —
        # they're tertiary controls, not part of the play/seek/skip group.
        self._chapters_btn = QPushButton(theme.ICON_MENU_BOOK)
        self._chapters_btn.setFixedSize(44, 44)
        self._chapters_btn.clicked.connect(self._toggle_chapter_overlay)

        self._prev_btn = QPushButton(theme.ICON_SKIP_PREVIOUS)
        self._prev_btn.setFixedSize(64, 64)
        self._prev_btn.clicked.connect(self.prev_item)

        self._rew_btn = QPushButton(theme.ICON_REPLAY_30)
        self._rew_btn.setFixedSize(64, 64)
        self._rew_btn.clicked.connect(self._player.seek_back)

        self._play_btn = QPushButton(theme.ICON_PAUSE)
        self._play_btn.setFixedSize(80, 80)
        self._play_btn.setStyleSheet(
            f"font-family: '{theme.ICON_FONT_FAMILY}'; font-size: 32pt; "
            f"background-color: {theme.ACCENT}; border-radius: 40px; "
            f"color: white; border: none; padding: 0;"
        )
        self._play_btn.clicked.connect(self._player.toggle_pause)

        self._fwd_btn = QPushButton(theme.ICON_FORWARD_30)
        self._fwd_btn.setFixedSize(64, 64)
        self._fwd_btn.clicked.connect(self._player.seek_forward)

        self._next_btn = QPushButton(theme.ICON_SKIP_NEXT)
        self._next_btn.setFixedSize(64, 64)
        self._next_btn.clicked.connect(self.next_item)

        self._speed_btn = QPushButton(theme.ICON_SPEED)
        self._speed_btn.setFixedSize(44, 44)
        self._speed_btn.clicked.connect(self._cycle_speed)

        for btn in (
            self._chapters_btn, self._prev_btn, self._rew_btn, self._play_btn,
            self._fwd_btn, self._next_btn, self._speed_btn,
        ):
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            controls.addWidget(btn)

        # De-emphasize the secondary transport buttons — flat/muted — so
        # they read as present-but-not-focusable next to the accent-filled
        # play/pause button, which stays the one visually "hot" control.
        for btn in (self._prev_btn, self._rew_btn, self._fwd_btn, self._next_btn):
            btn.setStyleSheet(
                f"font-family: '{theme.ICON_FONT_FAMILY}'; background: transparent; "
                f"color: {theme.TEXT_SECONDARY}; border: none; font-size: 22pt; padding: 0;"
            )

        for btn in (self._chapters_btn, self._speed_btn):
            btn.setStyleSheet(
                f"font-family: '{theme.ICON_FONT_FAMILY}'; background: transparent; "
                f"color: {theme.TEXT_MUTED}; border: none; font-size: 16pt; padding: 0;"
            )

        # The speed button itself is icon-only (matches the approved
        # layout); the current multiplier still needs to be visible
        # somewhere, so it sits as a small label right next to the icon.
        self._speed_value_label = QLabel("1.0x")
        self._speed_value_label.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: {theme.FONT_META}pt; "
            f"background: transparent;"
        )
        controls.addWidget(self._speed_value_label)

        root.addLayout(controls)

        self._up_next_label = QLabel("")
        self._up_next_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._up_next_label.setStyleSheet(
            f"color: {theme.TEXT_SECONDARY}; font-size: {theme.FONT_BODY}pt; "
            f"background: transparent;"
        )
        self._up_next_label.setVisible(False)
        root.addWidget(self._up_next_label)

        root.addStretch(1)

        # In-player chapter access overlay — hidden modal list over the
        # player, opened/closed via InputAction.MENU. Not part of `root`'s
        # layout flow (it floats above everything else, like a modal), so
        # it's constructed as a plain child of `self` and positioned
        # explicitly in resizeEvent, mirroring chapter_select.py's own
        # QListWidget construction/styling.
        self._chapter_overlay = QListWidget(self)
        self._chapter_overlay.setSpacing(2)
        self._chapter_overlay.setStyleSheet(f"""
            QListWidget {{
                background: {theme.SURFACE};
                border: 2px solid {theme.ACCENT};
                border-radius: 8px;
                outline: none;
            }}
            QListWidget::item {{ padding: 0; margin: 2px 0; border: none; }}
            QListWidget::item:selected {{ background-color: transparent; }}
        """)
        self._chapter_overlay.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._chapter_overlay.itemActivated.connect(self._on_overlay_chapter_activated)
        self._chapter_overlay.hide()

    def resizeEvent(self, event) -> None:
        self._backdrop.setGeometry(self.rect())
        w, h = int(self.width() * 0.6), int(self.height() * 0.7)
        self._chapter_overlay.setGeometry((self.width() - w) // 2, (self.height() - h) // 2, w, h)
        super().resizeEvent(event)

    def _connect_player(self) -> None:
        self._player.on_position_changed(self._on_position)
        self._player.on_state_changed(self._on_state_changed)
        self._player.on_end_of_track(self._on_end_of_track)
        self._player.on_duration_changed(self._on_duration_changed)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def _reset_per_item_state(self) -> None:
        """Clear every piece of per-item state before a play_* method sets
        its own. PlayerScreen is a process-lifetime singleton — constructed
        once in app.py and reused for every item played for the app's whole
        life — so anything set for one item that isn't explicitly cleared
        here can leak into the next item played on this same instance
        (wrong-book chapter overlay, wrong-mode "up next" navigation
        target, etc.). This has been the root cause of every per-item-state
        bug found across this plan's fix rounds. Any FUTURE per-item state
        this screen grows must be reset here too — this is its one home.
        """
        self._chapters = []
        self._chapter_overlay.hide()
        self._chapter_overlay.clear()
        self._current_book = None
        self._series = None
        self._series_books = []
        self._current_playlist_item = None
        self._playlist = None
        self._playlist_items = []
        self._episode_id = ""

    def play_book(
        self,
        book: SeriesBook,
        start_time: float,
        series: Series,
        books: list[SeriesBook],
        server_url: str,
        token: str,
    ) -> None:
        # Reset all per-item state (chapters, chapter overlay, and the
        # OTHER mode's book/series vs. playlist fields) before setting this
        # item's own fields below. See _reset_per_item_state's docstring.
        self._reset_per_item_state()
        self._current_book = book
        self._series = series
        self._series_books = books
        self._current_index = books.index(book) if book in books else 0
        self._item_id = book.id

        self._title_label.setText(book.title)
        self._series_label.setText(series.name)
        seq = f"Episode {book.sequence}" if book.sequence else ""
        self._episode_label.setText(seq)
        self._set_description(book.description)

        # Fetch cover (via cache if available)
        cover_url = book.cover_url(server_url, token)
        if self._cover_cache is not None:
            self._cover_cache.fetch(cover_url, token, self._set_cover_pixmap)
            # Set the expected key synchronously, before the async
            # fetch_backdrop() call below kicks off — see
            # `_set_backdrop_pixmap`/`Backdrop.set_expected_key` for why:
            # this screen is constructed once and reused across
            # play_book()/play_library_item()/play_playlist_item() calls
            # (app.py's _on_next_item/_on_prev_item call back into this same
            # instance), so a fetch still in flight for a previous item must
            # not clobber a later item's backdrop when it resolves.
            self._backdrop.set_expected_key(self._item_id)
            self._cover_cache.fetch_backdrop(
                cover_url, token,
                lambda pix, key=self._item_id: self._set_backdrop_pixmap(pix, key),
            )

        self._server_url = server_url
        self._token = token
        self._sync_timer.start()

    def play_library_item(
        self,
        item: LibraryItem,
        start_time: float,
        server_url: str,
        token: str,
    ) -> None:
        """Play a standalone library item (from the browse screen, no series context)."""
        # See _reset_per_item_state's docstring — reset all per-item state
        # before setting this item's own fields below.
        self._reset_per_item_state()
        self._current_index = 0
        self._item_id = item.id

        self._title_label.setText(item.title)
        self._series_label.setText(item.subtitle)
        self._episode_label.setText("")
        self._set_description(item.description)

        cover_url = item.cover_url(server_url, token)
        if self._cover_cache is not None:
            self._cover_cache.fetch(cover_url, token, self._set_cover_pixmap)
            # See the matching comment in play_book() — this screen instance
            # is reused across play_* calls, so guard the async backdrop
            # fetch against a stale callback overwriting a later item.
            self._backdrop.set_expected_key(self._item_id)
            self._cover_cache.fetch_backdrop(
                cover_url, token,
                lambda pix, key=self._item_id: self._set_backdrop_pixmap(pix, key),
            )

        self._server_url = server_url
        self._token = token
        self._sync_timer.start()

    def play_playlist_item(
        self,
        item: PlaylistItem,
        start_time: float,
        playlist: Playlist,
        items: list[PlaylistItem],
        server_url: str,
        token: str,
    ) -> None:
        """Play an item from a playlist (similar to play_book but for playlists)."""
        # See _reset_per_item_state's docstring — reset all per-item state
        # (including the book/series fields) before setting this item's own
        # fields below.
        self._reset_per_item_state()
        self._current_playlist_item = item
        self._playlist = playlist
        self._playlist_items = items
        self._current_index = items.index(item) if item in items else 0
        self._item_id = item.library_item_id

        self._title_label.setText(item.title)
        self._series_label.setText(playlist.name)
        self._episode_label.setText(f"Item {self._current_index + 1} of {len(items)}")
        self._set_description(item.description)

        # Fetch cover (via cache if available)
        cover_url = item.cover_url(server_url, token)
        if self._cover_cache is not None:
            self._cover_cache.fetch(cover_url, token, self._set_cover_pixmap)
            # See the matching comment in play_book() — this screen instance
            # is reused across play_* calls, so guard the async backdrop
            # fetch against a stale callback overwriting a later item.
            self._backdrop.set_expected_key(self._item_id)
            self._cover_cache.fetch_backdrop(
                cover_url, token,
                lambda pix, key=self._item_id: self._set_backdrop_pixmap(pix, key),
            )

        self._server_url = server_url
        self._token = token
        self._sync_timer.start()

    def play_podcast_episode(
        self,
        episode: PodcastEpisode,
        show: LibraryItem,
        start_time: float,
        server_url: str,
        token: str,
    ) -> None:
        """Play a podcast episode. Cover/backdrop use the show's own art
        (episodes have none of their own); progress/session calls need the
        episode id too, tracked separately from _item_id."""
        self._reset_per_item_state()
        self._current_index = 0
        self._item_id = show.id
        self._episode_id = episode.id

        self._title_label.setText(episode.title)
        self._series_label.setText(show.title)
        self._episode_label.setText("")
        self._set_description(episode.description)

        cover_url = show.cover_url(server_url, token)
        if self._cover_cache is not None:
            self._cover_cache.fetch(cover_url, token, self._set_cover_pixmap)
            self._backdrop.set_expected_key(self._item_id)
            self._cover_cache.fetch_backdrop(
                cover_url, token,
                lambda pix, key=self._item_id: self._set_backdrop_pixmap(pix, key),
            )

        self._server_url = server_url
        self._token = token
        self._sync_timer.start()

    def set_chapters(self, chapters: list[Chapter]) -> None:
        """Give this screen the current item's chapter list, for the
        in-player chapter access overlay (InputAction.MENU). Called by
        app.py separately from play_book/play_library_item/
        play_playlist_item — see those methods' docstrings/callers in
        app.py for the two paths chapters arrive by (direct single-chapter
        play vs. via ChapterSelectScreen)."""
        self._chapters = chapters

    def set_audio_tracks(self, content_url: str, start_time: float, token: str) -> None:
        self._player.play(content_url, start_time=start_time, auth_token=token)
        self._play_btn.setText("⏸")

    def show_up_next(self, message: str) -> None:
        self._up_next_label.setText(message)
        self._up_next_label.setVisible(True)

    def hide_up_next(self) -> None:
        self._up_next_label.setVisible(False)

    def _set_cover_pixmap(self, pix: QPixmap) -> None:
        scaled = pix.scaled(
            400, 400,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._cover_label.setPixmap(scaled)

    def _set_backdrop_pixmap(self, pix: QPixmap, key: str | None = None) -> None:
        self._backdrop.show_image(pix, key=key)

    # ------------------------------------------------------------------
    # Player callbacks  (called from mpv thread — no Qt widget access here)
    # ------------------------------------------------------------------

    def _on_position(self, seconds: float) -> None:
        self._position = seconds
        # Marshal to GUI thread
        from PyQt6.QtCore import QMetaObject, Q_ARG
        QMetaObject.invokeMethod(
            self, "_update_position",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(float, seconds),
        )

    def _on_duration_changed(self, seconds: float) -> None:
        self._duration = seconds
        from PyQt6.QtCore import QMetaObject, Q_ARG
        QMetaObject.invokeMethod(
            self, "_update_duration",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(float, seconds),
        )

    def _on_state_changed(self, state: str) -> None:
        from PyQt6.QtCore import QMetaObject, Q_ARG
        QMetaObject.invokeMethod(
            self, "_update_state",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(str, state),
        )

    def _on_end_of_track(self) -> None:
        from PyQt6.QtCore import QMetaObject
        QMetaObject.invokeMethod(
            self, "_handle_end_of_track",
            Qt.ConnectionType.QueuedConnection,
        )

    # ------------------------------------------------------------------
    # GUI-thread slots
    # ------------------------------------------------------------------

    @staticmethod
    def _slot_update_position(self, seconds: float) -> None:
        pass

    from PyQt6.QtCore import pyqtSlot

    @pyqtSlot(float)
    def _update_position(self, seconds: float) -> None:
        self._elapsed_label.setText(_fmt_time(seconds))
        remaining = max(0.0, self._duration - seconds)
        self._remaining_label.setText(f"-{_fmt_time(remaining)}")
        if self._duration > 0:
            self._progress_bar.setValue(int(seconds / self._duration * 10000))

    @pyqtSlot(float)
    def _update_duration(self, seconds: float) -> None:
        self._duration = seconds

    @pyqtSlot(str)
    def _update_state(self, state: str) -> None:
        self._play_btn.setText("⏸" if state == "playing" else "▶")

    @pyqtSlot()
    def _handle_end_of_track(self) -> None:
        self._sync_progress()
        self.track_ended.emit()

    def _sync_progress(self) -> None:
        if self._item_id and self._duration > 0:
            is_finished = (self._duration - self._position) < 10
            self.progress_update.emit(
                self._item_id, self._position, self._duration, is_finished, self._episode_id
            )

    def _set_description(self, text: str) -> None:
        text = _truncate_description(text)
        if not text:
            self._description_label.setVisible(False)
            self._description_label.setText("")
            return
        self._description_label.setText(text)
        self._description_label.setVisible(True)

    def _cycle_speed(self) -> None:
        self._speed_index = (self._speed_index + 1) % len(_SPEED_STEPS)
        speed = _SPEED_STEPS[self._speed_index]
        self._player.set_speed(speed)
        self._speed_value_label.setText(f"{speed}x")

    # ------------------------------------------------------------------
    # Chapter access overlay
    # ------------------------------------------------------------------

    def _toggle_chapter_overlay(self) -> None:
        if self._chapter_overlay.isVisible():
            self._chapter_overlay.hide()
            return
        if not self._chapters:
            return
        self._chapter_overlay.clear()
        current_time = self._position
        for i, chapter in enumerate(self._chapters):
            status = _chapter_status(chapter, current_time, is_finished=False)
            fraction = _chapter_fraction(chapter, current_time, status)
            widget = ChapterItem(i, chapter, status, fraction)
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 68))
            self._chapter_overlay.addItem(item)
            self._chapter_overlay.setItemWidget(item, widget)
        self._chapter_overlay.setCurrentRow(self._current_chapter_index())
        self._chapter_overlay.show()

    def _current_chapter_index(self) -> int:
        for i, chapter in enumerate(self._chapters):
            if self._position < chapter.end:
                return i
        return max(0, len(self._chapters) - 1)

    def _on_overlay_chapter_activated(self, item: QListWidgetItem) -> None:
        # Seek by TIME, not by index — `row` is an index into
        # self._chapters (Audiobookshelf's own item-level chapter
        # metadata), which is a different data source than mpv's own
        # internally-derived chapter list that AudioPlayer.seek_to_chapter
        # indexes into (different length/ordering possible for multi-file
        # items, transcoded streams, or zero embedded chapters mpv can
        # detect). Every other chapter jump in this app (chapter_select.py)
        # seeks by time the same way — see chapter.start usage there.
        row = self._chapter_overlay.row(item)
        if 0 <= row < len(self._chapters):
            self._player.seek_absolute(self._chapters[row].start)
        self._chapter_overlay.hide()

    # ------------------------------------------------------------------
    # Keyboard / gamepad
    # ------------------------------------------------------------------

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.setFocus()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        from sixpack.input.keyboard import key_to_action
        from sixpack.input.actions import InputAction

        action = key_to_action(event.key(), player_mode=True)

        if self._chapter_overlay.isVisible():
            # While the overlay is open, it owns SELECT/UP/DOWN/BACK/MENU —
            # none of these should also fall through to the normal
            # player-mode bindings below (e.g. SELECT must not also seek).
            #
            # Note: in player_mode, key_to_action's keyboard map never
            # produces InputAction.SELECT for Key_Return (it maps to MENU,
            # matching Kodi's "Enter = show OSD" convention) — SELECT only
            # ever arrives from a gamepad's A button (see gamepad.py). So
            # both SELECT *and* MENU are treated as "activate the
            # highlighted chapter" here, which is what lets a keyboard user
            # open the overlay (MENU when closed) and then confirm a
            # highlighted chapter (MENU again, now open) with the same key.
            # BACK is the only way to dismiss the overlay without seeking.
            if action == InputAction.BACK:
                self._chapter_overlay.hide()
            elif action in (InputAction.SELECT, InputAction.MENU):
                current = self._chapter_overlay.currentItem()
                if current:
                    self._on_overlay_chapter_activated(current)
                else:
                    self._chapter_overlay.hide()
            elif action == InputAction.UP:
                row = self._chapter_overlay.currentRow()
                if row > 0:
                    self._chapter_overlay.setCurrentRow(row - 1)
            elif action == InputAction.DOWN:
                row = self._chapter_overlay.currentRow()
                if row + 1 < self._chapter_overlay.count():
                    self._chapter_overlay.setCurrentRow(row + 1)
            return

        if action == InputAction.MENU:
            self._toggle_chapter_overlay()
        elif action == InputAction.BACK:
            self.back_requested.emit()
        elif action == InputAction.PLAY_PAUSE:
            self._player.toggle_pause()
        elif action == InputAction.UP:
            self._cycle_speed()
        elif action == InputAction.STOP:
            self._player.stop()
            self.back_requested.emit()
        elif action == InputAction.SEEK_FORWARD:
            self._player.seek_forward()
        elif action == InputAction.SEEK_BACK:
            self._player.seek_back()
        elif action == InputAction.SEEK_FORWARD_LONG:
            self._player.seek_forward_long()
        elif action == InputAction.SEEK_BACK_LONG:
            self._player.seek_back_long()
        elif action == InputAction.NEXT_CHAPTER:
            self._player.next_chapter()
        elif action == InputAction.PREV_CHAPTER:
            self._player.prev_chapter()
        elif action == InputAction.NEXT_ITEM:
            self.next_item.emit()
        elif action == InputAction.PREV_ITEM:
            self.prev_item.emit()
        else:
            super().keyPressEvent(event)
