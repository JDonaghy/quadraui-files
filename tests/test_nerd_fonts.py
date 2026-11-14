"""Black-box coverage for nerd-font glyphs in the TUI: sidebar places paint
their plain-Unicode fallback by default and their codicon once nerd fonts
are on, and `detect_nerd_fonts` guesses from the terminal's environment
(Ghostty/kitty/WezTerm bundle the symbols) with an env override."""

from quadraui_files.app import FileManager, Place, PlaceSection, _key_event, detect_nerd_fonts


def _fm(root) -> FileManager:
    sections = [PlaceSection("Favorites", (Place("Home", root, "account", "⌂"),))]
    return FileManager(root, width=100, height=20, sections=sections)


def _sidebar_line(fm: FileManager) -> str:
    return next(line for line in fm.app.screen().splitlines() if "Home" in line)


def test_sidebar_place_paints_its_fallback_without_nerd_fonts(sample_tree):
    fm = _fm(sample_tree)
    assert "⌂ Home" in _sidebar_line(fm)


def test_sidebar_place_paints_its_codicon_with_nerd_fonts(sample_tree):
    fm = _fm(sample_tree)
    fm.set_nerd_fonts(True)
    fm.step(_key_event({"Char": "z"}))  # an unbound key: just a repaint
    line = _sidebar_line(fm)
    assert "⌂" not in line
    glyph = line[line.index("Home") - 2]
    assert 0xE000 <= ord(glyph) <= 0xF8FF, f"expected a PUA codicon glyph, got {glyph!r} in {line!r}"


def test_detect_nerd_fonts_from_the_terminal_environment():
    assert detect_nerd_fonts({"TERM_PROGRAM": "ghostty"})
    assert detect_nerd_fonts({"TERM": "xterm-kitty"})
    assert detect_nerd_fonts({"TERM_PROGRAM": "WezTerm"})
    assert detect_nerd_fonts({"GHOSTTY_RESOURCES_DIR": "/x"})
    assert not detect_nerd_fonts({"TERM_PROGRAM": "Apple_Terminal", "TERM": "xterm-256color"})


def test_detect_nerd_fonts_env_override_wins():
    assert detect_nerd_fonts({"QUADRAUI_FILES_NERD_FONTS": "1", "TERM_PROGRAM": "Apple_Terminal"})
    assert not detect_nerd_fonts({"QUADRAUI_FILES_NERD_FONTS": "0", "TERM_PROGRAM": "ghostty"})
