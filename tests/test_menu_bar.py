"""Black-box tests for the menu bar (Finder-parity VISION.md backlog item):
today just a View menu with Hide/Show Sidebar and Hide/Show Preview, each
item's own label flipping with the state it toggles. Driven headlessly
through `FileManager.step`, same as every other feature tranche -- see
`app.py`'s "chrome: menu bar" section doc for how little of the open/close/
Alt-mnemonic/arrow-key interaction this app actually has to handle itself."""

from pathlib import Path

from conftest import click as _click
from conftest import find_row as _find_row

from quadraui_files import FileManager
from quadraui_files.app import ENTER_KEY, MENU_VIEW_PREVIEW_ID, MENU_VIEW_SIDEBAR_ID, _key_event, _menu_bar

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


def test_the_menu_bar_shows_the_view_label(sample_tree):
    fm = FileManager(sample_tree)
    assert "View" in fm.app.screen()


def test_alt_v_opens_the_view_menu_with_both_items(sample_tree):
    fm = FileManager(sample_tree)
    fm.step(_alt("v"))
    screen = fm.app.screen()
    assert "Hide Sidebar" in screen
    assert "Hide Preview" in screen


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
    label = _menu_bar(sidebar_visible=fm.sidebar_visible, preview_visible=fm.preview_visible)
    items = label["menu_bar"]["items"][0]["submenu"]
    sidebar_item = next(i for i in items if i["id"] == MENU_VIEW_SIDEBAR_ID)
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
    fm.step(_alt("v"))
    fm.step({"MenuActivated": MENU_VIEW_PREVIEW_ID})
    assert fm.preview_visible is False

    fm.step(_key_event({"Char": "p"}))
    assert fm.preview_visible is True


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
