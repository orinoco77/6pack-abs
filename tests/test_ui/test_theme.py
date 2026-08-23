from sixpack.ui import theme


def test_new_tokens_exist():
    assert theme.SURFACE_LOW.startswith("#")
    assert theme.ACCENT_GLOW.startswith("#")
    assert isinstance(theme.BACKDROP_W, int) and theme.BACKDROP_W > 0
    assert isinstance(theme.BACKDROP_H, int) and theme.BACKDROP_H > 0
    assert 0.0 < theme.UNFOCUSED_OPACITY <= 1.0
    assert 0.0 <= theme.BACKDROP_DARKEN <= 1.0


def test_accent_unchanged():
    assert theme.ACCENT == "#4a9eff"


def test_stylesheet_builds():
    # STYLESHEET is an f-string; referencing any missing token would raise at import.
    assert "QWidget" in theme.STYLESHEET
    assert theme.SURFACE_LOW in theme.STYLESHEET or theme.GRADIENT_BG in theme.STYLESHEET


def test_icon_codepoints_are_distinct_single_characters():
    codepoints = [
        theme.ICON_SKIP_PREVIOUS, theme.ICON_SKIP_NEXT, theme.ICON_PLAY,
        theme.ICON_PAUSE, theme.ICON_REPLAY_30, theme.ICON_FORWARD_30,
        theme.ICON_MENU_BOOK, theme.ICON_SPEED,
    ]
    assert all(len(c) == 1 for c in codepoints)
    assert len(set(codepoints)) == len(codepoints)  # no two icons share a codepoint


def test_load_icon_font_loads_the_real_bundled_font(qapp):
    """End-to-end regression against the real bundled asset (not mocked) --
    guards against ever breaking the asset's packaging or path resolution,
    which importlib.resources.files("sixpack") depends on staying correct
    for both a source checkout and an installed wheel."""
    family = theme.load_icon_font()
    assert family != ""
    assert family == theme.ICON_FONT_FAMILY
