"""Black-box coverage for Explorer-style browsing in the tabs: opening a
folder navigates the tab in place (with Back/Forward history), Up selects the
folder you came from, the address bar's breadcrumbs jump to an ancestor,
`t`/`w` open and close tabs (the last one stays), and the safety rules --
nothing selected means nothing to trash, and a trashed folder a tab is
showing moves that tab to its parent."""

import os
import sys
from pathlib import Path

import pytest

from conftest import activate_child, double_click, find_row
from quadraui_files import FileManager
from quadraui_files.app import DELETE_KEY, LEFT_KEY, _key_event

BACKSPACE_KEY = {"Named": "Backspace"}


def _char(c: str) -> dict:
    return _key_event({"Char": c})


def test_double_clicking_a_folder_navigates_in_place_and_records_history(sample_tree):
    fm = FileManager(sample_tree, width=120, height=30)

    double_click(fm, *find_row(fm, "alpha/"))

    assert len(fm.open) == 1, "a folder opened a new tab instead of navigating in place"
    assert fm.cursor.name == "alpha"
    # "otes.txt": the clicked table's focus ring currently paints over the
    # first column (a known quadraui gap, filed separately).
    assert "otes.txt" in fm.app.screen()
    assert [n.path for n in fm.back[0]] == [sample_tree]


def test_back_and_forward_walk_the_tabs_history(sample_tree):
    fm = FileManager(sample_tree, width=120, height=30)
    activate_child(fm, "alpha")

    fm.step(_key_event(BACKSPACE_KEY))
    assert fm.cursor.path == sample_tree
    assert fm.selected_file is not None and fm.selected_file.name == "alpha"

    fm.step(_char("]"))
    assert fm.cursor.name == "alpha"
    assert "notes.txt" in fm.app.screen()

    fm.step(_char("["))
    assert fm.cursor.path == sample_tree


def test_back_with_no_history_says_so(sample_tree):
    fm = FileManager(sample_tree, width=120, height=30)
    fm.step(_key_event(BACKSPACE_KEY))
    assert fm.cursor.path == sample_tree
    assert "nothing to go back to" in fm.app.screen()


def test_left_goes_up_and_selects_the_folder_we_came_from(sample_tree):
    fm = FileManager(sample_tree / "alpha", width=120, height=30)

    fm.step(_key_event(LEFT_KEY))

    assert fm.cursor.path == sample_tree
    assert fm.selected_file is not None and fm.selected_file.name == "alpha"


def test_left_at_a_filesystem_root_hands_focus_to_the_sidebar(sample_tree):
    fm = FileManager(Path(sample_tree.anchor), width=120, height=30)
    fm.step(_key_event(LEFT_KEY))
    assert fm.table_focus is False


def test_a_breadcrumb_click_jumps_to_that_ancestor(sample_tree):
    fm = FileManager(sample_tree / "alpha", width=160, height=30)
    depth = len(sample_tree.parts) - 1  # crumb 0 is the filesystem root

    fm.step({"StatusBar": ["fm:addr:0", {"SegmentClicked": {"id": f"fm:crumb:{depth}"}}]})

    assert fm.cursor.path == sample_tree
    assert fm.selected_file is not None and fm.selected_file.name == "alpha"
    assert fm.back[0] and fm.back[0][-1].name == "alpha"


def test_the_address_bar_shows_the_path_as_breadcrumbs(sample_tree):
    """Asserted on the descriptor: pytest's long temp path doesn't fit the
    bar, which (no breadcrumb primitive yet) clips instead of eliding."""
    fm = FileManager(sample_tree / "alpha", width=120, height=30)
    segments = fm._address_leaf(0, fm.cursor)["status_bar"]["left_segments"]
    crumbs = [s["text"].strip() for s in segments if s["text"] != "›"]
    assert crumbs[-2:] == [sample_tree.name, "alpha"]
    assert [s.get("action_id") for s in segments][-1] is None, "the current folder isn't a link"
    assert "alpha" in fm.app.screen()


def test_t_opens_a_tab_w_closes_it_and_the_last_tab_stays(sample_tree):
    fm = FileManager(sample_tree, width=120, height=30)
    fm.step({"DataTable": ["fm:grid:0", {"RowSelected": {"idx": 0}}]})  # select alpha

    fm.step(_char("t"))
    assert [n.name for n in fm.open] == [sample_tree.name, "alpha"]
    assert fm.active_tab == 1
    assert "notes.txt" in fm.app.screen()

    fm.step({"TabBar": ["fm:tabs", {"TabActivated": {"index": 0}}]})
    assert fm.active_tab == 0 and fm.cursor.path == sample_tree

    fm.step(_char("w"))
    assert [n.name for n in fm.open] == ["alpha"]

    fm.step(_char("w"))
    assert len(fm.open) == 1, "the last tab closed"
    assert "the last tab stays open" in fm.app.screen()


def test_no_argument_opens_the_home_folder():
    fm = FileManager(None, width=120, height=30)
    assert fm.cursor.path == Path.home()


def test_delete_with_nothing_selected_does_nothing(sample_tree):
    fm = FileManager(sample_tree, width=160, height=30)
    fm.step(_key_event(DELETE_KEY))
    assert fm._delete_target is None
    assert "select something" in fm.app.screen()


def test_trashing_a_folder_a_tab_shows_moves_that_tab_to_its_parent(sample_tree):
    fm = FileManager(sample_tree, width=120, height=30)
    fm.step({"DataTable": ["fm:grid:0", {"RowSelected": {"idx": 0}}]})  # alpha
    fm.step(_char("t"))  # alpha in a second tab
    fm.step({"TabBar": ["fm:tabs", {"TabActivated": {"index": 0}}]})
    fm.step({"DataTable": ["fm:grid:0", {"RowSelected": {"idx": 0}}]})  # alpha again

    fm.step(_key_event(DELETE_KEY))
    fm.step({"MessageDialogResolved": "delete"})

    assert not (sample_tree / "alpha").exists()
    assert [n.path for n in fm.open] == [sample_tree, sample_tree]


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0, reason="needs POSIX perms, non-root")
def test_an_unreadable_folder_says_why(sample_tree):
    locked = sample_tree / "locked"
    locked.mkdir()
    locked.chmod(0)
    try:
        fm = FileManager(locked, width=160, height=30)
        assert "Can't read" in fm.app.screen()
    finally:
        locked.chmod(0o755)
