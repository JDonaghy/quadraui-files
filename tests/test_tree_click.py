"""F1 black-box tests: a tree-row click selects and shows that folder in the
details pane without touching its expansion state; only the chevron (or
Left/Right) expands/collapses; the clicked row's own tree position doesn't
move this app's own scroll offset; and an unreadable folder reports why, not
just "0 items".

Most assertions here read model state (`fm.cursor`/`fm.open`/`fm.scroll`/
`fm.message`) rather than `fm.app.screen()`, since model state is what
each of these behaviors is actually about. The tree opts into
`TreeStyle.bordered` (see `TREE_STYLE` in `app.py`), so the TUI focus ring
a mouse click gives the tree lands on that reserved border instead of
overwriting row 0 -- `test_root_row_stays_painted_on_screen_after_a_tree_click`
below checks that directly against the screen."""

import os
import sys

import pytest

from conftest import click as _click
from conftest import let_double_click_window_pass as _let_double_click_window_pass
from quadraui_files import FileManager
from quadraui_files.app import DOWN_KEY, _key_event


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


def test_root_row_stays_painted_on_screen_after_a_tree_click(tmp_path):
    # A fixed, short root name, unlike `sample_tree` (which hands back
    # `tmp_path` itself, named after this test's own -- long -- node id):
    # this test is about the root row staying painted, not about how much
    # of a long name the narrowed, bordered tree pane can still fit.
    root = tmp_path / "root"
    root.mkdir()
    (root / "alpha").mkdir()
    fm = FileManager(root, width=120, height=30)
    root_name = fm.root.name
    assert f"/ {root_name}" in fm.app.screen()

    _click_tree_row(fm, "alpha")

    assert f"/ {root_name}" in fm.app.screen()


def test_last_folder_scrolls_into_the_bordered_trees_painted_window(tmp_path):
    """`TreeStyle.bordered` costs the tree two painted rows (one top, one
    bottom) that the shared row band `_tree_capacity` doesn't know about --
    `_scroll_to_cursor` has to use `_tree_painted_capacity` instead, or the
    scroll clamp caps two rows short and the last folders in a tree taller
    than its pane can never reach the rows the tree actually paints."""
    root = tmp_path / "root"
    root.mkdir()
    fm = FileManager(root, width=120, height=30)
    capacity = fm._tree_capacity()
    names = [f"d{i:02d}" for i in range(capacity + 5)]  # taller than the pane
    for name in names:
        (root / name).mkdir()
    fm = FileManager(root, width=120, height=30)  # re-scan with the new folders on disk

    for _ in range(len(names)):
        fm.step(_key_event(DOWN_KEY))

    assert fm.cursor.name == names[-1]
    screen = fm.app.screen()
    assert f"/ {names[-1]}" in screen, f"last row {names[-1]!r} not painted on screen:\n{screen}"


def test_hovering_a_tree_row_anchors_the_tooltip_below_that_rows_own_line(tmp_path):
    """`_show_tree_tooltip` adds `_TREE_BORDER_INSET` into the anchor it
    hands the engine so the tooltip tracks the row's own (bordered-tree)
    screen position, not a stale unbordered one. Pinned exactly rather than
    just "somewhere below": the tooltip opens one line below its anchor
    (the engine's default `Bottom` placement plus its own 1-cell margin),
    and the tooltip box's own top border takes the first line of that, so
    the text itself lands on `row_line + 3`. If the inset dropped back out
    of the anchor the diff adds it to, every row's tooltip would shift up
    by exactly one line."""
    root = tmp_path / "root"
    root.mkdir()
    (root / "alpha").mkdir()
    fm = FileManager(root, width=120, height=30)
    fm.step(_key_event(DOWN_KEY))  # cursor -> "alpha", the "hover"
    assert fm.cursor.name == "alpha"

    _, row_line = _row_icon_x(fm, "alpha")
    lines = fm.app.screen().splitlines()
    tooltip_line = next(i for i, line in enumerate(lines) if str(fm.cursor.path) in line)
    assert tooltip_line == row_line + 3, (
        f"tooltip for row {row_line} painted on {tooltip_line}:\n{fm.app.screen()}"
    )


def test_a_long_root_name_truncates_without_breaking_the_bordered_pane(tmp_path):
    """A name longer than the tree pane's own (now 2-columns-narrower,
    bordered) content width must still render: clipped to a prefix, never
    raising and never spilling past the tree's own border into the pane
    beside it -- the kind of long-name coverage
    `test_root_row_stays_painted_on_screen_after_a_tree_click` deliberately
    sidesteps by using a short, fixed root name instead."""
    long_name = "x" * 60
    root = tmp_path / long_name
    root.mkdir()
    fm = FileManager(root, width=40, height=20)  # narrow enough that 60 chars can't fit

    screen = fm.app.screen()
    lines = screen.splitlines()
    assert len({len(line) for line in lines}) == 1, f"a painted line overflowed:\n{screen}"

    root_line = next(line for line in lines if "/ x" in line)
    assert long_name not in root_line, "a too-long name should be truncated, not overflow"
    assert "x" in root_line  # some prefix of it is still visible


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
