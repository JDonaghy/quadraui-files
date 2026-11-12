"""Black-box coverage for keyboard arrow navigation across both panes:
opening a folder hands key focus to its details table ("focus follows the
open"), so the arrows navigate that listing -- Up/Down move the row
selection, Right drills into the selected folder row, Left steps up to the
parent listing and, on the root listing, hands key focus back to the tree.

The engine only rewrites Up/Down into `RowSelected` (and Enter into
`RowActivated`) once a real mouse `MouseDown` focused the table, so this
keyboard handoff is app-side (`_on_grid_arrow`); the clicked-focus path it
mirrors is covered by test_detail_click/test_keys_after_click."""

from conftest import click as _click
from conftest import find_row as _find_row
from quadraui_files import FileManager
from quadraui_files.app import (
    DOWN_KEY,
    ENTER_KEY,
    LEFT_KEY,
    RIGHT_KEY,
    UP_KEY,
    _key_event,
)


def _open_root_tab(fm: FileManager) -> None:
    """Open the root folder's listing; key focus follows into its table."""
    fm.step(_key_event(ENTER_KEY))
    assert fm.table_focus, "opening a folder did not hand key focus to its grid"
    assert [n.name for n in fm.open] == [fm.root.name]


def test_arrows_after_an_open_move_the_grids_selection_not_the_tree(sample_tree):
    fm = FileManager(sample_tree, width=120, height=30)
    _open_root_tab(fm)

    fm.step(_key_event(DOWN_KEY))

    assert fm.selected_file is not None and fm.selected_file.name == "alpha"
    assert fm.cursor is fm.root, "Down walked the tree cursor from under grid focus"
    assert fm.selected_file.name in fm.app.screen(), "selection never painted"

    fm.step(_key_event(DOWN_KEY))
    assert fm.selected_file.name == "beta"
    fm.step(_key_event(UP_KEY))
    assert fm.selected_file.name == "alpha"


def test_right_drills_into_the_selected_folder_row_and_left_steps_back_up(sample_tree):
    fm = FileManager(sample_tree, width=120, height=30)
    _open_root_tab(fm)
    fm.step(_key_event(DOWN_KEY))  # select alpha

    fm.step(_key_event(RIGHT_KEY))

    assert [n.name for n in fm.open] == [fm.root.name, "alpha"], "Right did not open a new tab"
    assert fm.open[fm.active_tab].name == "alpha"
    assert "notes.txt" in fm.app.screen(), "alpha's listing never showed"

    fm.step(_key_event(LEFT_KEY))  # step up: the root tab is still open, focus it

    assert fm.open[fm.active_tab].name == fm.root.name
    assert len(fm.open) == 2, "Left duplicated a tab for the parent instead of focusing it"
    assert fm.selected_file.name == "alpha", "stepping up lost the row selection"


def test_left_on_the_root_listing_hands_key_focus_back_to_the_tree(sample_tree):
    fm = FileManager(sample_tree, width=120, height=30)
    _open_root_tab(fm)

    fm.step(_key_event(LEFT_KEY))  # nothing above the root

    assert fm.table_focus is False
    assert "tree" in fm.message, "no hint that the arrows moved back to the tree"

    fm.step(_key_event(DOWN_KEY))  # arrows walk the tree again

    assert fm.cursor.name == "alpha"
    assert fm.selected_file is None


def test_right_on_a_file_row_only_hints_at_enter(sample_tree):
    fm = FileManager(sample_tree, width=120, height=30)
    _open_root_tab(fm)
    for _ in range(3):  # alpha, beta, readme.txt
        fm.step(_key_event(DOWN_KEY))

    assert fm.selected_file.name == "readme.txt"
    fm.step(_key_event(RIGHT_KEY))

    assert len(fm.open) == 1, "Right opened something for a file row"
    assert "press Enter" in fm.message


def test_left_after_a_row_click_no_longer_collapses_the_tree(sample_tree):
    """Left/Right are the two arrows the engine never rewrites, so they reach
    the app even with the table focused by a real click -- they used to fall
    through and collapse/expand the *tree* cursor from under the grid. With
    key focus in the grid they step the listing and leave the tree alone."""
    fm = FileManager(sample_tree, width=120, height=30)
    _open_root_tab(fm)
    fm.step(_key_event(DOWN_KEY))
    fm.step(_key_event(RIGHT_KEY))  # drill into alpha: cursor is now alpha, expanded

    _click(fm, *_find_row(fm, "notes.txt"))  # a real click focuses alpha's table
    fm.step(_key_event(LEFT_KEY))

    assert fm.open[fm.active_tab].name == fm.root.name, "Left did not step up"
    assert fm.cursor.name == "alpha", "Left moved the tree cursor"
