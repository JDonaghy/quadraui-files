"""F6d black-box tests: the context menu's newer items -- New Folder,
Duplicate, Copy/Paste, and Get Info -- driven headlessly through
`FileManager.step` (deferred-action drain included, see `app.py`'s module
doc). `test_actions.py` keeps the original Open/Reveal/Move to Trash
coverage; this file is the "fuller context menu" VISION.md backlog item."""

from conftest import click as _click
from conftest import find_row as _find_row

from quadraui_files import FileManager
from quadraui_files.app import ENTER_KEY, MENU_KEY, _key_event

ESCAPE_KEY = {"Named": "Escape"}


def _open_root_tab(fm: FileManager) -> None:
    fm.step(_key_event(ENTER_KEY))


def _select(fm: FileManager, name: str) -> None:
    """A real synthesized single click on `name`'s row -- selects it and
    gives the table focus, same as `test_detail_click.py`'s own clicks."""
    x, y = _find_row(fm, name)
    _click(fm, x, y)


def _accel(accel_id: str) -> dict:
    """A real `Accelerator` event for `accel_id` -- the chord path
    `ACCELERATORS` registers, distinct from the plain `KeyPressed` path
    `_on_key` handles (see `_on_accelerator`'s own doc)."""
    return {"Accelerator": [accel_id, {"shift": False, "ctrl": False, "alt": False, "cmd": False}]}


_NO_MODS = {"shift": False, "ctrl": False, "alt": False, "cmd": False}


def _right_click(fm: FileManager, x: float, y: float) -> None:
    """A real synthesized right-button `MouseDown`/`MouseUp` pair -- unlike
    `conftest.click`, which always sends `"Left"`. Only meaningful off a
    row (`_dispatch`'s own `"MouseUp"` branch): a right-click *on* a row
    still can't be told apart from a left one (JDonaghy/quadraui#2555)."""
    for kind in ("MouseDown", "MouseUp"):
        fm.app.push_event({kind: {"position": {"x": x, "y": y}, "button": "Right", "modifiers": _NO_MODS}})
        fm.app.step()


def _names(fm: FileManager) -> list[str]:
    return sorted(c.name for c in (fm.open[fm.active_tab].children or []))


# --- New Folder ---------------------------------------------------------


def test_new_folder_creates_an_editable_untitled_folder(sample_tree):
    fm = FileManager(sample_tree)
    _open_root_tab(fm)

    fm.step(_accel("fm:accel:new_folder_cmd"))

    assert "untitled folder" in _names(fm)
    assert (sample_tree / "untitled folder").is_dir()
    assert fm.edit_mode == "rename", "should drop straight into an editable name, like Finder"
    assert fm.rename_target is not None and fm.rename_target.name == "untitled folder"
    assert "untitled folder" in fm.app.screen()


def test_new_folder_numbers_on_a_name_collision(sample_tree):
    (sample_tree / "untitled folder").mkdir()
    fm = FileManager(sample_tree)
    _open_root_tab(fm)

    fm.step(_accel("fm:accel:new_folder_cmd"))

    assert "untitled folder 2" in _names(fm)
    assert (sample_tree / "untitled folder 2").is_dir()


def test_new_folder_acts_on_the_browsed_folder_not_the_selection(sample_tree):
    """Selecting "alpha" and choosing New Folder from its context menu must
    still create inside the root being browsed, not inside alpha -- the one
    exception `_request_context_menu`'s own doc calls out."""
    fm = FileManager(sample_tree)
    _open_root_tab(fm)
    _select(fm, "alpha")

    fm.step(_key_event(MENU_KEY))
    fm.step({"ContextMenuItemActivated": "new_folder"})

    assert "untitled folder" in _names(fm)
    assert not (sample_tree / "alpha" / "untitled folder").exists()


# --- Duplicate -----------------------------------------------------------


def test_duplicate_a_file_makes_a_named_copy_and_selects_it(sample_tree):
    (sample_tree / "readme.txt").write_text("hello")
    fm = FileManager(sample_tree)
    _open_root_tab(fm)
    _select(fm, "readme.txt")

    fm.step(_accel("fm:accel:duplicate"))

    assert "readme copy.txt" in _names(fm)
    assert (sample_tree / "readme copy.txt").read_text() == "hello"
    assert fm.selected_file is not None and fm.selected_file.name == "readme copy.txt"


def test_duplicate_twice_numbers_the_second_copy(sample_tree):
    (sample_tree / "readme.txt").write_text("hello")
    fm = FileManager(sample_tree)
    _open_root_tab(fm)
    _select(fm, "readme.txt")

    fm.step(_accel("fm:accel:duplicate"))
    _select(fm, "readme.txt")  # back onto the original, not the copy just made
    fm.step(_accel("fm:accel:duplicate"))

    assert "readme copy 2.txt" in _names(fm)


def test_duplicate_a_folder_copies_its_whole_contents(sample_tree):
    fm = FileManager(sample_tree)
    _open_root_tab(fm)
    _select(fm, "alpha")

    fm.step(_accel("fm:accel:duplicate"))

    assert "alpha copy" in _names(fm)
    assert (sample_tree / "alpha copy" / "notes.txt").read_text() == "notes"


def test_duplicate_with_nothing_selected_reports_a_message_and_does_not_raise(sample_tree):
    fm = FileManager(sample_tree)
    _open_root_tab(fm)

    fm.step(_accel("fm:accel:duplicate"))

    assert "select something" in fm.message


# --- Copy / Paste ----------------------------------------------------------


def test_copy_then_paste_into_a_different_folder_keeps_the_name(sample_tree):
    (sample_tree / "readme.txt").write_text("hello")
    fm = FileManager(sample_tree)
    _open_root_tab(fm)
    _select(fm, "readme.txt")
    fm.step(_accel("fm:accel:copy_cmd"))

    fm._navigate(fm._node_for(sample_tree / "alpha"))
    fm.step(_accel("fm:accel:paste_cmd"))

    assert "readme.txt" in _names(fm)
    assert (sample_tree / "alpha" / "readme.txt").read_text() == "hello"
    assert (sample_tree / "readme.txt").exists(), "Copy must not remove the original"


def test_paste_into_the_same_folder_numbers_like_duplicate(sample_tree):
    (sample_tree / "readme.txt").write_text("hello")
    fm = FileManager(sample_tree)
    _open_root_tab(fm)
    _select(fm, "readme.txt")

    fm.step(_accel("fm:accel:copy_cmd"))
    fm.step(_accel("fm:accel:paste_cmd"))

    assert "readme copy.txt" in _names(fm)


def test_paste_with_an_empty_clipboard_reports_a_message_and_does_not_raise(sample_tree):
    fm = FileManager(sample_tree)
    _open_root_tab(fm)

    fm.step(_accel("fm:accel:paste_cmd"))

    assert "nothing to paste" in fm.message


def test_context_menu_paste_item_only_appears_after_a_copy(sample_tree):
    (sample_tree / "readme.txt").write_text("hello")
    fm = FileManager(sample_tree)
    _open_root_tab(fm)
    _select(fm, "readme.txt")

    fm.step(_key_event(MENU_KEY))
    assert "Paste" not in fm.app.screen()
    fm.step(_key_event(ESCAPE_KEY))

    fm.step(_accel("fm:accel:copy_cmd"))
    fm.step(_key_event(MENU_KEY))
    assert "Paste" in fm.app.screen()


# --- Get Info --------------------------------------------------------------


def test_get_info_shows_kind_size_dates_and_permissions(sample_tree):
    (sample_tree / "readme.txt").write_text("hello world")
    fm = FileManager(sample_tree)
    _open_root_tab(fm)
    _select(fm, "readme.txt")

    fm.step(_accel("fm:accel:get_info_cmd"))

    screen = fm.app.screen()
    assert "readme.txt" in screen
    assert "Kind: Plain Text" in screen
    assert "Size: 11 B" in screen
    assert "Modified:" in screen
    assert "Created:" in screen
    assert "Permissions:" in screen


def test_get_info_on_a_folder_shows_an_item_count_instead_of_a_size(sample_tree):
    fm = FileManager(sample_tree)
    _open_root_tab(fm)
    _select(fm, "alpha")

    fm.step(_accel("fm:accel:get_info_cmd"))

    screen = fm.app.screen()
    assert "Kind: Folder" in screen
    assert "Contains: 1 items" in screen


def test_get_info_with_nothing_selected_reports_a_message_and_does_not_raise(sample_tree):
    fm = FileManager(sample_tree)
    _open_root_tab(fm)

    fm.step(_accel("fm:accel:get_info_cmd"))

    assert "select something" in fm.message


# --- context menu contents --------------------------------------------------


def test_context_menu_lists_the_newer_items_too(sample_tree):
    (sample_tree / "readme.txt").write_text("hello")
    fm = FileManager(sample_tree)
    _open_root_tab(fm)
    _select(fm, "readme.txt")

    fm.step(_key_event(MENU_KEY))
    screen = fm.app.screen()
    for label in ("Open", "Reveal", "Get Info", "Rename", "Duplicate", "Copy", "New Folder", "Move to Trash"):
        assert label in screen, f"{label!r} missing from the context menu:\n{screen}"


def test_context_menu_rename_item_opens_the_rename_box(sample_tree):
    (sample_tree / "readme.txt").write_text("hello")
    fm = FileManager(sample_tree)
    _open_root_tab(fm)
    _select(fm, "readme.txt")

    fm.step(_key_event(MENU_KEY))
    fm.step({"ContextMenuItemActivated": "rename"})

    assert fm.edit_mode == "rename"
    assert fm.rename_target is not None and fm.rename_target.name == "readme.txt"


# --- a real right-click, where it's actually possible today ----------------


def test_right_click_on_empty_grid_space_opens_the_context_menu(sample_tree):
    """A right-click that lands on the grid's own empty space (below/
    between rows) still carries its real `button` all the way through --
    unlike one that lands on a row, which can't be told apart from a left
    click yet (JDonaghy/quadraui#2555). Acts like nothing's selected
    (`_request_context_menu(None)`), the same menu Menu/Shift+F10 show
    with nothing selected -- not whatever row happens to be selected
    elsewhere in the tab."""
    (sample_tree / "readme.txt").write_text("hello")
    fm = FileManager(sample_tree)
    _open_root_tab(fm)
    _select(fm, "readme.txt")  # something *is* selected elsewhere

    _right_click(fm, 50.0, 15.0)  # empty space below the listed rows

    assert fm._menu_target is not None and fm._menu_target.name == fm.cursor.name
    assert "New Folder" in fm.app.screen()


def test_right_click_on_a_row_still_cannot_open_the_context_menu(sample_tree):
    """The still-blocked case: right-clicking an actual row resolves
    identically to a left click (`RowSelected`, no button carried), so no
    menu opens -- documents today's real limit rather than silently
    passing because the assertion is too loose."""
    (sample_tree / "readme.txt").write_text("hello")
    fm = FileManager(sample_tree)
    _open_root_tab(fm)

    x, y = _find_row(fm, "readme.txt")
    _right_click(fm, x, y)

    assert fm._menu_target is None
    assert fm.selected_file is not None and fm.selected_file.name == "readme.txt"


def test_right_click_on_empty_grid_space_is_suppressed_while_editing(sample_tree):
    fm = FileManager(sample_tree)
    _open_root_tab(fm)
    fm._start_filter()

    _right_click(fm, 50.0, 15.0)

    assert fm._menu_target is None
    assert fm.edit_mode == "filter"
