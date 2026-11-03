"""T3 black-box tests: OS-theme match and the global keybindings -- driven
headlessly through `FileManager.step`, same as the other suites (see
`app.py`'s module doc).

Tooltips (hover a tree/details row) and notifications (`QuiApp.send_notification`
on a completed op) are not covered here: both would need `_handle` to call a
method `QuiApp.actions()` doesn't carry (`show_tooltip`/`send_notification`),
and every other `QuiApp` method raises "already borrowed" when called from
inside the handler's dispatch -- see `app.py`'s own doc for the `actions()`
handle and `ACCELERATORS`'s doc for the same reentrancy constraint applied to
`register_accelerator`. There is no reachable way to wire either from this
app without quadraui-py's deferred-action queue growing to cover them.
"""

from quadraui_files import FileManager
from quadraui_files.app import DOWN_KEY, ENTER_KEY, _key_event

F2_KEY = {"Named": {"F": 2}}
CTRL_F_EVENT = {
    "KeyPressed": {
        "key": {"Char": "f"},
        "modifiers": {"shift": False, "ctrl": True, "alt": False, "meta": False},
        "repeat": False,
    }
}


# --- OS theme match -----------------------------------------------------


def test_dark_system_theme_paints_the_vscode_dark_palette(sample_tree, monkeypatch):
    monkeypatch.setenv("COLORFGBG", "15;0")  # light-on-dark -> system is dark
    fm = FileManager(sample_tree, width=60, height=20)
    assert fm.app.theme()["background"] == {"r": 30, "g": 30, "b": 30, "a": 255}
    # Prove it actually painted, not just that `theme()` reads the override
    # back (`cell_colors`'s own doc): cell (0, 0) is inside the toolbar's
    # first button, whose background is theme-driven (`StyledText`'s `bg:
    # None` lets the theme through).
    _fg, bg = fm.app.cell_colors(0, 0)
    assert bg == (45, 45, 45), f"toolbar background not repainted dark: {bg}"


def test_light_system_theme_paints_the_vscode_light_palette(sample_tree, monkeypatch):
    monkeypatch.setenv("COLORFGBG", "0;15")  # dark-on-light -> system is light
    fm = FileManager(sample_tree, width=60, height=20)
    assert fm.app.theme()["background"] == {"r": 255, "g": 255, "b": 255, "a": 255}
    _fg, bg = fm.app.cell_colors(0, 0)
    assert bg == (243, 243, 243), f"toolbar background not repainted light: {bg}"


def test_unsupported_system_theme_falls_back_to_the_backend_default(sample_tree, monkeypatch):
    """No `$COLORFGBG` -- `system_theme()` raises `Unsupported` (e.g. a TUI
    session outside any terminal that sets it) -- leaves the installed
    theme's own default untouched rather than raising out of `__init__`."""
    monkeypatch.delenv("COLORFGBG", raising=False)
    fm = FileManager(sample_tree, width=60, height=20)
    assert fm.app.theme()["background"] not in (
        {"r": 30, "g": 30, "b": 30, "a": 255},
        {"r": 255, "g": 255, "b": 255, "a": 255},
    )


# --- keybindings (C15) ---------------------------------------------------


def test_ctrl_f_accelerator_opens_the_search_box(sample_tree):
    fm = FileManager(sample_tree)
    fm.step(CTRL_F_EVENT)
    assert fm.edit_mode == "filter"
    assert "Filter" in fm.app.screen()


def test_f2_accelerator_opens_the_rename_box_for_the_cursored_folder(sample_tree):
    fm = FileManager(sample_tree)
    fm.step(_key_event(DOWN_KEY))  # cursor onto "alpha"
    fm.step(_key_event(F2_KEY))
    assert fm.edit_mode == "rename"
    assert fm.rename_target is not None and fm.rename_target.name == "alpha"
    assert "Rename" in fm.app.screen()


def test_registered_accelerators_are_ignored_while_the_edit_box_is_open(sample_tree):
    """An accelerator firing mid-edit must not reroute the box onto a
    different target -- same suppression the equivalent plain key already
    gets from `_handle_edit_key` (see `ACCELERATORS`'s own doc)."""
    fm = FileManager(sample_tree)
    fm.step(_key_event(ENTER_KEY))  # open the root folder as a details tab
    fm.step(_key_event(DOWN_KEY))
    fm.step(_key_event(F2_KEY))  # start renaming the cursored node
    renaming = fm.rename_target
    assert fm.edit_mode == "rename"

    fm.step(CTRL_F_EVENT)  # must not switch the box into "filter" mid-rename

    assert fm.edit_mode == "rename"
    assert fm.rename_target is renaming
