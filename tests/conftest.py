"""Black-box test harness. Builds a known filesystem tree and a `FileManager`
driven headlessly, so tests assert on the *rendered screen* of the running app
(the acceptance bar for this repo — see README). Native-backend behavior
(window/tray/native file ops) is verified manually, not here."""

import shutil
import time
from pathlib import Path

import pytest
from quadraui.testing import Harness

from quadraui_files import FileManager
from quadraui_files.app import Place, PlaceSection


class _FakeTrash:
    """Moves a path into a private per-test directory instead of the real OS
    Trash, and back again on restore -- the same before/after effect on disk
    a test asserts on, without `move_to_trash` risking a multi-minute block
    against a slow or sandboxed system Trash."""

    def __init__(self, directory: Path) -> None:
        self._dir = directory
        self._dir.mkdir(exist_ok=True)
        self._trashed: dict[str, Path] = {}
        self._seq = 0

    def move_to_trash(self, path: str) -> None:
        self._seq += 1
        src = Path(path)
        dest = self._dir / f"{self._seq}-{src.name}"
        shutil.move(str(src), str(dest))
        self._trashed[path] = dest

    def restore_from_trash(self, path: str) -> None:
        dest = self._trashed.pop(path, None)
        if dest is None:
            raise FileNotFoundError(f"nothing trashed at {path!r}")
        shutil.move(str(dest), path)


class _NoDesktopActions:
    """Wraps a real `QuiAppActions` handle, recording `open_path` and
    `reveal_in_file_manager` instead of queuing them. Those hand the path to
    the desktop, which on a Mac really opens TextEdit/Finder windows for
    every run of the suite. `move_to_trash`/`restore_from_trash` go through
    `trash` (a `_FakeTrash`) instead of the real OS Trash, for the same
    reason -- real disk effect, no host Trash involved. Everything else
    (toasts, dialogs, the cursor...) delegates to the real handle."""

    def __init__(self, inner, trash: _FakeTrash):
        self._inner = inner
        self._trash = trash
        self.opened: list[str] = []
        self.revealed: list[str] = []

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def open_path(self, path: str) -> None:
        self.opened.append(path)

    def reveal_in_file_manager(self, path: str) -> None:
        self.revealed.append(path)

    def move_to_trash(self, path: str) -> None:
        self._trash.move_to_trash(path)

    def restore_from_trash(self, path: str) -> None:
        self._trash.restore_from_trash(path)


@pytest.fixture(autouse=True)
def _no_desktop_windows(monkeypatch, tmp_path_factory):
    # A directory of its own, not a subdirectory of `tmp_path` -- `sample_tree`
    # *is* `tmp_path` (see `_make_tree`), so a trash dir nested under it would
    # show up as one more child of the tree every test builds against.
    trash = _FakeTrash(tmp_path_factory.mktemp("trash"))
    real_init = FileManager.__init__

    def init(self, *args, **kwargs):
        # The real sidebar lists this machine's own places (Finder's
        # Favorites, mounted volumes...); tests get an empty one unless they
        # pass `sections`, so screens don't depend on the host.
        kwargs.setdefault("sections", [])
        real_init(self, *args, **kwargs)
        self.actions = _NoDesktopActions(self.actions, trash)

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
    here lands inside that row, details-table or tree alike. `click`/
    `double_click`/`find_row` stay pixel-based because most of the suite
    still calls them this way; a test built from scratch (or migrated) should
    reach for the `h` fixture and `pointer()` below instead, which hold no
    coordinate at all."""
    for y, line in enumerate(fm.app.screen().splitlines()):
        x = line.find(text)
        if x >= 0:
            return float(x + 1), float(y)
    raise AssertionError(f"{text!r} not on screen:\n{fm.app.screen()}")


@pytest.fixture
def h(quadraui_harness):
    """A `quadraui.testing.Harness` factory bound to this test's own
    `quadraui_harness` (so its teardown is still handled): `h(fm)` wraps a
    `FileManager` built with whatever constructor args the test needs --
    `FileManager` only ever exposes a plain `QuiApp`, so the harness needs
    the same `_render_frame` the app was given, same as
    `quadraui.testing.harness(qui_app, render=...)`'s own doc describes.

        def test_x(sample_tree, h):
            fm = FileManager(sample_tree)
            ui = h(fm)
            ui.find(role="data_table").row("readme.txt").click()
    """

    def build(fm: FileManager) -> Harness:
        # A trampoline, not a bound method -- same reason `app.py` installs
        # one on `fm.app` itself: re-resolves `fm._render_frame` on every
        # call, so a hot reload that swaps `fm.__class__` is still reflected.
        return quadraui_harness(fm.app, render=lambda: fm._render_frame())

    return build


def pointer(
    h: Harness,
    text: str,
    *,
    button: str = "Left",
    shift: bool = False,
    ctrl: bool = False,
    alt: bool = False,
    meta: bool = False,
) -> None:
    """A `MouseDown`/`MouseUp` pair wherever `text` painted, carrying a
    `button` or modifiers `Harness.click_text` has no parameters for -- the
    escape hatch for a right-click or a modifier-click (a drag's own two
    ends are just two calls to `h.dispatch(...)` with the same positions
    this would compute). Built on the harness's own public `locate_all()` +
    `dispatch()`, so the test names what's on screen instead of holding a
    coordinate."""
    found = h.locate_all(text)
    if not found:
        raise AssertionError(f"{text!r} not on screen:\n{h.screen()}")
    position = {"x": found[0][0], "y": found[0][1]}
    modifiers = {"shift": shift, "ctrl": ctrl, "alt": alt, "cmd": meta}
    h.dispatch({"MouseDown": {"position": position, "button": button, "modifiers": modifiers}})
    h.dispatch({"MouseUp": {"position": position, "button": button}})


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
