"""T1 black-box tests: open/reveal/move-to-trash, the delete-confirm dialog,
the context menu, and the undo toast — all driven headlessly through
`FileManager.step` (push + dispatch + flush whatever `QuiApp` call the
handler queued), exactly as a real `--tui`/`--native` session would see it
if that backend could hand control back between events (see `app.py`'s
module doc)."""

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
    # `open_path` has no reachable OS opener in a headless test run; `step`
    # must swallow that rather than letting it raise out of the handler.
    assert fm._open_request is None  # queued request was flushed either way

    fm.step(_key_event(MENU_KEY))
    fm.step(_key_event(DOWN_KEY))  # down to "Reveal"
    fm.step(_key_event(ENTER_KEY))
    assert fm._reveal_request is None
