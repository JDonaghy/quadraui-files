"""F1 black-box tests: a tree-row click selects and shows that folder in the
details pane without touching its expansion state; only the chevron (or
Left/Right) expands/collapses; the clicked row's own tree position doesn't
move this app's own scroll offset; and an unreadable folder reports why, not
just "0 items".

Most assertions here read model state (`fm.cursor`/`fm.open`/`fm.scroll`/
`fm.message`) rather than `fm.app.screen()`: the installed quadraui build's
Tree widget paints a focus border over the widget's own first content row
the moment it gains focus from a mouse click (reproducible headlessly, see
`test_root_row_hidden_by_upstream_focus_border_is_a_known_quadraui_bug`
below) -- any row happening to be scrolled to the top, root included, is
covered by that border regardless of this app's own (correct) scroll
offset. Asserting against the screen for *tree-pane* content right after a
click would make these tests depend on that unrelated, upstream rendering
bug rather than on this file's own behavior."""

import os
import sys

import pytest

from conftest import click as _click
from conftest import let_double_click_window_pass as _let_double_click_window_pass
from quadraui_files import FileManager


def _row_icon_x(fm: FileManager, name: str) -> tuple[int, int]:
    """The (x, y) of the "/ name" icon+name marker for tree row `name`, on
    the painted screen -- clicking here is a row-body click. Raises if the
    row isn't on screen."""
    for y, line in enumerate(fm.app.screen().splitlines()):
        x = line.find(f"/ {name}")
        if 0 <= x < 40:  # the tree is the leftmost pane
            return x, y
    raise AssertionError(f"no tree row {name!r} on screen")


def _click_tree_row(fm: FileManager, name: str) -> None:
    """Click the row *body* (icon/name) of tree row `name`."""
    x, y = _row_icon_x(fm, name)
    _click(fm, float(x + 2), float(y))


def _click_tree_chevron(fm: FileManager, name: str) -> None:
    """Click the chevron of tree row `name` -- always exactly 2 columns
    left of the row's own icon marker (chevron, then one space, then the
    icon), at any indent depth."""
    x, y = _row_icon_x(fm, name)
    _click(fm, float(x - 2), float(y))


# --- row click: select + show, never toggle expansion ----------------------


def test_clicking_a_tree_row_shows_it_in_the_details_pane(sample_tree):
    fm = FileManager(sample_tree, width=120, height=30)
    _click_tree_row(fm, "alpha")

    assert fm.cursor.name == "alpha"
    assert fm.open and fm.open[fm.active_tab].name == "alpha"
    assert [c.name for c in fm._visible_children(fm.open[fm.active_tab])] == ["notes.txt"]


def test_clicking_a_tree_row_replaces_the_active_tab_not_a_new_one(sample_tree):
    fm = FileManager(sample_tree, width=120, height=30)
    _click_tree_row(fm, "alpha")
    assert len(fm.open) == 1

    _let_double_click_window_pass()
    _click_tree_row(fm, "beta")
    assert len(fm.open) == 1, "a tree click replaces the active tab's folder, not a new one"
    assert fm.open[fm.active_tab].name == "beta"


def test_clicking_a_tree_row_does_not_change_its_expansion_state(sample_tree):
    (sample_tree / "alpha" / "sub").mkdir()  # a subfolder: alpha has something to expand into
    fm = FileManager(sample_tree, width=120, height=30)
    alpha = next(c for c in fm._visible()[1] if c.name == "alpha")
    assert alpha.expanded is False

    _click_tree_row(fm, "alpha")
    assert alpha.expanded is False  # unchanged: a row click never expands

    fm.cursor = alpha
    fm._expand()  # Right: now expanded
    assert alpha.expanded is True

    _let_double_click_window_pass()
    _click_tree_row(fm, "alpha")
    assert alpha.expanded is True  # unchanged: a row click never collapses either


# --- chevron click: only expansion, no details-pane change ------------------


def test_clicking_the_chevron_toggles_expansion_without_opening_a_tab(sample_tree):
    (sample_tree / "alpha" / "sub").mkdir()  # a subfolder: alpha has something to expand into
    fm = FileManager(sample_tree, width=120, height=30)
    alpha = next(c for c in fm._visible()[1] if c.name == "alpha")

    _click_tree_chevron(fm, "alpha")
    assert alpha.expanded is True
    assert not fm.open, "a chevron click only expands; it doesn't open a details tab"

    _let_double_click_window_pass()
    _click_tree_chevron(fm, "alpha")
    assert alpha.expanded is False


# --- scroll stays put --------------------------------------------------------


def test_this_apps_own_scroll_offset_is_unmoved_by_a_tree_click(sample_tree):
    """The one thing this app's own code is responsible for -- its
    `self.scroll` (the `scroll_offset` it hands the tree descriptor every
    frame) -- never changes just because a row was clicked; only a cursor
    move that would otherwise leave the viewport adjusts it
    (`_scroll_to_cursor`). See the module doc for why this is checked
    against model state rather than the painted screen."""
    fm = FileManager(sample_tree, width=120, height=30)
    assert fm.scroll == 0

    _click_tree_row(fm, "alpha")
    assert fm.scroll == 0

    _let_double_click_window_pass()
    _click_tree_row(fm, "beta")
    assert fm.scroll == 0


@pytest.mark.xfail(
    reason=(
        "quadraui's Tree widget (reproducible on the headless TestBackend, "
        "not just a real terminal) paints a focus border over its own first "
        "content row the instant it gains focus from a mouse click, "
        "regardless of this app's own scroll_offset -- filed upstream."
    ),
    strict=True,
)
def test_root_row_stays_painted_on_screen_after_a_tree_click(sample_tree):
    fm = FileManager(sample_tree, width=120, height=30)
    root_name = fm.root.name
    assert f"/ {root_name}" in fm.app.screen()

    _click_tree_row(fm, "alpha")

    assert f"/ {root_name}" in fm.app.screen()


# --- unreadable folder --------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="chmod doesn't restrict reads on Windows")
@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores permission bits")
def test_clicking_an_unreadable_folder_reports_the_reason(sample_tree):
    blocked = sample_tree / "blocked"
    blocked.mkdir()
    blocked.chmod(0o000)
    try:
        fm = FileManager(sample_tree, width=120, height=30)
        _click_tree_row(fm, "blocked")

        assert "Permission denied" in fm.message
        assert str(blocked) in fm.message
        assert "Can't read" in fm.app.screen()
    finally:
        blocked.chmod(0o755)


@pytest.mark.skipif(sys.platform == "win32", reason="chmod doesn't restrict reads on Windows")
@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores permission bits")
def test_an_unreadable_root_reports_the_reason_at_startup(tmp_path):
    tmp_path.chmod(0o000)
    try:
        fm = FileManager(tmp_path, width=120, height=30)
        assert "Permission denied" in fm.message
        assert "Can't read" in fm.app.screen()
    finally:
        tmp_path.chmod(0o755)
