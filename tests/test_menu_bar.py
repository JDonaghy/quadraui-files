"""Black-box tests for the menu bar (Finder-parity VISION.md backlog item):
File (New Folder, New Tab), Edit (Copy, Paste), View (Hide/Show Sidebar,
Hide/Show Preview, each item's own label flipping with the state it
toggles), and Window (Close Tab) -- every item reusing an action the
context menu/a plain key already backs, see `app.py`'s "chrome: menu bar"
section doc for the full rationale. Driven headlessly through
`FileManager.step`, same as every other feature tranche -- that doc also
covers how little of the open/close/Alt-mnemonic/arrow-key interaction
this app actually has to handle itself."""

from pathlib import Path

from conftest import click as _click
from conftest import find_row as _find_row

from quadraui_files import FileManager
from quadraui_files.app import (
    ENTER_KEY,
    MENU_EDIT_COPY_ID,
    MENU_EDIT_PASTE_ID,
    MENU_FILE_NEW_FOLDER_ID,
    MENU_FILE_NEW_TAB_ID,
    MENU_VIEW_PREVIEW_ID,
    MENU_VIEW_SIDEBAR_ID,
    MENU_WINDOW_CLOSE_TAB_ID,
    _key_event,
    _menu_bar,
)

TAB_KEY = {"Named": "Tab"}
LEFT_KEY = {"Named": "Left"}


def _open_root_tab(fm: FileManager) -> None:
    fm.step(_key_event(ENTER_KEY))


def _alt(char: str) -> dict:
    """A real `Alt+<char>` `KeyPressed` -- the mnemonic chord that opens a
    menu bar item whose own label carries a leading `&` on that letter
    (`&View` here)."""
    return {
        "KeyPressed": {
            "key": {"Char": char},
            "modifiers": {"shift": False, "ctrl": False, "alt": True, "meta": False},
            "repeat": False,
        }
    }


def test_the_menu_bar_shows_all_four_labels(sample_tree):
    fm = FileManager(sample_tree)
    screen = fm.app.screen()
    assert "File" in screen
    assert "Edit" in screen
    assert "View" in screen
    assert "Window" in screen


def test_alt_f_opens_the_file_menu_with_both_items(sample_tree):
    fm = FileManager(sample_tree)
    fm.step(_alt("f"))
    screen = fm.app.screen()
    assert "New Folder" in screen
    assert "New Tab" in screen


def test_file_new_folder_creates_one_in_the_browsed_folder(sample_tree):
    """The exact same action the context menu's own "New Folder" and
    `cmd+shift+n` already back -- the menu item is one more door to it,
    not a second implementation."""
    fm = FileManager(sample_tree)
    _open_root_tab(fm)

    fm.step(_alt("f"))
    fm.step({"MenuActivated": MENU_FILE_NEW_FOLDER_ID})

    assert "untitled folder" in [c.name for c in (fm.open[fm.active_tab].children or [])]
    assert fm.edit_mode == "rename", "should drop straight into an editable name, like Finder"


def test_file_new_tab_opens_a_second_tab_on_the_same_folder(sample_tree):
    fm = FileManager(sample_tree)
    _open_root_tab(fm)
    assert len(fm.open) == 1

    fm.step(_alt("f"))
    fm.step({"MenuActivated": MENU_FILE_NEW_TAB_ID})

    assert len(fm.open) == 2
    assert fm.active_tab == 1
    assert fm.open[1].path == fm.open[0].path


def test_edit_paste_is_disabled_with_an_empty_clipboard(sample_tree):
    fm = FileManager(sample_tree)
    label = _menu_bar(sidebar_visible=fm.sidebar_visible, preview_visible=fm.preview_visible, has_clipboard=False)
    all_items = [i for menu in label["menu_bar"]["items"] for i in menu["submenu"]]
    paste_item = next(i for i in all_items if i["id"] == MENU_EDIT_PASTE_ID)
    assert paste_item["disabled"] is True


def test_edit_paste_is_enabled_once_something_is_copied():
    label = _menu_bar(sidebar_visible=True, preview_visible=False, has_clipboard=True)
    all_items = [i for menu in label["menu_bar"]["items"] for i in menu["submenu"]]
    paste_item = next(i for i in all_items if i["id"] == MENU_EDIT_PASTE_ID)
    assert paste_item.get("disabled", False) is False


def test_edit_copy_sets_the_clipboard_to_the_selected_file(sample_tree):
    (sample_tree / "readme.txt").write_text("hi")
    fm = FileManager(sample_tree)
    _open_root_tab(fm)
    x, y = _find_row(fm, "readme.txt")
    _click(fm, x, y)

    fm.step(_alt("e"))
    fm.step({"MenuActivated": MENU_EDIT_COPY_ID})

    assert fm._clipboard is not None and fm._clipboard.name == "readme.txt"


def test_edit_paste_pastes_the_copied_file_into_the_browsed_folder(sample_tree):
    (sample_tree / "readme.txt").write_text("hi")
    fm = FileManager(sample_tree)
    _open_root_tab(fm)
    fm._copy(fm._node_for(sample_tree / "readme.txt"))  # direct: Copy itself has its own tests above
    fm._navigate(fm._node_for(sample_tree / "alpha"))

    fm.step(_alt("e"))
    fm.step({"MenuActivated": MENU_EDIT_PASTE_ID})

    assert "readme.txt" in [c.name for c in (fm.open[fm.active_tab].children or [])]
    assert (sample_tree / "alpha" / "readme.txt").exists()


def test_alt_v_opens_the_view_menu_with_both_items(sample_tree):
    fm = FileManager(sample_tree)
    fm.step(_alt("v"))
    screen = fm.app.screen()
    assert "Hide Sidebar" in screen
    assert "Show Preview" in screen  # hidden by default; the label says so


def test_choosing_hide_sidebar_hides_it_and_flips_its_own_label(sample_tree):
    fm = FileManager(sample_tree)
    _open_root_tab(fm)
    assert fm.sidebar_visible is True

    fm.step(_alt("v"))
    fm.step({"MenuActivated": MENU_VIEW_SIDEBAR_ID})

    assert fm.sidebar_visible is False
    assert "alpha" in fm.app.screen(), "the details grid should still be there, just wider"

    # Built directly rather than reopened live: a synthesized `MenuActivated`
    # (above) never tells the *engine's own* dropdown-open state that it
    # closed, the way a real click/Enter on the item would -- so a second
    # live `Alt+V` right after one in a test can land on stale engine state
    # and misbehave. Irrelevant to a real session (nothing here ever
    # synthesizes `MenuActivated` directly), but real enough in a test to
    # check the built descriptor instead of the live screen for this one.
    label = _menu_bar(
        sidebar_visible=fm.sidebar_visible,
        preview_visible=fm.preview_visible,
        has_clipboard=fm._clipboard is not None,
    )
    all_items = [i for menu in label["menu_bar"]["items"] for i in menu["submenu"]]
    sidebar_item = next(i for i in all_items if i["id"] == MENU_VIEW_SIDEBAR_ID)
    assert sidebar_item["label"]["spans"][0]["text"] == "Show Sidebar"


def test_choosing_hide_sidebar_twice_shows_it_again(sample_tree):
    fm = FileManager(sample_tree)
    fm.step(_alt("v"))
    fm.step({"MenuActivated": MENU_VIEW_SIDEBAR_ID})
    assert fm.sidebar_visible is False

    fm.step(_alt("v"))
    fm.step({"MenuActivated": MENU_VIEW_SIDEBAR_ID})
    assert fm.sidebar_visible is True


def test_choosing_hide_preview_hides_the_preview_pane(sample_tree):
    (sample_tree / "readme.txt").write_text("zzqMARKERzz")
    fm = FileManager(sample_tree)
    _open_root_tab(fm)
    fm._toggle_preview()  # hidden by default; show it first so hiding it means something
    x, y = _find_row(fm, "readme.txt")
    _click(fm, x, y)
    assert "zzqMARKERzz" in fm.app.screen()

    fm.step(_alt("v"))
    fm.step({"MenuActivated": MENU_VIEW_PREVIEW_ID})

    assert fm.preview_visible is False
    assert "zzqMARKERzz" not in fm.app.screen()


def test_hide_preview_menu_item_is_the_same_toggle_the_p_key_uses(sample_tree):
    """Confirms the menu item doesn't duplicate `_toggle_preview`'s own
    state -- choosing it, then pressing `p`, ends up back where it started
    rather than double-toggling or diverging."""
    fm = FileManager(sample_tree)
    assert fm.preview_visible is False  # hidden by default
    fm.step(_alt("v"))
    fm.step({"MenuActivated": MENU_VIEW_PREVIEW_ID})
    assert fm.preview_visible is True

    fm.step(_key_event({"Char": "p"}))
    assert fm.preview_visible is False


def test_tab_does_nothing_once_the_sidebar_is_hidden(sample_tree):
    fm = FileManager(sample_tree)
    _open_root_tab(fm)
    fm.step(_alt("v"))
    fm.step({"MenuActivated": MENU_VIEW_SIDEBAR_ID})
    assert fm.table_focus is True

    fm.step(_key_event(TAB_KEY))

    assert fm.table_focus is True, "nothing to hand focus to with the sidebar hidden"


def test_left_at_a_filesystem_root_does_not_try_to_focus_a_hidden_sidebar(sample_tree):
    fm = FileManager(sample_tree)
    fm._navigate(fm._node_for(Path(sample_tree.anchor)))  # straight to "/" -- nowhere up from here
    fm._toggle_sidebar()  # direct, not through the menu -- see the label-flip test's own note
    assert fm.sidebar_visible is False

    fm.step(_key_event(LEFT_KEY))  # would hand focus to the sidebar if it were shown

    assert fm.table_focus is True
    assert "already at the top" in fm.message


def test_window_close_tab_closes_the_active_tab(sample_tree):
    fm = FileManager(sample_tree)
    _open_root_tab(fm)
    fm._open()  # a second tab on the same folder; it becomes active
    assert len(fm.open) == 2

    fm.step(_alt("w"))
    fm.step({"MenuActivated": MENU_WINDOW_CLOSE_TAB_ID})

    assert len(fm.open) == 1


def test_window_close_tab_keeps_the_last_tab_open(sample_tree):
    fm = FileManager(sample_tree)
    _open_root_tab(fm)
    assert len(fm.open) == 1

    fm.step(_alt("w"))
    fm.step({"MenuActivated": MENU_WINDOW_CLOSE_TAB_ID})

    assert len(fm.open) == 1
    assert "the last tab stays open" in fm.message
