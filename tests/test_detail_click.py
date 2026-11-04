"""F2 black-box tests: a single click on a details-table row selects it and
loads the preview, never the OS's default app for it -- only a double-click,
Enter/`o` once the table has focus, or the context menu's Open does that. On
a folder row, a single click selects it the same way; only a double-click
drills in (mirrors the details pane in Finder/Explorer).

Driven with real synthesized clicks at painted coordinates, not hand-built
`DataTable` events -- the whole point here is the real click/double-click
distinction the installed quadraui build now reports (see `conftest.py`'s
`click`/`double_click` doc)."""

from conftest import click as _click
from conftest import double_click as _double_click
from conftest import find_row as _find_row
from quadraui_files import FileManager
from quadraui_files.app import ENTER_KEY, _key_event


def _open_root_tab(fm: FileManager) -> None:
    fm.step(_key_event(ENTER_KEY))


def test_single_click_on_a_file_row_selects_and_previews_without_opening(sample_tree):
    (sample_tree / "readme.txt").write_text("zzqMARKERzz")
    fm = FileManager(sample_tree, width=120, height=30)
    _open_root_tab(fm)

    x, y = _find_row(fm, "readme.txt")
    _click(fm, x, y)

    assert fm.selected_file is not None and fm.selected_file.name == "readme.txt"
    assert "zzqMARKERzz" in fm.app.screen(), f"preview missing content:\n{fm.app.screen()}"
    assert fm.actions.opened == [], "a single click must never queue an OS open"


def test_double_click_on_a_file_row_opens_it_with_the_os(sample_tree):
    (sample_tree / "readme.txt").write_text("hello")
    fm = FileManager(sample_tree, width=120, height=30)
    _open_root_tab(fm)

    x, y = _find_row(fm, "readme.txt")
    _double_click(fm, x, y)

    assert fm.actions.opened == [str(sample_tree / "readme.txt")]


def test_enter_opens_the_row_a_click_just_focused_and_selected(sample_tree):
    (sample_tree / "readme.txt").write_text("hello")
    fm = FileManager(sample_tree, width=120, height=30)
    _open_root_tab(fm)

    x, y = _find_row(fm, "readme.txt")
    _click(fm, x, y)  # select -- and give the table real focus
    assert fm.actions.opened == []

    fm.step(_key_event(ENTER_KEY))

    assert fm.actions.opened == [str(sample_tree / "readme.txt")]


def test_single_click_on_a_folder_row_selects_without_drilling_in(sample_tree):
    fm = FileManager(sample_tree, width=120, height=30)
    _open_root_tab(fm)

    x, y = _find_row(fm, "alpha/")
    _click(fm, x, y)

    assert len(fm.open) == 1 and fm.open[0].name != "alpha", "a single click must not drill in"
    assert fm.selected_file is not None and fm.selected_file.name == "alpha"


def test_double_click_on_a_folder_row_drills_in(sample_tree):
    fm = FileManager(sample_tree, width=120, height=30)
    _open_root_tab(fm)

    x, y = _find_row(fm, "alpha/")
    _double_click(fm, x, y)

    assert fm.open[fm.active_tab].name == "alpha"


def test_o_key_opens_the_row_a_click_just_focused_and_selected(sample_tree):
    (sample_tree / "readme.txt").write_text("hello")
    fm = FileManager(sample_tree, width=120, height=30)
    _open_root_tab(fm)

    x, y = _find_row(fm, "readme.txt")
    _click(fm, x, y)

    fm.step(_key_event({"Char": "o"}))

    assert fm.actions.opened == [str(sample_tree / "readme.txt")]
