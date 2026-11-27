"""F3 black-box tests: the preview pane's one-line header (file name, size,
modified time, and a close control) and the `p` toggle that hides/shows the
whole pane, giving its width back to the details table."""

from conftest import activate_child as _activate_child

from quadraui_files import FileManager
from quadraui_files.app import ENTER_KEY, _key_event


def _open_root_tab(fm: FileManager) -> None:
    """Opens the root folder as a details tab *and* shows the preview pane
    -- hidden by default now (View menu / `p`), but every test in this
    file is specifically about its header, so showing it is part of this
    file's own "open the tab" setup, not something each test repeats."""
    fm.step(_key_event(ENTER_KEY))
    fm._toggle_preview()


def _press_char(fm: FileManager, char: str) -> None:
    fm.step(_key_event({"Char": char}))


def test_empty_state_header_says_no_file_selected(sample_tree):
    # A realistic window, not the 100-column default -- see
    # `test_header_shows_name_and_size_above_the_preview_text`'s own doc for
    # why the 100-column default no longer leaves enough header budget for
    # "No file selected" (17 characters) to survive unellipsized.
    fm = FileManager(sample_tree, width=120)
    _open_root_tab(fm)

    screen = fm.app.screen()
    occurrences = [y for y, line in enumerate(screen.splitlines()) if "No file selected" in line]
    # Both the header (no selection yet) and the preview body (unchanged
    # `preview_lines` hint) say so -- discriminate against the unchanged
    # pre-header behaviour by requiring *both* rows, header above body.
    assert len(occurrences) == 2, f"expected a header row and a body row saying so:\n{screen}"
    header_y, body_y = occurrences
    assert header_y < body_y, f"header isn't above the body hint:\n{screen}"


def test_header_shows_name_and_size_above_the_preview_text(sample_tree, h):
    (sample_tree / "readme.txt").write_text("zzqMARKERzz")
    # A realistic window, not the 100-column default: `fm:split`'s own
    # padding and `fm:detail_split`'s own gap each cost the preview column
    # a cell `_preview_column_width_cells` now deducts for real, and the
    # 100-column default leaves too little budget left over for this
    # 10-character name to survive unellipsized.
    fm = FileManager(sample_tree, width=120)
    ui = h(fm)
    _open_root_tab(fm)

    _activate_child(fm, "readme.txt")

    screen = ui.screen()
    size = f"{(sample_tree / 'readme.txt').stat().st_size} B"
    name_y = ui.locate_all("readme.txt")[0][1]
    size_y = ui.locate_all(size)[0][1]
    content_y = ui.locate_all("zzqMARKERzz")[0][1]
    assert name_y == size_y, f"name and size aren't on the same header line:\n{screen}"
    assert name_y < content_y, f"header isn't above the preview text:\n{screen}"


def test_header_size_survives_at_a_narrow_width(sample_tree):
    """The size is a left segment next to the name, so it isn't the first
    thing a narrow preview column drops (unlike the modified time, a right
    segment, which may legitimately disappear here)."""
    (sample_tree / "readme.txt").write_text("zzqMARKERzz")
    fm = FileManager(sample_tree, width=80, height=24)
    _open_root_tab(fm)

    _activate_child(fm, "readme.txt")

    screen = fm.app.screen()
    size = f"{(sample_tree / 'readme.txt').stat().st_size} B"
    assert "readme.txt" in screen, f"name missing at width 80:\n{screen}"
    assert size in screen, f"size missing at width 80:\n{screen}"


def test_p_hides_the_pane_and_widens_the_details_table(sample_tree):
    (sample_tree / "readme.txt").write_text("zzqMARKERzz")
    fm = FileManager(sample_tree)
    _open_root_tab(fm)
    _activate_child(fm, "readme.txt")
    assert "zzqMARKERzz" in fm.app.screen()
    dividers_before = fm.app.screen().splitlines()[3].count("│")

    _press_char(fm, "p")

    screen = fm.app.screen()
    assert "zzqMARKERzz" not in screen, f"preview text still showing once hidden:\n{screen}"
    assert fm.preview_visible is False
    dividers_after = screen.splitlines()[3].count("│")
    assert dividers_after == dividers_before - 1, (
        f"details table didn't widen into the preview's old column:\n{screen}"
    )


def test_p_twice_restores_the_pane(sample_tree):
    (sample_tree / "readme.txt").write_text("zzqMARKERzz")
    fm = FileManager(sample_tree)
    _open_root_tab(fm)
    _activate_child(fm, "readme.txt")

    _press_char(fm, "p")
    assert "zzqMARKERzz" not in fm.app.screen()

    _press_char(fm, "p")

    assert "zzqMARKERzz" in fm.app.screen()
    assert fm.preview_visible is True


def test_clicking_the_header_close_control_hides_the_pane(sample_tree, h):
    (sample_tree / "readme.txt").write_text("zzqMARKERzz")
    fm = FileManager(sample_tree, width=120, height=30)
    ui = h(fm)
    _open_root_tab(fm)
    _activate_child(fm, "readme.txt")
    assert "zzqMARKERzz" in ui.screen()

    # The *rightmost* "×" on screen: an open tab's own closable × paints on
    # the same screen row, further left (the tabs bar and the preview
    # header sit side by side, at the top of the details|preview split).
    ui.click_text("×", nth=-1)

    screen = ui.screen()
    assert fm.preview_visible is False
    assert "zzqMARKERzz" not in screen, f"preview text still showing once closed:\n{screen}"
