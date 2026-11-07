"""F6 black-box coverage: folder/file codicon markers in the tree and the
details pane. The TUI backend defaults `nerd_fonts_enabled` off (its own
conservative default -- see `app.py`'s `_nerd_fonts_enabled` doc), so every
other suite in this repo exercises the ASCII-fallback half of these markers
(`"/"` for a folder, `" "` for a file) without ever turning a Nerd Font on.
This file is the one place that flips it, to cover the glyph half too."""

from quadraui_files import FileManager
from quadraui_files.app import (
    _CODICON_FILE_GLYPH,
    _CODICON_FOLDER_GLYPH,
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
    # A fixed, short root name -- see the previous test's own doc on why;
    # here a long one pushes the tree's own (unrelated) pseudo-hover
    # tooltip box wide enough to overlap and truncate the details column
    # this test asserts on.
    root = tmp_path / "root"
    root.mkdir()
    (root / "alpha").mkdir()
    (root / "readme.txt").write_text("hello")
    fm = FileManager(root, width=120, height=20)
    fm.step(_key_event(ENTER_KEY))  # open the root tab
    assert "readme.txt" in fm.app.screen()

    _enable_nerd_fonts(fm)
    # A tree-cursor move forces the repaint this assertion needs, without
    # selecting a details row -- but it also puts up the tree's own
    # pseudo-hover tooltip (see `_move`'s `_show_tree_tooltip` call),
    # which can overlap/overwrite the very cells being asserted on below
    # (it's sized off the cursored node's full absolute path). Dismissed
    # explicitly rather than relying on "the next event auto-dismisses
    # it" (`hide_tooltip`'s own doc): the next event here is this test's
    # own assertion, not another `step`.
    fm.step(_key_event(DOWN_KEY))
    fm.app.hide_tooltip()

    assert f"{_CODICON_FILE_GLYPH} readme.txt" in fm.app.screen()
    assert f"{_CODICON_FOLDER_GLYPH} alpha/" in fm.app.screen()
