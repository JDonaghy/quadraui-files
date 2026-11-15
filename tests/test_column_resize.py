"""Black-box coverage for the details grid's column resize: dragging a
header divider pins that column's width (`DataTableEvent::ColumnResized`'s
own contract -- "App should update column_overrides[col]"), shared globally
across every open tab's own table, the same way `sort_col`/`ratio` already
are. Driven headlessly through `FileManager.step` with real synthesized
`MouseDown`/`MouseMoved`/`MouseUp` events, like `test_detail_click.py`'s own
clicks."""

from quadraui_files import FileManager
from quadraui_files.app import ENTER_KEY, _key_event

_NO_MODS = {"shift": False, "ctrl": False, "alt": False, "cmd": False}


def _open_root_tab(fm: FileManager) -> None:
    fm.step(_key_event(ENTER_KEY))


def _header_row(fm: FileManager) -> int:
    lines = fm.app.screen().splitlines()
    return next(i for i, line in enumerate(lines) if "Name" in line and "Kind" in line)


def _divider_x(fm: FileManager, col: int) -> float:
    """The painted x of the divider to the *right* of column `col` (0 Name,
    1 Size, 2 Modified, 3 Kind) -- the `col+1`'th `"│"` on the header row
    counting from the "Name" label itself, so the sidebar's own border and
    the grid's own left border (both painted as `"│"` too, earlier on the
    same row) are never miscounted as column dividers."""
    line = fm.app.screen().splitlines()[_header_row(fm)]
    x = line.index("Name")
    for _ in range(col + 1):
        x = line.index("│", x + 1)
    return float(x)


def _drag_divider(fm: FileManager, col: int, dx: float) -> None:
    y = float(_header_row(fm))
    x0 = _divider_x(fm, col)
    fm.step({"MouseDown": {"position": {"x": x0, "y": y}, "button": "Left", "modifiers": _NO_MODS}})
    fm.step({"MouseMoved": {"position": {"x": x0 + dx, "y": y}, "buttons": {"left": True}}})
    fm.step({"MouseUp": {"position": {"x": x0 + dx, "y": y}, "button": "Left"}})


def test_dragging_the_name_divider_pins_that_columns_width(sample_tree):
    fm = FileManager(sample_tree)
    _open_root_tab(fm)
    assert fm.column_overrides == [None, None, None, None]

    _drag_divider(fm, 0, 10.0)

    assert fm.column_overrides[0] is not None
    assert fm.column_overrides[1:] == [None, None, None]


def test_a_resize_survives_a_filter_and_a_re_render(sample_tree):
    """`column_overrides` isn't recomputed from the drag each frame -- it's
    stored once and fed back every time, so it has to still be in effect
    after something else (the filter box) triggers a fresh render."""
    fm = FileManager(sample_tree)
    _open_root_tab(fm)
    _drag_divider(fm, 0, 10.0)
    width = fm.column_overrides[0]

    fm._start_filter()
    fm._cancel_edit()

    assert fm.column_overrides[0] == width


def test_resizing_in_one_tab_resizes_the_other_tabs_table_too(sample_tree):
    """`column_overrides` is app-global, like `sort_col`/`ratio` -- a resize
    made while tab 1 is active must show up in tab 0's own painted table
    too, not just stay local to the table it was dragged on."""
    fm = FileManager(sample_tree)
    _open_root_tab(fm)
    fm._open()  # a second tab on the same folder; it becomes active
    assert fm.active_tab == 1

    _drag_divider(fm, 0, 10.0)
    divider_in_tab_1 = _divider_x(fm, 0)

    fm.active_tab = 0
    divider_in_tab_0 = _divider_x(fm, 0)

    assert divider_in_tab_0 == divider_in_tab_1


def test_direct_callers_that_pass_no_overrides_get_the_plain_flex_columns(sample_tree):
    """`details_table` itself, called directly (as `--dump` does) without
    ever passing `column_overrides`, must not require it -- defaults to
    "no overrides", not a crash."""
    from quadraui_files.app import details_table

    fm = FileManager(sample_tree)
    descriptor = details_table(fm.cursor, 0)
    assert descriptor["column_overrides"] == [None, None, None, None]
