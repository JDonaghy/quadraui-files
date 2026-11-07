"""T3b black-box tests: OS-theme match, the global keybindings, hover
tooltips, notifications, and the overlay guard -- driven headlessly through
`FileManager.step`, same as the other suites (see `app.py`'s module doc).
"""

from conftest import activate_child as _activate_child

from quadraui import InvalidDescriptorError

from quadraui_files import FileManager
from quadraui_files.app import DELETE_KEY, DOWN_KEY, ENTER_KEY, QuiApp, _key_event

F2_KEY = {"Named": {"F": 2}}
CTRL_F_EVENT = {
    "KeyPressed": {
        "key": {"Char": "f"},
        "modifiers": {"shift": False, "ctrl": True, "alt": False, "meta": False},
        "repeat": False,
    }
}


def _open_root_tab(fm: FileManager) -> None:
    fm.step(_key_event(ENTER_KEY))


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


def test_light_theme_status_bar_colors_differ_from_dark(sample_tree, monkeypatch):
    """The status bar isn't painted from `set_theme`'s palette (it needs its
    own explicit fg/bg) -- `_apply_system_theme` must still pick a light
    pair for it under a light OS theme, not leave it on the dark triple
    regardless. Checked on the painted bottom-left status cell, same
    `cell_colors` proof-of-paint `test_dark_system_theme_...` uses above."""
    monkeypatch.setenv("COLORFGBG", "15;0")  # system is dark
    dark = FileManager(sample_tree, width=60, height=20)
    _fg_dark, bg_dark = dark.app.cell_colors(0, 19)

    monkeypatch.setenv("COLORFGBG", "0;15")  # system is light
    light = FileManager(sample_tree, width=60, height=20)
    _fg_light, bg_light = light.app.cell_colors(0, 19)

    assert bg_dark != bg_light, f"status bar background didn't change: {bg_dark}"
    assert light._status_bg == {"r": 225, "g": 225, "b": 225, "a": 255}
    assert dark._status_bg == {"r": 30, "g": 32, "b": 48, "a": 255}


SYSTEM_THEME_CHANGED_TO_LIGHT = {
    "SystemThemeChanged": {
        "dark": False,
        "accent": None,
        "high_contrast": False,
        "reduce_motion": False,
    }
}


def test_system_theme_changed_event_repaints_toolbar_and_status_bar(sample_tree, monkeypatch):
    """A `SystemThemeChanged` event (dark -> light) swaps the VS Code
    palette and the status-bar triple, proved the same way the startup
    dark/light tests above do: the painted toolbar cell (theme-driven) and
    the painted status-bar cell (not theme-driven, picked separately --
    see `_STATUS_DARK_FG`'s own doc) both actually repaint, not just
    `fm.app.theme()`'s/`fm._status_bg`'s own readback."""
    monkeypatch.setenv("COLORFGBG", "15;0")  # system starts dark
    fm = FileManager(sample_tree, width=60, height=20)
    _fg, toolbar_bg_before = fm.app.cell_colors(0, 0)
    _fg, status_bg_before = fm.app.cell_colors(0, 19)
    assert fm.app.theme()["background"] == {"r": 30, "g": 30, "b": 30, "a": 255}

    fm.step(SYSTEM_THEME_CHANGED_TO_LIGHT)

    assert fm.app.theme()["background"] == {"r": 255, "g": 255, "b": 255, "a": 255}
    assert fm._status_bg == {"r": 225, "g": 225, "b": 225, "a": 255}
    _fg, toolbar_bg_after = fm.app.cell_colors(0, 0)
    _fg, status_bg_after = fm.app.cell_colors(0, 19)
    assert toolbar_bg_after != toolbar_bg_before, "toolbar didn't repaint light"
    assert status_bg_after != status_bg_before, "status bar didn't repaint light"


def test_system_theme_changed_applies_live_through_the_real_run_loop(sample_tree, monkeypatch):
    """The acceptance bar for F4b: unlike `fm.step()` above (which calls
    `QuiApp.step()` itself from top-level code), this drives the app through
    `QuiApp.run()` -- the same queued-event/deferred-action pump `run_tui()`'s
    and `run_native()`'s own loops use internally (see `run`'s own doc) --
    with no call back to top-level code in between. `_dispatch`'s
    `SystemThemeChanged` branch must queue the palette switch on the
    deferred `self.actions.set_theme` handle rather than calling
    `self.app.set_theme()` directly (which `run`'s internal dispatch would
    reject as a reentrant borrow), so this is the one path that actually
    proves a real `run_tui()`/`run_native()` session -- which never hands
    control back to this app's own top-level code -- repaints live on a
    real OS theme switch."""
    monkeypatch.setenv("COLORFGBG", "15;0")  # system starts dark
    fm = FileManager(sample_tree, width=60, height=20)
    assert fm.app.theme()["background"] == {"r": 30, "g": 30, "b": 30, "a": 255}
    _fg, toolbar_bg_before = fm.app.cell_colors(0, 0)
    _fg, status_bg_before = fm.app.cell_colors(0, 19)

    fm.app.push_event(SYSTEM_THEME_CHANGED_TO_LIGHT)
    still_running = fm.app.run(max_steps=1)

    assert still_running
    assert fm.app.theme()["background"] == {"r": 255, "g": 255, "b": 255, "a": 255}
    assert fm._status_bg == {"r": 225, "g": 225, "b": 225, "a": 255}
    _fg, toolbar_bg_after = fm.app.cell_colors(0, 0)
    _fg, status_bg_after = fm.app.cell_colors(0, 19)
    assert toolbar_bg_after != toolbar_bg_before, "toolbar didn't repaint light"
    assert status_bg_after != status_bg_before, "status bar didn't repaint light"


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
    different target, and must not leak its own key into the buffer either
    -- same suppression the equivalent plain key already gets from
    `_handle_edit_key` (see `ACCELERATORS`'s own doc)."""
    fm = FileManager(sample_tree)
    fm.step(_key_event(ENTER_KEY))  # open the root folder as a details tab
    fm.step(_key_event(DOWN_KEY))
    fm.step(_key_event(F2_KEY))  # start renaming the cursored node
    renaming = fm.rename_target
    text_before = fm.edit_text
    assert fm.edit_mode == "rename"

    fm.step(CTRL_F_EVENT)  # must not switch the box into "filter" mid-rename

    assert fm.edit_mode == "rename"
    assert fm.rename_target is renaming
    assert fm.edit_text == text_before, "the ctrl+f chord must not have landed as a typed 'f'"
    assert "f" not in fm.filter_text


def test_typing_a_bare_f_into_the_open_filter_box_is_not_swallowed(sample_tree):
    """Only the *chord* `ctrl+f`/`cmd+f` is a registered global accelerator
    (see `ACCELERATORS`'s own doc) -- a bare `f` keystroke must still reach
    the filter box as ordinary typed text once it's open."""
    fm = FileManager(sample_tree)
    fm.step(CTRL_F_EVENT)  # open the filter box
    assert fm.edit_mode == "filter"

    fm.step(_key_event({"Char": "f"}))

    assert fm.filter_text == "f"
    assert fm.edit_text == "f"


def test_accelerator_registration_rejecting_one_chord_does_not_raise(sample_tree, monkeypatch):
    """A backend that rejects a chord it doesn't recognize (`cmd+f` off
    macOS, say) must not take `FileManager.__init__` down with it, and must
    not stop the rest of the list from registering either."""
    original = QuiApp.register_accelerator

    def flaky(self, descriptor):
        if descriptor["id"] == "fm:accel:search_cmd":
            raise InvalidDescriptorError("this backend doesn't know this chord")
        return original(self, descriptor)

    monkeypatch.setattr(QuiApp, "register_accelerator", flaky)

    fm = FileManager(sample_tree)  # must not raise

    # The other accelerators registered fine despite the one rejection.
    fm.step(CTRL_F_EVENT)
    assert fm.edit_mode == "filter"


# --- overlay guard --------------------------------------------------------


def test_delete_and_f2_accelerators_are_dropped_while_the_confirm_dialog_is_open(sample_tree):
    """Pressing `Delete` again while the trash-confirm dialog is already up
    must not overwrite `_delete_target` and queue a second dialog; `F2`
    must not open a rename box behind it either."""
    fm = FileManager(sample_tree)
    _open_root_tab(fm)
    _activate_child(fm, "readme.txt")

    fm.step(_key_event(DELETE_KEY))
    target = fm._delete_target
    assert target is not None and target.name == "readme.txt"

    fm.step(_key_event(DELETE_KEY))  # re-entry attempt
    assert fm._delete_target is target, "a second Delete must not touch the pending target"

    fm.step(_key_event(F2_KEY))  # would open a rename box behind the dialog
    assert fm.edit_mode is None, "F2 must not open a rename box while the dialog is open"
    assert fm.rename_target is None

    screen = fm.app.screen()
    assert "Move to Trash" in screen and "readme.txt" in screen


# --- hover tooltips --------------------------------------------------------


def _wide_enough_for(root) -> int:
    """A screen width that fits a tooltip naming a path under `root`. The
    tooltip is clipped at the screen edge, and a temp dir can be long
    (macOS's `/private/var/folders/...` runs well past 100 columns)."""
    return max(100, len(str(root)) + 100)


def test_hovering_a_tree_row_shows_a_tooltip_with_its_full_path(sample_tree):
    fm = FileManager(sample_tree, width=_wide_enough_for(sample_tree))
    fm.step(_key_event(DOWN_KEY))  # cursor onto "alpha" -- the "hover"
    assert fm.cursor.name == "alpha"
    assert str(fm.cursor.path) in fm.app.screen()


def test_hovering_a_details_row_shows_a_tooltip_with_path_size_and_modified_time(sample_tree):
    fm = FileManager(sample_tree, width=_wide_enough_for(sample_tree))
    _open_root_tab(fm)
    _activate_child(fm, "readme.txt")  # the "hover": last file activated

    screen = fm.app.screen()
    node = fm.selected_file
    assert node is not None and node.name == "readme.txt"
    assert str(node.path) in screen
    assert "B" in screen  # the human-readable size ("5 B")


# --- notifications ---------------------------------------------------------


def test_completed_trash_sends_a_notification_without_raising(sample_tree):
    """Fire-and-forget (see `send_notification`'s own doc): there's nothing
    to assert on besides "the whole delete flow still completes"."""
    fm = FileManager(sample_tree)
    _open_root_tab(fm)
    _activate_child(fm, "readme.txt")

    fm.step(_key_event(DELETE_KEY))
    fm.step(_key_event(ENTER_KEY))  # confirm the default "Delete" button

    assert not (sample_tree / "readme.txt").exists()
