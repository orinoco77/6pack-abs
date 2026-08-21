from sixpack.ui import theme


def test_new_tokens_exist():
    assert theme.SURFACE_LOW.startswith("#")
    assert theme.ACCENT_GLOW.startswith("#")
    assert isinstance(theme.BACKDROP_W, int) and theme.BACKDROP_W > 0
    assert isinstance(theme.BACKDROP_H, int) and theme.BACKDROP_H > 0
    assert isinstance(theme.FOCUS_ANIM_MS, int)
    assert 0.0 < theme.UNFOCUSED_OPACITY <= 1.0
    assert 0.0 <= theme.BACKDROP_DARKEN <= 1.0


def test_accent_unchanged():
    assert theme.ACCENT == "#4a9eff"


def test_stylesheet_builds():
    # STYLESHEET is an f-string; referencing any missing token would raise at import.
    assert "QWidget" in theme.STYLESHEET
    assert theme.SURFACE_LOW in theme.STYLESHEET or theme.GRADIENT_BG in theme.STYLESHEET
