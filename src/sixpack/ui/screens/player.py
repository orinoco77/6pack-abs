"""Now-playing full-screen overlay."""
from __future__ import annotations

import math

from PyQt6.QtCore import Q_ARG, QMetaObject, QSize, Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QKeyEvent, QPixmap
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
    Playlist,
    PlaylistItem,
    PodcastEpisode,
    Series,
    SeriesBook,
)
from sixpack.player.player import AudioPlayer
from sixpack.ui import theme
from sixpack.ui.cover_cache import CoverCache
from sixpack.ui.screens.chapter_select import ChapterItem, _chapter_fraction, _chapter_status
from sixpack.ui.widgets.backdrop import Backdrop
from sixpack.ui.widgets.confirm_popup import ConfirmPopup

_SPEED_STEPS = [1.0, 1.25, 1.5, 1.75, 2.0]

# Roughly 6-7 lines' worth of text for the description panel -- no
# scrolling, no expand interaction, just a preview. Truncated at a word
# boundary rather than measuring actual font metrics (good enough for a
# preview; doesn't need to be pixel-exact).
_DESCRIPTION_MAX_CHARS = 600


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

    def __init__(
        self, player: AudioPlayer, cover_cache: CoverCache | None = None, parent=None
    ) -> None:
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

        self._finish_btn = QPushButton(theme.ICON_CHECK_CIRCLE)
        self._finish_btn.setFixedSize(44, 44)
        self._finish_btn.clicked.connect(self._on_finish_clicked)

        # This row is the screen's one, always-active focus zone (see
        # _move_control_focus/_reflect_control_focus/keyPressEvent) — real
        # Qt focus stays off every button (NoFocus), matching how every
        # other screen in this app manually tracks a focus index and
        # restyles instead of relying on real Qt focus traversal.
        self._control_buttons: list[QPushButton] = [
            self._chapters_btn, self._prev_btn, self._rew_btn, self._play_btn,
            self._fwd_btn, self._next_btn, self._speed_btn, self._finish_btn,
        ]
        for btn in self._control_buttons:
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            controls.addWidget(btn)

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

        # Play/pause is the most likely first action, so it's the row's
        # default landing spot — no separate "enter navigation" gesture
        # exists on this screen; Left/Right always move this highlight.
        self._control_focus_idx = self._control_buttons.index(self._play_btn)
        self._reflect_control_focus()

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

        self._finish_popup = ConfirmPopup(self)
        self._finish_popup.confirmed.connect(self._on_finish_confirmed)
        self._finish_popup.cancelled.connect(self._on_finish_cancelled)

    def resizeEvent(self, event) -> None:
        self._backdrop.setGeometry(self.rect())
        w, h = int(self.width() * 0.6), int(self.height() * 0.7)
        self._chapter_overlay.setGeometry((self.width() - w) // 2, (self.height() - h) // 2, w, h)
        fw, fh = int(self.width() * 0.5), 180
        self._finish_popup.setGeometry((self.width() - fw) // 2, (self.height() - fh) // 2, fw, fh)
        self._finish_popup.update_scrim_geometry()
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
        # Not stale data so much as a UI cursor position, but the same
        # "reset predictably on every new item" reasoning applies — land
        # back on play/pause rather than leaving focus wherever a skip
        # left it (e.g. on "next", inviting an accidental repeat-skip).
        self._control_focus_idx = self._control_buttons.index(self._play_btn)
        self._reflect_control_focus()

    def _finish_play_setup(self, cover_url: str, server_url: str, token: str) -> None:
        """Shared tail of every play_* method below: fetch cover/backdrop
        and start the progress-sync timer. Called once the caller has
        already set this item's own fields (title/series/episode labels,
        description, _item_id, etc.) -- _item_id specifically must already
        be set, since it's used to guard the async backdrop fetch below
        against a stale callback (this screen instance is reused across
        play_book()/play_library_item()/play_playlist_item()/
        play_podcast_episode() calls -- app.py's _on_next_item/_on_prev_item
        call back into this same instance -- so a fetch still in flight for
        a previous item must not clobber a later item's backdrop when it
        resolves)."""
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
        self._finish_play_setup(book.cover_url(server_url, token), server_url, token)

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
        self._finish_play_setup(item.cover_url(server_url, token), server_url, token)

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
        self._finish_play_setup(item.cover_url(server_url, token), server_url, token)

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
        self._finish_play_setup(show.cover_url(server_url, token), server_url, token)

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
        self._play_btn.setText(theme.ICON_PAUSE)

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
        QMetaObject.invokeMethod(
            self, "_update_position",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(float, seconds),
        )

    def _on_duration_changed(self, seconds: float) -> None:
        self._duration = seconds
        QMetaObject.invokeMethod(
            self, "_update_duration",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(float, seconds),
        )

    def _on_state_changed(self, state: str) -> None:
        QMetaObject.invokeMethod(
            self, "_update_state",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(str, state),
        )

    def _on_end_of_track(self) -> None:
        QMetaObject.invokeMethod(
            self, "_handle_end_of_track",
            Qt.ConnectionType.QueuedConnection,
        )

    # ------------------------------------------------------------------
    # GUI-thread slots
    # ------------------------------------------------------------------

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
        self._play_btn.setText(theme.ICON_PAUSE if state == "playing" else theme.ICON_PLAY)

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
    # Control row focus (Left/Right + Select — see keyPressEvent)
    # ------------------------------------------------------------------

    def _move_control_focus(self, delta: int) -> None:
        n = len(self._control_buttons)
        self._control_focus_idx = max(0, min(self._control_focus_idx + delta, n - 1))
        self._reflect_control_focus()

    def _reflect_control_focus(self) -> None:
        for i, btn in enumerate(self._control_buttons):
            focused = i == self._control_focus_idx
            if btn is self._play_btn:
                # Already accent-filled regardless of focus (it's the
                # screen's one permanently "hot" control) — focus gets a
                # brighter ring on top rather than a color swap, since an
                # accent-colored ring on an accent-filled button wouldn't
                # be visible at all.
                ring = theme.ACCENT_GLOW if focused else "transparent"
                btn.setStyleSheet(
                    f"font-family: '{theme.ICON_FONT_FAMILY}'; font-size: 32pt; "
                    f"background-color: {theme.ACCENT}; border-radius: 40px; "
                    f"color: white; border: 3px solid {ring}; padding: 0;"
                )
            elif btn in (self._chapters_btn, self._speed_btn, self._finish_btn):
                border = theme.ACCENT if focused else "transparent"
                btn.setStyleSheet(
                    f"font-family: '{theme.ICON_FONT_FAMILY}'; background: transparent; "
                    f"color: {theme.TEXT_MUTED}; border: 2px solid {border}; "
                    f"border-radius: 8px; font-size: 16pt; padding: 0;"
                )
            else:
                border = theme.ACCENT if focused else "transparent"
                btn.setStyleSheet(
                    f"font-family: '{theme.ICON_FONT_FAMILY}'; background: transparent; "
                    f"color: {theme.TEXT_SECONDARY}; border: 2px solid {border}; "
                    f"border-radius: 8px; font-size: 22pt; padding: 0;"
                )

    # ------------------------------------------------------------------
    # Mark finished
    # ------------------------------------------------------------------

    def _on_finish_clicked(self) -> None:
        title = self._title_label.text()
        self._finish_popup.show_confirm(
            f"Mark '{title}' as finished?", confirm_label="Mark Finished"
        )

    def _on_finish_confirmed(self) -> None:
        self.progress_update.emit(
            self._item_id, self._position, self._duration, True, self._episode_id
        )
        self._player.stop()
        self.track_ended.emit()
        self.setFocus()

    def _on_finish_cancelled(self) -> None:
        self.setFocus()

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
        from sixpack.input.actions import InputAction
        from sixpack.input.keyboard import key_to_action

        action = key_to_action(event.key(), player_mode=True)

        if self._chapter_overlay.isVisible():
            # While the overlay is open, it owns SELECT/UP/DOWN/BACK/MENU —
            # none of these should also fall through to the control row's
            # own Left/Right/Select handling below.
            #
            # Both SELECT and MENU are accepted as "activate the
            # highlighted chapter" — Key_Return/Key_Enter now produce
            # SELECT (see keyboard.py), and a gamepad's Y/Start button (if
            # ever wired up) would still produce MENU, so accepting either
            # keeps both paths working without needing to know which one
            # actually fired. BACK is the only way to dismiss the overlay
            # without jumping to a chapter.
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

        if action == InputAction.LEFT:
            self._move_control_focus(-1)
        elif action == InputAction.RIGHT:
            self._move_control_focus(1)
        elif action == InputAction.SELECT:
            # Reuses the focused button's own .clicked wiring rather than
            # a parallel dispatch table — whatever a mouse click on that
            # button already does is exactly what Select should do too.
            self._control_buttons[self._control_focus_idx].click()
        elif action == InputAction.MENU:
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
