"""Black-box coverage for "the grid lists the selected tree item": moving the
folder cursor -- keyboard Down/Up, Right's descend, Left's parent-jump --
shows that folder's contents in the details pane, exactly the way clicking
the tree row already did (`_show_folder_in_active_tab`, VS Code/Finder
sidebar behavior: selecting a folder is asking to see inside it). Opening a
*new* tab stays a deliberate action (Enter)."""

from quadraui_files import FileManager
from quadraui_files.app import DOWN_KEY, ENTER_KEY, LEFT_KEY, RIGHT_KEY, UP_KEY, _key_event


def test_moving_the_tree_cursor_shows_that_folder_in_the_grid(sample_tree):
    fm = FileManager(sample_tree, width=120, height=30)
    assert not fm.open, "sanity: nothing open before the first cursor move"

    fm.step(_key_event(DOWN_KEY))  # tree cursor -> alpha (grid unfocused)

    assert [n.name for n in fm.open] == ["alpha"], "the grid did not list the cursored folder"
    assert "notes.txt" in fm.app.screen(), "alpha's contents never painted"


def test_a_later_tree_move_replaces_the_active_tabs_folder(sample_tree):
    fm = FileManager(sample_tree, width=120, height=30)
    fm.step(_key_event(ENTER_KEY))  # open the root tab; key focus lands in its grid
    assert [n.name for n in fm.open] == [fm.root.name]

    fm.step(_key_event(LEFT_KEY))  # root listing: key focus back to the tree
    fm.step(_key_event(DOWN_KEY))  # tree cursor -> alpha

    assert len(fm.open) == 1, "a cursor move duplicated a tab instead of replacing the folder"
    assert fm.open[fm.active_tab].name == "alpha"
    assert "notes.txt" in fm.app.screen()


def test_right_descending_and_left_parent_jumping_also_follow(sample_tree):
    fm = FileManager(sample_tree, width=120, height=30)
    fm.step(_key_event(DOWN_KEY))  # cursor -> alpha (grid lists alpha, per the first test)
    fm.step(_key_event(RIGHT_KEY))  # alpha is loaded, not expanded, no subdirs: expand it

    # With the tree cursor on alpha and alpha having no subfolder to descend
    # into, Left jumps to the parent -- and the grid must follow back up.
    fm.step(_key_event(LEFT_KEY))

    assert fm.cursor is fm.root
    assert fm.open[fm.active_tab].name == fm.root.name, "parent-jump did not re-point the grid"
    assert "readme.txt" in fm.app.screen(), "the parent listing never painted"

    fm.step(_key_event(UP_KEY))  # cursor stays on root at the top: grid unchanged
    assert fm.open[fm.active_tab].name == fm.root.name
