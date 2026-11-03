"""T2 black-box tests: the bottom-panel filter box, F2 inline rename, and
details-table column sort -- all driven headlessly through `FileManager.step`
(push-and-dispatch plus the deferred-action drain, same as the other suites;
see `app.py`'s module doc)."""

import time

from quadraui_files import FileManager
from quadraui_files.app import ENTER_KEY, _key_event, ensure_loaded

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


# --- F2 rename -----------------------------------------------------------


def _select_file(fm: FileManager, name: str) -> None:
    folder = fm.open[fm.active_tab]
    idx = [c.name for c in fm._visible_children(folder)].index(name)
    fm.step({"DataTable": [f"fm:grid:{fm.active_tab}", {"RowActivated": {"idx": idx}}]})


def test_f2_renames_the_selected_file_on_disk_and_in_the_listing(sample_tree):
    fm = FileManager(sample_tree)
    _open_root_tab(fm)
    _select_file(fm, "readme.txt")

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
    _select_file(fm, "readme.txt")

    fm.step(_key_event(F2_KEY))
    _type(fm, "xxx")
    fm.step(_key_event(ESCAPE_KEY))

    assert fm.edit_mode is None
    assert (sample_tree / "readme.txt").exists()
    assert "readme.txt" in _listing(fm)


def test_f2_renaming_a_folder_updates_children_paths_too(sample_tree):
    fm = FileManager(sample_tree)
    fm.cursor = next(c for c in fm._visible()[1] if c.name == "alpha")
    ensure_loaded(fm.cursor)  # load "notes.txt" so its cached path is checkable below

    fm.step(_key_event(F2_KEY))
    assert fm.edit_mode == "rename"
    assert fm.edit_text == "alpha"
    for _ in range(5):
        fm.step(_key_event(BACKSPACE_KEY))
    _type(fm, "gamma")
    fm.step(_key_event(ENTER_KEY))

    assert not (sample_tree / "alpha").exists()
    assert (sample_tree / "gamma" / "notes.txt").exists()
    assert fm.cursor.name == "gamma"
    assert fm.cursor.path == sample_tree / "gamma"
    # The child's cached path was fixed up too, not left pointing at the
    # now-missing "alpha" directory.
    gamma = fm.cursor
    assert gamma.children is not None
    child = gamma.children[0]
    assert child.path == sample_tree / "gamma" / "notes.txt"


# --- column sort -----------------------------------------------------------


def test_clicking_a_header_sorts_the_table_and_clicking_again_reverses_it(
    sample_tree, tmp_path
):
    # `sample_tree`'s "alpha"/"beta" sort identically by name and by size
    # (both directories, size None) -- use distinct file sizes/mtimes so a
    # Size-column sort has an unambiguous order to assert on.
    (sample_tree / "small.bin").write_bytes(b"x")
    time.sleep(0.01)
    (sample_tree / "big.bin").write_bytes(b"x" * 1000)

    fm = FileManager(sample_tree)
    _open_root_tab(fm)

    fm.step({"DataTable": [f"fm:grid:0", {"HeaderClicked": {"col": 1}}]})
    ascending = _listing(fm)
    assert ascending.index("small.bin") < ascending.index("big.bin")

    fm.step({"DataTable": [f"fm:grid:0", {"HeaderClicked": {"col": 1}}]})
    descending = _listing(fm)
    assert descending.index("big.bin") < descending.index("small.bin")
    assert descending == list(reversed(ascending))
