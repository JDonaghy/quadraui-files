"""T2 black-box tests: the bottom-panel filter box, F2 inline rename, and
details-table column sort -- all driven headlessly through `FileManager.step`
(push-and-dispatch plus the deferred-action drain, same as the other suites;
see `app.py`'s module doc)."""

import pytest
from conftest import activate_child as _activate_file
from conftest import click as _click
from conftest import find_row as _find_row

from quadraui_files import FileManager
from quadraui_files.app import DELETE_KEY, ENTER_KEY, UNDO_SUPPORTED, _key_event, ensure_loaded

ESCAPE_KEY = {"Named": "Escape"}
BACKSPACE_KEY = {"Named": "Backspace"}
F2_KEY = {"Named": {"F": 2}}


def _char_event(ch: str) -> dict:
    """A plain-character keystroke, exactly what a real `--tui` session
    sends for typed text (crossterm has no separate `CharTyped` variant --
    see `app.py`'s `_handle_edit_key` doc)."""
    return _key_event({"Char": ch})


def _type(fm: FileManager, text: str) -> None:
    for ch in text:
        fm.step(_char_event(ch))


def _open_root_tab(fm: FileManager) -> None:
    fm.step(_key_event(ENTER_KEY))


def _listing(fm: FileManager) -> list[str]:
    folder = fm.open[fm.active_tab]
    return [c.name for c in fm._visible_children(folder)]


# --- filter/search ------------------------------------------------------


def test_typing_into_the_filter_narrows_the_listing_live(sample_tree):
    fm = FileManager(sample_tree)
    _open_root_tab(fm)
    assert sorted(_listing(fm)) == ["alpha", "beta", "readme.txt"]

    fm.step(_char_event("/"))
    assert fm.edit_mode == "filter"

    _type(fm, "re")
    assert _listing(fm) == ["readme.txt"]
    assert "readme.txt" in fm.app.screen()
    # The filter narrows the details table only, not the folders-only tree
    # (which always lists "alpha" with no trailing "/"); "alpha/" is the
    # table row's own marker for a navigable subfolder.
    assert "alpha/" not in fm.app.screen()
    assert "Filter: re" in fm.app.screen()


def test_escape_clears_the_filter_and_restores_the_full_listing(sample_tree):
    fm = FileManager(sample_tree)
    _open_root_tab(fm)

    fm.step(_char_event("/"))
    _type(fm, "re")
    assert _listing(fm) == ["readme.txt"]

    fm.step(_key_event(ESCAPE_KEY))
    assert fm.edit_mode is None
    assert fm.filter_text == ""
    assert sorted(_listing(fm)) == ["alpha", "beta", "readme.txt"]
    assert "alpha/" in fm.app.screen()  # the filtered-out row is back on screen


def test_enter_closes_the_filter_box_but_keeps_the_query_applied(sample_tree):
    fm = FileManager(sample_tree)
    _open_root_tab(fm)

    fm.step(_char_event("/"))
    _type(fm, "al")
    fm.step(_key_event(ENTER_KEY))

    assert fm.edit_mode is None
    assert fm.filter_text == "al"
    assert _listing(fm) == ["alpha"]
    assert "filter:" in fm.app.screen().lower()


def test_backspace_narrows_the_filter_buffer(sample_tree):
    fm = FileManager(sample_tree)
    _open_root_tab(fm)

    fm.step(_char_event("/"))
    _type(fm, "readmex")
    assert _listing(fm) == []  # no match

    fm.step(_key_event(BACKSPACE_KEY))
    assert fm.edit_text == "readme"
    assert _listing(fm) == ["readme.txt"]
    assert "readme.txt" in fm.app.screen()


# --- F2 rename -----------------------------------------------------------


def test_f2_renames_the_selected_file_on_disk_and_in_the_listing(sample_tree):
    fm = FileManager(sample_tree)
    _open_root_tab(fm)
    _activate_file(fm, "readme.txt")

    fm.step(_key_event(F2_KEY))
    assert fm.edit_mode == "rename"
    assert fm.edit_text == "readme.txt"
    assert "Rename: readme.txt" in fm.app.screen()

    # Replace the extension: backspace off ".txt", type ".md".
    for _ in range(4):
        fm.step(_key_event(BACKSPACE_KEY))
    _type(fm, ".md")
    fm.step(_key_event(ENTER_KEY))

    assert fm.edit_mode is None
    assert not (sample_tree / "readme.txt").exists()
    assert (sample_tree / "readme.md").exists()
    assert (sample_tree / "readme.md").read_text() == "hello"
    assert "readme.md" in _listing(fm)
    assert "readme.md" in fm.app.screen()


def test_f2_escape_cancels_the_rename_leaving_the_file_untouched(sample_tree):
    fm = FileManager(sample_tree)
    _open_root_tab(fm)
    _activate_file(fm, "readme.txt")

    fm.step(_key_event(F2_KEY))
    _type(fm, "xxx")
    fm.step(_key_event(ESCAPE_KEY))

    assert fm.edit_mode is None
    assert (sample_tree / "readme.txt").exists()
    assert "readme.txt" in _listing(fm)
    assert "readme.txt" in fm.app.screen()


def test_f2_rename_with_a_path_separator_is_rejected_not_raised(sample_tree):
    """A slash in the typed name would make `Path.with_name` raise
    `ValueError` if unguarded -- the real crash this file manager must
    never hit on a plausible keystroke (see `app.py`'s `_invalid_rename_name`
    doc). It must be reported via the status message, not escape the
    handler."""
    fm = FileManager(sample_tree)
    _open_root_tab(fm)
    _activate_file(fm, "readme.txt")

    fm.step(_key_event(F2_KEY))
    for _ in range(len("readme.txt")):
        fm.step(_key_event(BACKSPACE_KEY))
    _type(fm, "sub/name")
    fm.step(_key_event(ENTER_KEY))  # must not raise out of the handler

    assert fm.edit_mode is None
    assert (sample_tree / "readme.txt").exists()
    assert "readme.txt" in _listing(fm)
    assert "separator" in fm.app.screen()


def test_f2_rename_to_a_bare_dot_is_rejected_not_raised(sample_tree):
    """`Path("x").with_name(".")` raises `ValueError` too -- same guard,
    different plausible keystroke."""
    fm = FileManager(sample_tree)
    _open_root_tab(fm)
    _activate_file(fm, "readme.txt")

    fm.step(_key_event(F2_KEY))
    for _ in range(len("readme.txt")):
        fm.step(_key_event(BACKSPACE_KEY))
    _type(fm, ".")
    fm.step(_key_event(ENTER_KEY))  # must not raise out of the handler

    assert fm.edit_mode is None
    assert (sample_tree / "readme.txt").exists()
    assert "readme.txt" in _listing(fm)


def test_f2_rename_to_a_hidden_name_is_rejected(sample_tree):
    """A leading dot is rejected outright: `load_children` skips dotfiles,
    so a renamed entry would vanish from the listing on the next refresh."""
    fm = FileManager(sample_tree)
    _open_root_tab(fm)
    _activate_file(fm, "readme.txt")

    fm.step(_key_event(F2_KEY))
    for _ in range(len("readme.txt")):
        fm.step(_key_event(BACKSPACE_KEY))
    _type(fm, ".hidden")
    fm.step(_key_event(ENTER_KEY))

    assert fm.edit_mode is None
    assert (sample_tree / "readme.txt").exists()
    assert not (sample_tree / ".hidden").exists()
    assert "readme.txt" in _listing(fm)
    assert "hidden" in fm.app.screen()


def test_f2_renaming_a_folder_updates_children_paths_too(sample_tree):
    fm = FileManager(sample_tree)
    alpha = next(c for c in fm.cursor.children if c.name == "alpha")
    ensure_loaded(alpha)  # load "notes.txt" so its cached path is checkable below
    fm.step({"DataTable": ["fm:grid:0", {"RowSelected": {"idx": 0}}]})  # select alpha
    assert fm.selected_file is alpha

    fm.step(_key_event(F2_KEY))
    assert fm.edit_mode == "rename"
    assert fm.edit_text == "alpha"
    for _ in range(5):
        fm.step(_key_event(BACKSPACE_KEY))
    _type(fm, "gamma")
    fm.step(_key_event(ENTER_KEY))

    assert not (sample_tree / "alpha").exists()
    assert (sample_tree / "gamma" / "notes.txt").exists()
    assert alpha.name == "gamma"
    assert alpha.path == sample_tree / "gamma"
    # The child's cached path was fixed up too, not left pointing at the
    # now-missing "alpha" directory.
    gamma = alpha
    assert gamma.children is not None
    child = gamma.children[0]
    assert child.path == sample_tree / "gamma" / "notes.txt"


# --- non-key events during an open filter/rename box ----------------------


@pytest.mark.skipif(not UNDO_SUPPORTED, reason="no programmatic trash restore on this host (macOS)")
def test_toast_undo_still_works_while_the_filter_box_is_open(sample_tree):
    """Trash a file, open the filter box before clicking the undo toast's
    button -- `_handle_edit_key` must let the non-key `ToastActionClicked`
    event fall through to the normal dispatch rather than swallowing it the
    way it swallows a keystroke."""
    fm = FileManager(sample_tree)
    _open_root_tab(fm)
    _activate_file(fm, "readme.txt")
    fm.step(_key_event(DELETE_KEY))
    fm.step(_key_event(ENTER_KEY))  # confirm the trash; the undo toast appears
    assert not (sample_tree / "readme.txt").exists()

    fm.step(_char_event("/"))  # open the filter box while the toast is still up
    assert fm.edit_mode == "filter"

    fm.step({"ToastActionClicked": "undo"})

    assert (sample_tree / "readme.txt").exists(), "Undo should still work while filtering"
    assert fm.edit_mode == "filter"  # the box itself is untouched by the click


def test_double_clicking_a_filtered_row_opens_it_without_closing_the_box_first(sample_tree):
    """A `DataTable`/`RowDoubleClicked` is a non-key event too, so the
    natural "find and open" flow -- type a filter, then double-click the
    matching row -- works without first pressing Enter to close the box."""
    fm = FileManager(sample_tree)
    _open_root_tab(fm)

    fm.step(_char_event("/"))
    _type(fm, "al")
    assert _listing(fm) == ["alpha"]

    fm.step({"DataTable": ["fm:grid:0", {"RowDoubleClicked": {"idx": 0}}]})

    assert fm.edit_mode == "filter"  # the double-click didn't close the box
    assert any(f.name == "alpha" for f in fm.open)  # but it did drill in


# --- a real click, then the edit box's own keyboard ------------------------
#
# A click on a details-table row moves the engine's own keyboard focus onto
# the table (not just this app's `table_focus` bookkeeping), the same
# click-to-focus every tab stop gets. Reaching these two cases needs that
# real engine focus, which `_activate_file`'s hand-built `RowActivated`
# never sets up -- so they drive the click through `conftest.click` at
# painted coordinates, same as `tests/test_detail_click.py`.


def test_f2_rename_after_a_row_click_still_commits_on_enter(sample_tree):
    """Clicking a row, then F2, then Enter must commit the rename -- not
    hand the file to the OS, which is what a focused table's own Enter
    handling would do if the edit box's keyboard ownership weren't
    respected while it's open."""
    fm = FileManager(sample_tree)
    _open_root_tab(fm)

    x, y = _find_row(fm, "readme.txt")
    _click(fm, x, y)
    assert fm.selected_file is not None and fm.selected_file.name == "readme.txt"

    fm.step(_key_event(F2_KEY))
    assert fm.edit_mode == "rename"
    for _ in range(4):
        fm.step(_key_event(BACKSPACE_KEY))
    _type(fm, ".md")
    fm.step(_key_event(ENTER_KEY))

    assert fm.edit_mode is None, "Enter must commit the rename, not open the file"
    assert fm.actions.opened == []
    assert (sample_tree / "readme.md").exists()
    assert not (sample_tree / "readme.txt").exists()


def test_filter_after_a_row_click_still_closes_on_enter(sample_tree):
    """Clicking a row that the filter query still matches, then Enter, must
    close the filter box -- not open that row with the OS."""
    fm = FileManager(sample_tree)
    _open_root_tab(fm)

    x, y = _find_row(fm, "readme.txt")
    _click(fm, x, y)
    assert fm.selected_file is not None and fm.selected_file.name == "readme.txt"

    fm.step(_char_event("/"))
    _type(fm, "readme")
    assert _listing(fm) == ["readme.txt"]

    fm.step(_key_event(ENTER_KEY))

    assert fm.edit_mode is None, "Enter must close the filter box, not open the file"
    assert fm.actions.opened == []
    assert fm.filter_text == "readme"


# --- column sort -----------------------------------------------------------


def test_clicking_a_header_sorts_the_table_and_clicking_again_reverses_it(sample_tree):
    # `sample_tree`'s "alpha"/"beta" sort identically by name and by size
    # (both directories, size None) -- distinct file sizes give a Size-column
    # sort an unambiguous order to assert on.
    (sample_tree / "small.bin").write_bytes(b"x")
    (sample_tree / "big.bin").write_bytes(b"x" * 1000)

    fm = FileManager(sample_tree)
    _open_root_tab(fm)

    fm.step({"DataTable": ["fm:grid:0", {"HeaderClicked": {"col": 1}}]})
    ascending = _listing(fm)
    assert ascending.index("small.bin") < ascending.index("big.bin")
    screen = fm.app.screen()
    assert screen.index("small.bin") < screen.index("big.bin")
    assert "Size ▲" in screen  # the active sort column/direction indicator

    fm.step({"DataTable": ["fm:grid:0", {"HeaderClicked": {"col": 1}}]})
    descending = _listing(fm)
    assert descending.index("big.bin") < descending.index("small.bin")
    assert descending == list(reversed(ascending))
    screen = fm.app.screen()
    assert screen.index("big.bin") < screen.index("small.bin")
    assert "Size ▼" in screen
