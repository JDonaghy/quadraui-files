"""T1 black-box tests: open/reveal/move-to-trash, the delete-confirm dialog,
the context menu, and the undo toast — all driven headlessly through
`FileManager.step`, which is the push-and-dispatch pair a real `--tui`
session's pump performs per event, deferred-action drain included (see
`app.py`'s module doc)."""

import pytest
from conftest import activate_child as _activate_child

from quadraui_files import FileManager
from quadraui_files.app import (
    DELETE_KEY,
    DOWN_KEY,
    ENTER_KEY,
    MENU_KEY,
    UNDO_SUPPORTED,
    _key_event,
)

ESCAPE_KEY = {"Named": "Escape"}

needs_undo = pytest.mark.skipif(
    not UNDO_SUPPORTED, reason="no programmatic trash restore on this host (macOS)"
)


def _open_root_tab(fm: FileManager) -> None:
    """Open the root folder as a details tab (cursor starts there)."""
    fm.step(_key_event(ENTER_KEY))


def test_selecting_and_opening_a_file_queues_open_path_without_raising(sample_tree):
    fm = FileManager(sample_tree)
    _open_root_tab(fm)
    _activate_child(fm, "readme.txt")  # select + queue `open_path` -- must not raise
    assert fm.selected_file is not None and fm.selected_file.name == "readme.txt"
    assert "readme.txt" in fm.app.screen()
    assert fm.actions.opened == [str(sample_tree / "readme.txt")]


def test_delete_confirm_flow_removes_file_and_shows_undo_toast(sample_tree):
    fm = FileManager(sample_tree)
    _open_root_tab(fm)
    _activate_child(fm, "readme.txt")

    fm.step(_key_event(DELETE_KEY))
    dialog_screen = fm.app.screen()
    assert "Move to Trash" in dialog_screen
    assert "readme.txt" in dialog_screen
    assert "Cancel" in dialog_screen and "Delete" in dialog_screen

    # The dialog's default button is "Delete"; Enter confirms it.
    fm.step(_key_event(ENTER_KEY))

    listing = [c.name for c in fm.open[fm.active_tab].children]
    assert "readme.txt" not in listing, f"file node still in the listing: {listing}"
    assert not (sample_tree / "readme.txt").exists(), "file wasn't actually trashed"

    toast_screen = fm.app.screen()
    assert "Moved to Trash" in toast_screen
    # The Undo affordance is offered exactly where a restore can work.
    assert ("Undo" in toast_screen) == UNDO_SUPPORTED


def test_delete_dialog_button_spec_carries_a_danger_variant_matching_its_own_label(sample_tree):
    """The confirm dialog's `delete` button spec (`_request_delete`'s own
    doc) must keep `spec["label"]` equal to the button's own `label` --
    the label-drift this guards against -- and carry the `Danger` variant
    the TUI (and, per `message_dialog_options_from_buttons`, now the
    engine generally) can paint it with."""
    fm = FileManager(sample_tree)
    _open_root_tab(fm)
    _activate_child(fm, "readme.txt")

    calls = []
    real_show_message_dialog = fm.actions.show_message_dialog

    def recording(**kwargs):
        calls.append(kwargs)
        return real_show_message_dialog(**kwargs)

    fm.actions.show_message_dialog = recording

    fm.step(_key_event(DELETE_KEY))

    assert calls, "show_message_dialog was never called"
    delete_button = next(b for b in calls[0]["buttons"] if b["id"] == "delete")
    assert delete_button["spec"]["label"] == delete_button["label"]
    assert delete_button["spec"]["variant"] == "Danger"


def test_delete_cancel_keeps_the_file(sample_tree):
    fm = FileManager(sample_tree)
    _open_root_tab(fm)
    _activate_child(fm, "readme.txt")

    fm.step(_key_event(DELETE_KEY))
    assert "Move to Trash" in fm.app.screen()

    # Escape resolves to the dialog's Cancel button.
    fm.step(_key_event(ESCAPE_KEY))

    listing = [c.name for c in fm.open[fm.active_tab].children]
    assert "readme.txt" in listing
    assert (sample_tree / "readme.txt").exists()
    assert "Move to Trash" not in fm.app.screen(), "dialog should have closed"


def test_context_menu_lists_actions_and_dismisses_cleanly(sample_tree):
    fm = FileManager(sample_tree)
    fm.step(_key_event(DOWN_KEY))  # cursor onto the first subfolder (alpha)

    fm.step(_key_event(MENU_KEY))
    menu_screen = fm.app.screen()
    assert "Open" in menu_screen
    assert "Reveal" in menu_screen
    assert "Move to Trash" in menu_screen

    # Escape dismisses the menu with no action and no crash.
    fm.step(_key_event(ESCAPE_KEY))
    assert fm._menu_target is None


def test_context_menu_open_and_reveal_do_not_raise(sample_tree):
    fm = FileManager(sample_tree)
    fm.step(_key_event(DOWN_KEY))  # cursor onto alpha

    fm.step(_key_event(MENU_KEY))
    fm.step(_key_event(ENTER_KEY))  # "Open" is the first/default item
    # The headless backend has no OS opener, so `open_path` is a no-op there --
    # what matters is that neither the handler nor the pump's drain raises, and
    # that the menu closed.
    assert fm._menu_target is None
    assert "Reveal" not in fm.app.screen()

    fm.step(_key_event(MENU_KEY))
    fm.step(_key_event(DOWN_KEY))  # down to "Reveal"
    fm.step(_key_event(ENTER_KEY))
    assert fm._menu_target is None
    assert "Reveal" not in fm.app.screen()


def test_actions_land_without_python_driving_the_flush(sample_tree):
    """The real-backend path. `run_tui` owns the app for its whole run and
    never gives top-level Python a turn between events, so the whole
    delete flow has to work with nothing but `QuiApp`'s own push/dispatch pump
    running -- no `FileManager` code in between. Driven here through
    `fm.app` directly, deliberately bypassing `FileManager.step`."""
    fm = FileManager(sample_tree)

    def pump(event: dict) -> None:
        fm.app.push_event(event)
        fm.app.step()

    pump(_key_event(ENTER_KEY))  # open the root as a details tab
    idx = [c.name for c in fm.open[fm.active_tab].children].index("readme.txt")
    pump({"DataTable": [f"fm:grid:{fm.active_tab}", {"RowActivated": {"idx": idx}}]})

    pump(_key_event(DELETE_KEY))
    screen = fm.app.screen()
    assert "Move to Trash" in screen, f"dialog never reached the screen:\n{screen}"
    assert "Cancel" in screen and "Delete" in screen

    pump(_key_event(ENTER_KEY))  # confirm
    assert not (sample_tree / "readme.txt").exists(), "file wasn't actually trashed"
    assert "Moved to Trash" in fm.app.screen()


def _click_toast_undo(fm: FileManager) -> None:
    """Click the undo toast's `Undo` action button."""
    fm.step({"ToastActionClicked": "undo"})


@needs_undo
def test_undo_toast_restores_the_trashed_file(sample_tree):
    """The toast's Undo really puts the path back -- on disk and in the
    listing -- not just a message saying it would."""
    fm = FileManager(sample_tree)
    _open_root_tab(fm)
    _activate_child(fm, "readme.txt")

    fm.step(_key_event(DELETE_KEY))
    fm.step(_key_event(ENTER_KEY))  # confirm
    assert not (sample_tree / "readme.txt").exists()
    assert "Undo" in fm.app.screen()

    _click_toast_undo(fm)

    assert (sample_tree / "readme.txt").exists(), "Undo didn't restore the file"
    assert (sample_tree / "readme.txt").read_text() == "hello"
    listing = [c.name for c in fm.open[fm.active_tab].children]
    assert "readme.txt" in listing, f"restored file missing from the listing: {listing}"
    assert "restored readme.txt" in fm.app.screen()


@needs_undo
def test_undo_restores_a_trashed_folder_with_its_contents(sample_tree):
    fm = FileManager(sample_tree)
    fm.step(_key_event(DOWN_KEY))  # cursor onto alpha
    fm.step(_key_event(DELETE_KEY))
    fm.step(_key_event(ENTER_KEY))  # confirm
    assert not (sample_tree / "alpha").exists()

    _click_toast_undo(fm)

    assert (sample_tree / "alpha" / "notes.txt").read_text() == "notes"
    assert "alpha" in fm.app.screen(), "restored folder missing from the tree"


@needs_undo
def test_a_second_undo_click_is_refused_rather_than_failing_in_the_pump(sample_tree):
    """A restore of an already-restored path finds nothing in the trash and
    raises inside the event pump, where this app has no way to catch it -- so
    the undo token is one-shot and a repeat click must never queue one."""
    fm = FileManager(sample_tree)
    _open_root_tab(fm)
    _activate_child(fm, "readme.txt")
    fm.step(_key_event(DELETE_KEY))
    fm.step(_key_event(ENTER_KEY))

    _click_toast_undo(fm)
    _click_toast_undo(fm)  # must not raise out of the pump

    assert (sample_tree / "readme.txt").exists()
    assert "nothing left to undo" in fm.app.screen()


def test_trashing_a_vanished_file_is_reported_not_raised(sample_tree):
    """The confirm dialog is modal but the filesystem is not: the file can be
    gone by the time Delete is pressed. Trashing a missing path fails inside
    the pump, where nothing can catch it, so it must never be queued."""
    fm = FileManager(sample_tree)
    _open_root_tab(fm)
    _activate_child(fm, "readme.txt")

    fm.step(_key_event(DELETE_KEY))
    (sample_tree / "readme.txt").unlink()
    fm.step(_key_event(ENTER_KEY))  # confirm -- must not raise out of the pump

    assert "readme.txt" not in [c.name for c in fm.open[fm.active_tab].children]
    assert "no longer there" in fm.app.screen()
