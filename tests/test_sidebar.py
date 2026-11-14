"""Black-box coverage for the places sidebar (Finder's Favorites/Locations,
Explorer's Quick access/This PC, Nautilus's places): section headers and
place labels paint, a place click shows that folder in the active tab, a
header click folds its section, and with key focus on the sidebar Up/Down
step through the places. Uses `sidebar_fm` -- a fixed "Favorites" section
(Root, Alpha) over `sample_tree` -- so screens don't depend on the host."""

import pytest

from conftest import click, find_row, let_double_click_window_pass
from quadraui_files import FileManager
from quadraui_files.app import DOWN_KEY, UP_KEY, _key_event

TAB_KEY = {"Named": "Tab"}


def _sidebar_text(fm: FileManager) -> str:
    """The sidebar column of the painted screen (it's the leftmost pane)."""
    return "\n".join(line[:24] for line in fm.app.screen().splitlines())


def _click_sidebar(fm: FileManager, label: str) -> None:
    for y, line in enumerate(fm.app.screen().splitlines()):
        x = line.find(label)
        if 0 <= x < 24:
            click(fm, float(x + 1), float(y))
            return
    raise AssertionError(f"no sidebar row {label!r}:\n{fm.app.screen()}")


def test_sidebar_shows_its_section_and_place_labels(sidebar_fm):
    side = _sidebar_text(sidebar_fm)
    for label in ("Favorites", "Root", "Alpha"):
        assert label in side, f"{label!r} not in the sidebar:\n{side}"


def test_clicking_a_place_shows_it_in_the_active_tab(sidebar_fm, sample_tree):
    fm = sidebar_fm
    _click_sidebar(fm, "Alpha")

    assert len(fm.open) == 1, "a place click opened a new tab"
    assert fm.cursor.path == sample_tree / "alpha"
    screen = fm.app.screen()
    assert "notes.txt" in screen, "alpha's listing not shown"
    crumbs = fm._address_leaf(0, fm.cursor)["status_bar"]["left_segments"]
    assert crumbs[-1]["text"].strip() == "alpha", "address bar didn't follow the place"
    assert fm.table_focus is False, "a sidebar click should focus the sidebar"


def test_clicking_a_section_header_collapses_and_expands_it(sidebar_fm):
    fm = sidebar_fm
    _click_sidebar(fm, "Favorites")
    assert "Alpha" not in _sidebar_text(fm), "section didn't collapse"

    let_double_click_window_pass()
    _click_sidebar(fm, "Favorites")
    assert "Alpha" in _sidebar_text(fm), "section didn't expand again"


def test_tab_moves_key_focus_to_the_sidebar(sidebar_fm):
    fm = sidebar_fm
    fm.step(_key_event(TAB_KEY))
    assert fm.table_focus is False


def test_sidebar_up_down_navigate_between_places(sidebar_fm, sample_tree):
    fm = sidebar_fm
    _click_sidebar(fm, "Root")  # key focus to the sidebar
    assert fm.table_focus is False

    fm.step(_key_event(DOWN_KEY))  # Root -> Alpha
    assert fm.cursor.path == sample_tree / "alpha"
    assert "notes.txt" in fm.app.screen()

    fm.step(_key_event(UP_KEY))  # back to Root
    assert fm.cursor.path == sample_tree
    assert len(fm.open) == 1


def test_the_highlight_follows_the_place_and_clears_off_one(sidebar_fm):
    fm = sidebar_fm
    rows, entries = fm._sidebar()
    assert fm._sidebar_selected_index(entries) == 1, "Root should be highlighted at start"

    fm.step({"DataTable": ["fm:grid:0", {"RowActivated": {"idx": 1}}]})  # into beta: not a place

    assert fm.cursor.name == "beta"
    assert fm._sidebar_selected_index(entries) is None
    assert fm._render()["split"]["first"]["sidebar_panel"]["content"]["split"]["first"]["tree"][
        "selected_path"
    ] is None
