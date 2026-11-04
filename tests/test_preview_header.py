"""F3 black-box tests: the preview pane's one-line header (file name, size,
modified time, and a close control) and the `p` toggle that hides/shows the
whole pane, giving its width back to the details table."""

from conftest import activate_child as _activate_child

from quadraui_files import FileManager
from quadraui_files.app import ENTER_KEY, _key_event


def _open_root_tab(fm: FileManager) -> None:
    fm.step(_key_event(ENTER_KEY))


def _press_char(fm: FileManager, char: str) -> None:
    fm.step(_key_event({"Char": char}))


def _click(fm: FileManager, x: float, y: float) -> None:
    no_mods = {"shift": False, "ctrl": False, "alt": False, "cmd": False}
    for kind in ("MouseDown", "MouseUp"):
        fm.app.push_event({kind: {"position": {"x": x, "y": y}, "button": "Left", "modifiers": no_mods}})
        fm.app.step()


def _find(fm: FileManager, needle: str) -> tuple[int, int]:
    """(x, y) of `needle`'s first occurrence on the painted screen."""
    for y, line in enumerate(fm.app.screen().splitlines()):
        x = line.find(needle)
        if x >= 0:
            return x, y
    raise AssertionError(f"{needle!r} not found on screen:\n{fm.app.screen()}")


def _find_header_close(fm: FileManager) -> tuple[int, int]:
    """(x, y) of the preview header's own × -- the *rightmost* one on its
    row, since an open tab's own closable × paints on that same screen
    row, further left (the tabs bar and the preview header sit side by
    side, at the top of the details|preview split)."""
    for y, line in enumerate(fm.app.screen().splitlines()):
        x = line.rfind("×")
        if x >= 0:
            return x, y
    raise AssertionError(f"no × on screen:\n{fm.app.screen()}")


def test_empty_state_header_says_no_file_selected(sample_tree):
    fm = FileManager(sample_tree)
    _open_root_tab(fm)

    assert "No file selected" in fm.app.screen()


def test_header_shows_name_and_size_above_the_preview_text(sample_tree):
    (sample_tree / "readme.txt").write_text("zzqMARKERzz")
    fm = FileManager(sample_tree, width=200, height=30)  # roomy enough for the header's right segment
    _open_root_tab(fm)

    _activate_child(fm, "readme.txt")

    screen = fm.app.screen()
    size = f"{(sample_tree / 'readme.txt').stat().st_size} B"
    name_y = _find(fm, "readme.txt")[1]
    size_y = _find(fm, size)[1]
    content_y = _find(fm, "zzqMARKERzz")[1]
    assert name_y == size_y, f"name and size aren't on the same header line:\n{screen}"
    assert name_y < content_y, f"header isn't above the preview text:\n{screen}"


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


def test_clicking_the_header_close_control_hides_the_pane(sample_tree):
    (sample_tree / "readme.txt").write_text("zzqMARKERzz")
    fm = FileManager(sample_tree, width=120, height=30)
    _open_root_tab(fm)
    _activate_child(fm, "readme.txt")
    assert "zzqMARKERzz" in fm.app.screen()

    x, y = _find_header_close(fm)
    _click(fm, float(x), float(y))

    screen = fm.app.screen()
    assert fm.preview_visible is False
    assert "zzqMARKERzz" not in screen, f"preview text still showing once closed:\n{screen}"
