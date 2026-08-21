"""Shared Backdrop+hero shell, composed into detail-style screens.

DetailGridScreen and ChapterSelectScreen both show one Backdrop (blurred
cover-art background) behind their content, with a hero title/subtitle
overlay in the top band. This was duplicated across both files almost
verbatim; this widget is the single implementation both compose instead
of inheriting or re-copying.

Deliberately NOT used by browse.py, which has a materially different
design (rows scroll *underneath* a translucent hero, vs. this widget's
content-starts-below-hero approach used by the single-item detail
screens) — see docs/superpowers/plans/2026-08-21-phase-b-cleanup.md.
"""
from __future__ import annotations

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from sixpack.ui import theme
from sixpack.ui.widgets.backdrop import Backdrop


class HeroBackdrop(QWidget):
    """A Backdrop plus a title/subtitle hero overlay in the top HERO_H px."""

    HERO_H = 150

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.backdrop = Backdrop(self)
        self.backdrop.lower()
        self._build_hero()

    def _build_hero(self) -> None:
        self._hero = QWidget(self)
        self._hero.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._hero.setStyleSheet(f"background: {theme.GRADIENT_HERO_SCRIM};")
        lay = QVBoxLayout(self._hero)
        lay.setContentsMargins(36, 24, 36, 8)
        lay.setSpacing(4)
        self._hero_title = QLabel("")
        self._hero_title.setStyleSheet(
            f"font-size: {theme.FONT_HUGE}pt; font-weight: bold; "
            f"color: {theme.TEXT_PRIMARY}; background: transparent;"
        )
        self._hero_sub = QLabel("")
        self._hero_sub.setStyleSheet(
            f"font-size: {theme.FONT_HEADING}pt; color: {theme.TEXT_SECONDARY}; "
            f"background: transparent;"
        )
        lay.addWidget(self._hero_title)
        lay.addWidget(self._hero_sub)
        self._hero.raise_()

    def resizeEvent(self, event) -> None:
        self.backdrop.setGeometry(self.rect())
        self._hero.setGeometry(QRect(0, 0, self.width(), self.HERO_H))
        super().resizeEvent(event)

    def set_title(self, text: str) -> None:
        self._hero_title.setText(text)

    def set_subtitle(self, text: str) -> None:
        self._hero_sub.setText(text)
