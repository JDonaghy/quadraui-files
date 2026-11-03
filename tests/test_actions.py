"""T1 black-box tests: open/reveal/move-to-trash, the delete-confirm dialog,
the context menu, and the undo toast — all driven headlessly through
`FileManager.step`, which is the push-and-dispatch pair a real `--tui`
session's pump performs per event, deferred-action drain included (see
`app.py`'s module doc)."""

from quadraui_files import FileManager
from quadraui_files.app import (
    DELETE_KEY,
    DOWN_KEY,
    ENTER_KEY,
    MENU_KEY,
    _key_event,
)

ESCAPE_KEY = {"Named": "Escape"}


def _open_root_tab(fm: FileManager) -> None:
    """Open the root folder as a details tab (cursor starts there)."""
    fm.step(_key_event(ENTER_KEY))


def _activate_child(fm: FileManager, name: str) -> None:
    """Click (RowActivated) the details-table row for `name` in the active
    tab -- the way selecting a file in the listing really happens."""
    folder = fm.open[fm.active_tab]
    idx = [c.name for c in folder.children].index(name)
    fm.step({"DataTable": [f"fm:grid:{fm.active_tab}", {"RowActivated": {"idx": idx}}]})


def test_selecting_and_opening_a_file_queues_open_path_without_raising(sample_tree):
    fm = FileManager(sample_tree)
    _open_root_tab(fm)
    _activate_child(fm, "readme.txt")  # select + queue `open_path` -- must not raise
    assert fm.selected_file is not None and fm.selected_file.name == "readme.txt"
    assert "readme.txt" in fm.app.screen()


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
    assert "Moved to Trash" in toast_screen and "Undo" in toast_screen


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
