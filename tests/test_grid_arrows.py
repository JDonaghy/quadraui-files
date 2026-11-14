"""Black-box coverage for keyboard arrow navigation in the file list, which
has key focus from the start (Finder/Explorer open with the list focused):
Up/Down move the row selection, Right opens the selected folder *in place*,
Left goes up to the parent (selecting the folder you came from) and, at a
filesystem root, hands key focus to the sidebar.

The engine only rewrites Up/Down into `RowSelected` (and Enter into
`RowActivated`) once a real mouse `MouseDown` focused the table, so the
keyboard path is app-side (`_on_grid_arrow`); the clicked-focus path it
mirrors is covered by test_detail_click/test_keys_after_click."""

from pathlib import Path

from conftest import click as _click
from conftest import find_row as _find_row
from quadraui_files import FileManager
from quadraui_files.app import DOWN_KEY, LEFT_KEY, RIGHT_KEY, UP_KEY, _key_event


def test_arrows_move_the_grids_selection_from_the_start(sample_tree):
    fm = FileManager(sample_tree, width=120, height=30)
    assert fm.table_focus, "the list should have key focus from the start"

    fm.step(_key_event(DOWN_KEY))

    assert fm.selected_file is not None and fm.selected_file.name == "alpha"
    assert fm.cursor.path == sample_tree, "Down navigated instead of selecting"
    assert fm.selected_file.name in fm.app.screen(), "selection never painted"

    fm.step(_key_event(DOWN_KEY))
    assert fm.selected_file.name == "beta"
    fm.step(_key_event(UP_KEY))
    assert fm.selected_file.name == "alpha"


def test_right_opens_the_selected_folder_in_place_and_left_goes_back_up(sample_tree):
    fm = FileManager(sample_tree, width=120, height=30)
    fm.step(_key_event(DOWN_KEY))  # select alpha

    fm.step(_key_event(RIGHT_KEY))

    assert len(fm.open) == 1, "Right opened a new tab instead of navigating in place"
    assert fm.cursor.name == "alpha"
    assert "notes.txt" in fm.app.screen(), "alpha's listing never showed"

    fm.step(_key_event(LEFT_KEY))  # up to the parent

    assert fm.cursor.path == sample_tree
    assert len(fm.open) == 1
    assert fm.selected_file is not None and fm.selected_file.name == "alpha", (
        "going up did not select the folder we came from"
    )


def test_left_at_a_filesystem_root_hands_key_focus_to_the_sidebar(sample_tree):
    fm = FileManager(sample_tree, width=120, height=30)
    fm._navigate(fm._node_for(Path(sample_tree.anchor)))  # straight to `/`

    fm.step(_key_event(LEFT_KEY))  # nothing above a root

    assert fm.table_focus is False
    assert "sidebar" in fm.message, "no hint that the arrows moved to the sidebar"


def test_right_on_a_file_row_only_hints_at_enter(sample_tree):
    fm = FileManager(sample_tree, width=120, height=30)
    for _ in range(3):  # alpha, beta, readme.txt
        fm.step(_key_event(DOWN_KEY))

    assert fm.selected_file.name == "readme.txt"
    fm.step(_key_event(RIGHT_KEY))

    assert fm.cursor.path == sample_tree, "Right navigated somewhere for a file row"
    assert "press Enter" in fm.message


def test_left_after_a_row_click_still_goes_up(sample_tree):
    """Left/Right are the two arrows the engine never rewrites, so they reach
    the app even with the table focused by a real click."""
    fm = FileManager(sample_tree, width=120, height=30)
    fm.step(_key_event(DOWN_KEY))
    fm.step(_key_event(RIGHT_KEY))  # into alpha

    _click(fm, *_find_row(fm, "notes.txt"))  # a real click focuses alpha's table
    fm.step(_key_event(LEFT_KEY))

    assert fm.cursor.path == sample_tree, "Left did not go up"
