"""Black-box test harness. Builds a known filesystem tree and a `FileManager`
driven headlessly, so tests assert on the *rendered screen* of the running app
(the acceptance bar for this repo — see README). Native-backend behavior
(window/tray/native file ops) is verified manually, not here."""

import time
from pathlib import Path

import pytest

from quadraui_files import FileManager
from quadraui_files.app import Place, PlaceSection


class _NoDesktopActions:
    """Wraps a real `QuiAppActions` handle, recording `open_path` and
    `reveal_in_file_manager` instead of queuing them. Those hand the path to
    the desktop, which on a Mac really opens TextEdit/Finder windows for
    every run of the suite. Everything else delegates to the real handle --
    trash and restore included, since tests assert on their effect on disk."""

    def __init__(self, inner):
        self._inner = inner
        self.opened: list[str] = []
        self.revealed: list[str] = []

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def open_path(self, path: str) -> None:
        self.opened.append(path)

    def reveal_in_file_manager(self, path: str) -> None:
        self.revealed.append(path)


@pytest.fixture(autouse=True)
def _no_desktop_windows(monkeypatch):
    real_init = FileManager.__init__

    def init(self, *args, **kwargs):
        # The real sidebar lists this machine's own places (Finder's
        # Favorites, mounted volumes...); tests get an empty one unless they
        # pass `sections`, so screens don't depend on the host.
        kwargs.setdefault("sections", [])
        real_init(self, *args, **kwargs)
        self.actions = _NoDesktopActions(self.actions)

    monkeypatch.setattr(FileManager, "__init__", init)


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


def sample_sections(root: Path) -> list[PlaceSection]:
    """A fixed two-place sidebar over `sample_tree`."""
    return [
        PlaceSection(
            "Favorites",
            (Place("Root", root, "folder"), Place("Alpha", root / "alpha", "folder")),
        )
    ]


@pytest.fixture
def sidebar_fm(sample_tree: Path) -> FileManager:
    """A `FileManager` on `sample_tree` with `sample_sections` in its sidebar."""
    return FileManager(sample_tree, width=120, height=30, sections=sample_sections(sample_tree))


NO_MODS = {"shift": False, "ctrl": False, "alt": False, "cmd": False}


def click(fm: FileManager, x: float, y: float) -> None:
    """A real synthesized `MouseDown`/`MouseUp` pair at painted coordinates
    `(x, y)` -- a single click, the way a user's mouse reaches the app
    (`tests/test_tree_click.py`, `tests/test_detail_click.py`)."""
    for kind in ("MouseDown", "MouseUp"):
        fm.app.push_event({kind: {"position": {"x": x, "y": y}, "button": "Left", "modifiers": NO_MODS}})
        fm.app.step()


def double_click(fm: FileManager, x: float, y: float) -> None:
    """A real synthesized double-click at painted coordinates `(x, y)`,
    pushed as the engine's own bare `DoubleClick` event rather than two
    `click()`s separated by a wall-clock gap: the pinned upstream resolves
    either to the same `RowDoubleClicked`/`ItemDoubleClicked` semantic (a
    host synthesizing clicks, e.g. a test, is explicitly allowed to skip the
    `MouseDown`/`MouseUp` pair that precedes one on a real backend), and this
    form can't flake against a loaded CI box's wall-clock timing the way two
    back-to-back `click()`s racing the double-click detection window could."""
    fm.app.push_event({"DoubleClick": {"widget": None, "position": {"x": x, "y": y}}})
    fm.app.step()


# quadraui's double-click detection keys off real wall-clock time between two
# `MouseDown`/`MouseUp` pairs, not anything carried on the event itself -- so
# two clicks fired back-to-back (as tests otherwise would when they mean two
# distinct single clicks) land close enough in time to coalesce into a
# `RowDoubleClicked`/`ItemDoubleClicked` instead. A real user's two clicks
# are never this close together; tests that click twice in a row call
# `let_double_click_window_pass()` between them to get the same
# single-click behaviour a real click sequence would.
_DOUBLE_CLICK_WINDOW_S = 0.6


def let_double_click_window_pass() -> None:
    time.sleep(_DOUBLE_CLICK_WINDOW_S)


def find_row(fm: FileManager, text: str) -> tuple[float, float]:
    """(x, y) of `text`'s first occurrence on the painted screen -- clicking
    here lands inside that row, details-table or tree alike."""
    for y, line in enumerate(fm.app.screen().splitlines()):
        x = line.find(text)
        if x >= 0:
            return float(x + 1), float(y)
    raise AssertionError(f"{text!r} not on screen:\n{fm.app.screen()}")


def activate_child(fm: FileManager, name: str) -> None:
    """A `DataTable/RowActivated` for the details-table row `name` in the
    active tab -- the keyboard-Enter-on-a-focused-row semantic (see
    `app.py`'s own doc on `RowSelected` vs `RowDoubleClicked`/
    `RowActivated`), used throughout this suite as a convenient shortcut to
    both select `name` and queue opening it with the OS, without needing a
    real synthesized click (see `tests/test_detail_click.py` for those).
    Looks up `name`'s index in the table's *painted* order
    (`_visible_children`), not raw `folder.children`, so this still points
    at the right row once a filter/sort is applied."""
    folder = fm.open[fm.active_tab]
    idx = [c.name for c in fm._visible_children(folder)].index(name)
    fm.step({"DataTable": [f"fm:grid:{fm.active_tab}", {"RowActivated": {"idx": idx}}]})
