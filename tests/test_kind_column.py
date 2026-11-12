"""Black-box coverage for the grid's Kind column: every row paints a
Finder-style file type (Folder / PNG Image / Plain Text / ...), and clicking
the header sorts by it with the same ▲/▼ marker contract the other columns
have. Driven headlessly through `FileManager.step` on the painted screen,
like every other feature tranche's tests."""

from pathlib import Path

from quadraui_files import FileManager
from quadraui_files.app import ENTER_KEY, _key_event


def _make_tree(root: Path) -> Path:
    """Two folders and two files of *different* kinds, so a Kind sort
    visibly reorders rows the Name sort had in a different order."""
    root.mkdir()
    (root / "alpha").mkdir()
    (root / "beta").mkdir()
    (root / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (root / "readme.txt").write_text("hello")
    return root


def _open_root_tab(fm: FileManager) -> None:
    fm.step(_key_event(ENTER_KEY))


def _row_names(fm: FileManager) -> list[str]:
    """The grid's painted row order: each row's first (Name) cell, read off
    the painted screen's table region between the header and the pane's
    blank tail. Names carry the trailing `/` folder marker."""
    rows: list[str] = []
    for line in fm.app.screen().splitlines():
        if line.lstrip().startswith("Name") or "No file selected" in line:
            continue
        for token in ("alpha/", "beta/", "logo.png", "readme.txt"):
            if token in line and not line.lstrip().startswith("│▾"):
                if not rows or rows[-1] != token:
                    rows.append(token)
                break
    return rows


def test_the_grid_paints_a_kind_column(tmp_path):
    fm = FileManager(_make_tree(tmp_path / "root"), width=140, height=30)
    _open_root_tab(fm)

    screen = fm.app.screen()

    assert "Kind" in screen, "no Kind header on the grid"
    for text in ("Folder", "PNG Image", "Plain Text"):
        assert text in screen, f"kind {text!r} never painted"


def test_clicking_the_kind_header_sorts_by_kind_and_then_reverses(tmp_path):
    fm = FileManager(_make_tree(tmp_path / "root"), width=140, height=30)
    _open_root_tab(fm)
    assert _row_names(fm) == ["alpha/", "beta/", "logo.png", "readme.txt"]

    fm.step({"DataTable": ["fm:grid:0", {"HeaderClicked": {"col": 3}}]})

    # Folders first, then files by kind label: "plain text" sorts before
    # "png image" -- a different file order than the Name sort had.
    assert _row_names(fm) == ["alpha/", "beta/", "readme.txt", "logo.png"]
    assert "Kind ▲" in fm.app.screen(), "no ascending marker on the Kind header"

    fm.step({"DataTable": ["fm:grid:0", {"HeaderClicked": {"col": 3}}]})

    # Reversed: files before folders, kinds descending, names as tiebreak.
    assert _row_names(fm) == ["logo.png", "readme.txt", "beta/", "alpha/"]
    assert "Kind ▼" in fm.app.screen(), "no descending marker on the Kind header"
