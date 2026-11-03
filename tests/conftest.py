"""Black-box test harness. Builds a known filesystem tree and a `FileManager`
driven headlessly, so tests assert on the *rendered screen* of the running app
(the acceptance bar for this repo — see README). Native-backend behavior
(window/tray/native file ops) is verified manually, not here."""

from pathlib import Path

import pytest


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
