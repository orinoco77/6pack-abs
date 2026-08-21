"""Dark 10-foot TV theme for SixPack."""
from __future__ import annotations

# Colour palette
BG = "#0f0f0f"
SURFACE = "#1c1c1c"
SURFACE_HIGH = "#2a2a2a"
SURFACE_LOW = "#151515"
ACCENT = "#4a9eff"
ACCENT_DIM = "#2a6fcc"
# Deliberately distinct from ACCENT (a lighter, more saturated tint of the
# same blue hue) — it used to be byte-identical to ACCENT, which made the
# focus glow (painted translucent over the card's own opaque ACCENT border)
# indistinguishable from the border itself. See MediaCard's glow overlay.
ACCENT_GLOW = "#a8d8ff"
TEXT_PRIMARY = "#ffffff"
TEXT_SECONDARY = "#a0a0a0"
TEXT_MUTED = "#606060"
DANGER = "#e85555"
SUCCESS = "#4caf50"

# Cinematic backdrop
BACKDROP_W = 1920
BACKDROP_H = 1080
BACKDROP_DARKEN = 0.45           # fraction of black overlaid on blurred cover
BACKDROP_SCRIM_TOP = "#00000000"     # transparent
BACKDROP_SCRIM_BOTTOM = "#e6000000"  # near-opaque black at the bottom

# Focus feedback
FOCUS_ANIM_MS = 130
UNFOCUSED_OPACITY = 0.55

# Subtle top→bottom window gradient (used as the base background)
GRADIENT_BG = (
    f"qlineargradient(x1:0, y1:0, x2:0, y2:1, "
    f"stop:0 {SURFACE_LOW}, stop:1 {BG})"
)

# Hero band scrim: opaque BG at the top (keeps the hero title/subtitle
# legible) fading to fully transparent at the bottom. The hero band sits at
# a fixed position over the backdrop/rows, so a flat opaque background would
# both hide the backdrop entirely and create a hard edge where rows scroll
# up underneath it (via ensureWidgetVisible). Same #AARRGGBB-stop pattern as
# BACKDROP_SCRIM_TOP/BOTTOM above, just anchored to BG instead of black.
HERO_SCRIM_TOP = f"#ff{BG[1:]}"     # opaque BG
HERO_SCRIM_BOTTOM = f"#00{BG[1:]}"  # transparent BG
GRADIENT_HERO_SCRIM = (
    f"qlineargradient(x1:0, y1:0, x2:0, y2:1, "
    f"stop:0 {HERO_SCRIM_TOP}, stop:0.65 {HERO_SCRIM_TOP}, stop:1 {HERO_SCRIM_BOTTOM})"
)

# Font sizes (pt) — sized for TV viewing distance
FONT_HUGE = 32
FONT_TITLE = 24
FONT_HEADING = 20
FONT_BODY = 16
FONT_META = 13
FONT_BAR_BTN = 13   # header-bar buttons — compact but readable

CARD_WIDTH = 210
CARD_HEIGHT = 280
CARD_ART_HEIGHT = 200
CARD_INFO_HEIGHT = CARD_HEIGHT - CARD_ART_HEIGHT  # 80px
CARD_RADIUS = 8
FOCUS_BORDER = 3

STYLESHEET = f"""
QWidget {{
    background-color: {BG};
    color: {TEXT_PRIMARY};
    font-family: "Noto Sans", "DejaVu Sans", sans-serif;
    font-size: {FONT_BODY}pt;
}}

QMainWindow, #screen_root {{
    background: {GRADIENT_BG};
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

QMenu {{
    background-color: {SURFACE_HIGH};
    color: {TEXT_PRIMARY};
    border: 1px solid {TEXT_MUTED};
    border-radius: 6px;
    padding: 4px;
}}

QMenu::item {{
    padding: 10px 24px;
    border-radius: 4px;
}}

QMenu::item:selected {{
    background-color: {ACCENT_DIM};
    color: {TEXT_PRIMARY};
}}

QMenu::item:checked {{
    color: {ACCENT};
}}

QMenu::separator {{
    height: 1px;
    background: {TEXT_MUTED};
    margin: 4px 12px;
}}
"""


def apply(app: "QApplication") -> None:  # type: ignore[name-defined]  # noqa: F821
    app.setStyleSheet(STYLESHEET)
