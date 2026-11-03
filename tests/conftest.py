"""Black-box test harness. Builds a known filesystem tree and a `FileManager`
driven headlessly, so tests assert on the *rendered screen* of the running app
(the acceptance bar for this repo — see README). Native-backend behavior
(window/tray/native file ops) is verified manually, not here."""

from pathlib import Path

import pytest

from quadraui_files import FileManager


def _make_tree(root: Path) -> Path:
    (root / "alpha").mkdir()
    (root / "beta").mkdir()
    (root / "alpha" / "notes.txt").write_text("notes")
    (root / "readme.txt").write_text("hello")
    return root


@pytest.fixture
def sample_tree(tmp_path: Path) -> Path:
    """A root with two subfolders (alpha, beta), a file at root, and a file
    inside alpha."""
    return _make_tree(tmp_path)


def activate_child(fm: FileManager, name: str) -> None:
    """Click (RowActivated) the details-table row for `name` in the active
    tab -- the way selecting a file in the listing really happens. Looks up
    `name`'s index in the table's *painted* order (`_visible_children`),
    not raw `folder.children`, so this still points at the right row once a
    filter/sort is applied."""
    folder = fm.open[fm.active_tab]
    idx = [c.name for c in fm._visible_children(folder)].index(name)
    fm.step({"DataTable": [f"fm:grid:{fm.active_tab}", {"RowActivated": {"idx": idx}}]})
