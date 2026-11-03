"""Keys keep working after a mouse click focuses the folder tree. A click
gives the tree focus, and from then on the focus manager delivers every key
as a tree-scoped event (`{"Tree": ("fm:tree", {"KeyPressed": ...})}`) rather
than a plain `KeyPressed` -- the real event path, driven here by pushing the
same mouse events a terminal click produces."""

import pytest

from quadraui_files import FileManager
from quadraui_files.app import _Quit, _wrap_quit

NO_MODS = {"shift": False, "ctrl": False, "alt": False, "cmd": False}


def _click(fm: FileManager, x: float, y: float) -> None:
    for kind in ("MouseDown", "MouseUp"):
        fm.app.push_event({kind: {"position": {"x": x, "y": y}, "button": "Left", "modifiers": NO_MODS}})
        fm.app.step()


def _press(fm: FileManager, key: dict) -> None:
    fm.app.push_event({"KeyPressed": {"key": key, "modifiers": NO_MODS, "repeat": False}})
    fm.app.step()


def _click_tree_row(fm: FileManager, name: str) -> None:
    """Click the folder-tree row labelled `name`, located on the painted screen."""
    for y, line in enumerate(fm.app.screen().splitlines()):
        x = line.find(f"/ {name}")
        if 0 <= x < 40:  # the tree is the leftmost pane
            _click(fm, float(x + 2), float(y))
            return
    raise AssertionError(f"no tree row {name!r} on screen")


def test_q_quits_after_a_click_focuses_the_tree(sample_tree):
    fm = FileManager(sample_tree, width=120, height=30)
    _wrap_quit(fm)
    _click_tree_row(fm, "alpha")
    assert fm.cursor.name == "alpha"

    with pytest.raises(_Quit):
        _press(fm, {"Char": "q"})


def test_navigation_keys_reach_the_app_after_a_tree_click(sample_tree):
    fm = FileManager(sample_tree, width=120, height=30)
    _click_tree_row(fm, "alpha")

    _press(fm, {"Named": "Enter"})  # open the clicked folder as a tab

    assert fm.open and fm.open[fm.active_tab].name == "alpha"
