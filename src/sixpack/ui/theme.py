"""Dark 10-foot TV theme for SixPack."""
from __future__ import annotations

# Colour palette
BG = "#0f0f0f"
SURFACE = "#1c1c1c"
SURFACE_HIGH = "#2a2a2a"
ACCENT = "#4a9eff"
ACCENT_DIM = "#2a6fcc"
TEXT_PRIMARY = "#ffffff"
TEXT_SECONDARY = "#a0a0a0"
TEXT_MUTED = "#606060"
DANGER = "#e85555"
SUCCESS = "#4caf50"

# Font sizes (pt) — oversized for TV viewing distance
FONT_HUGE = 36
FONT_TITLE = 28
FONT_HEADING = 22
FONT_BODY = 18
FONT_META = 14

CARD_WIDTH = 200
CARD_HEIGHT = 260
CARD_ART_HEIGHT = 190
CARD_RADIUS = 8
FOCUS_BORDER = 3

STYLESHEET = f"""
QWidget {{
    background-color: {BG};
    color: {TEXT_PRIMARY};
    font-family: "Noto Sans", "DejaVu Sans", sans-serif;
    font-size: {FONT_BODY}pt;
}}

QLabel {{
    background: transparent;
}}

QScrollArea {{
    border: none;
    background-color: {BG};
}}

QScrollBar:vertical {{
    background: {SURFACE};
    width: 6px;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background: {TEXT_MUTED};
    border-radius: 3px;
    min-height: 30px;
}}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {{
    height: 0px;
}}

QScrollBar:horizontal {{
    height: 0px;
}}

QPushButton {{
    background-color: {SURFACE_HIGH};
    color: {TEXT_PRIMARY};
    border: 2px solid transparent;
    border-radius: 6px;
    padding: 10px 24px;
    font-size: {FONT_BODY}pt;
    font-weight: bold;
}}

QPushButton:focus {{
    border-color: {ACCENT};
    background-color: {ACCENT_DIM};
}}

QPushButton:hover {{
    background-color: {ACCENT_DIM};
}}

QPushButton:pressed {{
    background-color: {ACCENT};
}}

QLineEdit {{
    background-color: {SURFACE_HIGH};
    color: {TEXT_PRIMARY};
    border: 2px solid {TEXT_MUTED};
    border-radius: 6px;
    padding: 10px 16px;
    font-size: {FONT_BODY}pt;
    selection-background-color: {ACCENT};
}}

QLineEdit:focus {{
    border-color: {ACCENT};
}}

QLineEdit:disabled {{
    color: {TEXT_MUTED};
}}

QProgressBar {{
    background-color: {SURFACE_HIGH};
    border: none;
    border-radius: 4px;
    height: 8px;
    text-align: center;
}}

QProgressBar::chunk {{
    background-color: {ACCENT};
    border-radius: 4px;
}}

QListWidget {{
    background-color: {BG};
    border: none;
    outline: none;
}}

QListWidget::item {{
    background-color: {SURFACE};
    color: {TEXT_PRIMARY};
    padding: 14px 20px;
    margin: 3px 0;
    border-radius: 6px;
    border: 2px solid transparent;
}}

QListWidget::item:selected {{
    background-color: {SURFACE_HIGH};
    border-color: {ACCENT};
    color: {TEXT_PRIMARY};
}}

QListWidget::item:focus {{
    border-color: {ACCENT};
    outline: none;
}}
"""


def apply(app: "QApplication") -> None:  # type: ignore[name-defined]  # noqa: F821
    app.setStyleSheet(STYLESHEET)
