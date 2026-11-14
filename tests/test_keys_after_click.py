"""Keys keep working after a mouse click focuses the sidebar. A click gives
the sidebar tree focus, and from then on the focus manager delivers every key
as a tree-scoped event (`{"Tree": ("fm:tree", {"KeyPressed": ...})}`) rather
than a plain `KeyPressed` -- the real event path, driven here by pushing the
same mouse events a terminal click produces."""

import pytest

from conftest import click as _click
from quadraui_files import FileManager
from quadraui_files.app import _Quit, _wrap_quit

NO_MODS = {"shift": False, "ctrl": False, "alt": False, "cmd": False}


def _press(fm: FileManager, key: dict) -> None:
    fm.app.push_event({"KeyPressed": {"key": key, "modifiers": NO_MODS, "repeat": False}})
    fm.app.step()


def _click_sidebar_row(fm: FileManager, label: str) -> None:
    """Click the sidebar row labelled `label`, located on the painted screen."""
    for y, line in enumerate(fm.app.screen().splitlines()):
        x = line.find(label)
        if 0 <= x < 30:  # the sidebar is the leftmost pane
            _click(fm, float(x + 1), float(y))
            return
    raise AssertionError(f"no sidebar row {label!r} on screen:\n{fm.app.screen()}")


def test_q_quits_after_a_click_focuses_the_sidebar(sidebar_fm):
    fm = sidebar_fm
    _wrap_quit(fm)
    _click_sidebar_row(fm, "Alpha")
    assert fm.cursor.name == "alpha"

    with pytest.raises(_Quit):
        _press(fm, {"Char": "q"})


def test_navigation_keys_reach_the_app_after_a_sidebar_click(sidebar_fm):
    fm = sidebar_fm
    _click_sidebar_row(fm, "Alpha")
    assert fm.table_focus is False

    _press(fm, {"Named": "Up"})  # previous place: Root

    assert fm.cursor.path == fm.sections[0].places[0].path
    _press(fm, {"Named": "Enter"})  # hands key focus to the list
    assert fm.table_focus is True
