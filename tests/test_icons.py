"""F6 black-box coverage: folder/file codicon markers in the tree and the
details pane. The TUI backend defaults `nerd_fonts_enabled` off (its own
conservative default -- see `app.py`'s `_nerd_fonts_enabled` doc), so every
other suite in this repo exercises the ASCII-fallback half of these markers
(`"/"` for a folder, `" "` for a file) without ever turning a Nerd Font on.
This file is the one place that flips it, to cover the glyph half too."""

from quadraui_files import FileManager
from quadraui_files.app import (
    _CODICON_CODE_GLYPH,
    _CODICON_FILE_GLYPH,
    _CODICON_FOLDER_GLYPH,
    _CODICON_JSON_GLYPH,
    _CODICON_MD_GLYPH,
    _CODICON_MEDIA_GLYPH,
    _CODICON_PDF_GLYPH,
    _CODICON_ZIP_GLYPH,
    DOWN_KEY,
    ENTER_KEY,
    _key_event,
)


def _enable_nerd_fonts(fm: FileManager) -> None:
    """Flips the backend's own nerd-fonts flag and this app's one-time
    cached read of it (see `FileManager.__init__`'s own doc on why it's
    cached rather than read live from `_render`) -- both top-level calls,
    safe outside a handler/render dispatch, same as `register_accelerator`."""
    fm.app.set_nerd_fonts(True)
    fm._nerd_fonts_enabled = fm.app.nerd_fonts_enabled()


def test_tree_folder_row_shows_the_folder_codicon_once_nerd_fonts_are_on(tmp_path):
    # A fixed, short root name, unlike `sample_tree` (which hands back
    # `tmp_path` itself, named after this test's own -- long -- node id):
    # this test is about the codicon marker, not about how much of a long
    # name the narrowed, bordered tree pane can still fit -- see
    # `tests/test_tree_click.py`'s own `test_root_row_stays_painted_on_screen_
    # after_a_tree_click` for the same reasoning.
    root = tmp_path / "root"
    root.mkdir()
    (root / "alpha").mkdir()
    fm = FileManager(root, width=120, height=20)
    assert f"/ {fm.cursor.name}" in fm.app.screen(), "ASCII fallback by default"

    _enable_nerd_fonts(fm)
    fm.step(_key_event(DOWN_KEY))  # moves the cursor onto "alpha"; also forces a repaint

    assert f"{_CODICON_FOLDER_GLYPH} {fm.cursor.name}" in fm.app.screen()


def test_details_row_shows_the_file_codicon_once_nerd_fonts_are_on(tmp_path):
    # A fixed, short root name -- see the previous test's own doc on why.
    root = tmp_path / "root"
    root.mkdir()
    (root / "alpha").mkdir()
    (root / "readme.txt").write_text("hello")
    fm = FileManager(root, width=120, height=20)
    fm.step(_key_event(ENTER_KEY))  # open the root tab
    assert "readme.txt" in fm.app.screen()

    _enable_nerd_fonts(fm)
    # A details-row selection forces the repaint this assertion needs. (The
    # grid holds key focus after the open -- see `app.py`'s
    # `_on_grid_arrow` -- so this Down moves the row selection, not the
    # tree cursor; either repaints, and no tooltip is involved.)
    fm.step(_key_event(DOWN_KEY))

    assert f"{_CODICON_FILE_GLYPH} readme.txt" in fm.app.screen()
    assert f"{_CODICON_FOLDER_GLYPH} alpha/" in fm.app.screen()


def test_details_rows_get_type_specific_codicons_once_nerd_fonts_are_on(tmp_path):
    """The per-row marker says what kind of file each row is (`_codicon_glyph`),
    not just "file": media for images/audio/video, the dedicated PDF, zip,
    JSON and Markdown glyphs, code by extension, and the plain file glyph
    only for what genuinely is one. One row of each, one screen assertion
    per row."""
    # A fixed, short root name -- see the first test's own doc on why.
    root = tmp_path / "root"
    root.mkdir()
    (root / "app.py").write_text("print()")
    (root / "data.json").write_text("{}")
    (root / "doc.pdf").write_bytes(b"%PDF-1.4\n")
    (root / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (root / "app.zip").write_bytes(b"PK\x03\x04")
    (root / "README.md").write_text("# hi")
    (root / "plain.txt").write_text("hello")
    fm = FileManager(root, width=160, height=24)
    fm.step(_key_event(ENTER_KEY))  # open the root tab; key focus lands in its grid
    assert "app.py" in fm.app.screen()

    _enable_nerd_fonts(fm)
    fm.step(_key_event(DOWN_KEY))  # a row selection, to force the repaint

    screen = fm.app.screen()
    for glyph, name in (
        (_CODICON_CODE_GLYPH, "app.py"),
        (_CODICON_JSON_GLYPH, "data.json"),
        (_CODICON_PDF_GLYPH, "doc.pdf"),
        (_CODICON_MEDIA_GLYPH, "logo.png"),
        (_CODICON_ZIP_GLYPH, "app.zip"),
        (_CODICON_MD_GLYPH, "README.md"),
        (_CODICON_FILE_GLYPH, "plain.txt"),
    ):
        assert f"{glyph} {name}" in screen, f"no {name!r} marker painted"


def test_untyped_files_still_get_the_plain_file_codicon(tmp_path):
    # No extension at all: `mimetypes` can't place "Makefile"-style names,
    # and the honest marker for them is the plain file glyph (see
    # `_codicon_glyph`'s own doc) -- same label honesty the Kind column has.
    root = tmp_path / "root"
    root.mkdir()
    (root / "Makefile").write_text("all:")
    fm = FileManager(root, width=120, height=20)
    fm.step(_key_event(ENTER_KEY))

    _enable_nerd_fonts(fm)
    fm.step(_key_event(DOWN_KEY))

    assert f"{_CODICON_FILE_GLYPH} Makefile" in fm.app.screen()
