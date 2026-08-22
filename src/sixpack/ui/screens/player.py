"""Now-playing full-screen overlay."""
from __future__ import annotations

import math

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap, QKeyEvent
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from sixpack.api.models import LibraryItem, MediaProgress, Series, SeriesBook, Playlist, PlaylistItem
from sixpack.player.player import AudioPlayer
from sixpack.ui import theme
from sixpack.ui.cover_cache import CoverCache
from sixpack.ui.widgets.backdrop import Backdrop


_SPEED_STEPS = [1.0, 1.25, 1.5, 1.75, 2.0]


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
      progress_update — (item_id, current_time, duration, is_finished)
    """

    back_requested = pyqtSignal()
    next_item = pyqtSignal()
    prev_item = pyqtSignal()
    track_ended = pyqtSignal()
    progress_update = pyqtSignal(str, float, float, bool)

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
        self._speed_index = 0

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

        self._prev_btn = QPushButton("⏮")
        self._prev_btn.setFixedSize(64, 64)
        self._prev_btn.clicked.connect(self.prev_item)

        self._rew_btn = QPushButton("⏪ 30s")
        self._rew_btn.setFixedWidth(100)
        self._rew_btn.clicked.connect(self._player.seek_back)

        self._play_btn = QPushButton("⏸")
        self._play_btn.setFixedSize(80, 80)
        self._play_btn.setStyleSheet(
            f"font-size: 28pt; background-color: {theme.ACCENT}; border-radius: 40px;"
            f"color: white; border: none;"
        )
        self._play_btn.clicked.connect(self._player.toggle_pause)

        self._fwd_btn = QPushButton("30s ⏩")
        self._fwd_btn.setFixedWidth(100)
        self._fwd_btn.clicked.connect(self._player.seek_forward)

        self._next_btn = QPushButton("⏭")
        self._next_btn.setFixedSize(64, 64)
        self._next_btn.clicked.connect(self.next_item)

        for btn in (self._prev_btn, self._rew_btn, self._play_btn, self._fwd_btn, self._next_btn):
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            controls.addWidget(btn)

        # De-emphasize the secondary transport buttons — flat/muted — so
        # they read as present-but-not-focusable next to the accent-filled
        # play/pause button, which stays the one visually "hot" control.
        for btn in (self._prev_btn, self._rew_btn, self._fwd_btn, self._next_btn):
            btn.setStyleSheet(
                f"background: transparent; color: {theme.TEXT_SECONDARY}; "
                f"border: none; font-size: 18pt;"
            )

        self._speed_label = QLabel("1.0x")
        self._speed_label.setStyleSheet(
            f"color: {theme.TEXT_SECONDARY}; font-size: {theme.FONT_META}pt; "
            f"background: transparent;"
        )
        controls.addWidget(self._speed_label)

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

    def resizeEvent(self, event) -> None:
        self._backdrop.setGeometry(self.rect())
        super().resizeEvent(event)

    def _connect_player(self) -> None:
        self._player.on_position_changed(self._on_position)
        self._player.on_state_changed(self._on_state_changed)
        self._player.on_end_of_track(self._on_end_of_track)
        self._player.on_duration_changed(self._on_duration_changed)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def play_book(
        self,
        book: SeriesBook,
        start_time: float,
        series: Series,
        books: list[SeriesBook],
        server_url: str,
        token: str,
    ) -> None:
        self._current_book = book
        self._series = series
        self._series_books = books
        self._current_index = books.index(book) if book in books else 0
        self._item_id = book.id

        self._title_label.setText(book.title)
        self._series_label.setText(series.name)
        seq = f"Episode {book.sequence}" if book.sequence else ""
        self._episode_label.setText(seq)

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
        self._current_book = None
        self._series = None
        self._series_books = []
        self._current_playlist_item = None
        self._playlist = None
        self._playlist_items = []
        self._current_index = 0
        self._item_id = item.id

        self._title_label.setText(item.title)
        self._series_label.setText(item.subtitle)
        self._episode_label.setText("")

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
        self._current_playlist_item = item
        self._playlist = playlist
        self._playlist_items = items
        self._current_index = items.index(item) if item in items else 0
        self._item_id = item.library_item_id

        self._title_label.setText(item.title)
        self._series_label.setText(playlist.name)
        self._episode_label.setText(f"Item {self._current_index + 1} of {len(items)}")

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
                self._item_id, self._position, self._duration, is_finished
            )

    def _cycle_speed(self) -> None:
        self._speed_index = (self._speed_index + 1) % len(_SPEED_STEPS)
        speed = _SPEED_STEPS[self._speed_index]
        self._player.set_speed(speed)
        self._speed_label.setText(f"{speed}x")

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
        if action == InputAction.BACK:
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
