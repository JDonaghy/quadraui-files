"""#59: `fs.py`/`search.py`/`places.py`/`tags.py` hold the framework-free
leaves split out of `app.py` -- the fs model, the search worker, the per-OS
sidebar places, and the macOS tag reader. None of them imports `quadraui`,
so each has to load fine even with no `quadraui` wheel installed at all.
`app.py` still re-exports every moved name, so a plain
`from quadraui_files.app import ...` keeps working for everything else in
this suite (and for `--reload`, which snapshots/restores that module's
whole `__dict__`).

Run in a subprocess, not in-process: by the time this test runs,
`quadraui_files` (and `quadraui`) are already imported and cached in
`sys.modules` from collecting the rest of the suite, so poking
`sys.modules["quadraui"]` here wouldn't exercise a fresh import at all."""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"

_BLOCK_QUADRAUI_AND_IMPORT = """
import sys
sys.path.insert(0, {src!r})
sys.modules["quadraui"] = None
import quadraui_files.fs
import quadraui_files.search
import quadraui_files.places
import quadraui_files.tags
print("ok")
"""


def _run(script: str) -> subprocess.CompletedProcess:
    # `-I` (isolated mode): no implicit site/user-site dirs, no inherited
    # `PYTHONPATH` -- so the only way `quadraui` becomes importable is if
    # one of these four modules reaches for it itself.
    return subprocess.run(
        [sys.executable, "-I", "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_fs_search_places_tags_import_with_quadraui_blocked():
    done = _run(_BLOCK_QUADRAUI_AND_IMPORT.format(src=str(SRC)))
    assert done.returncode == 0, f"stdout={done.stdout!r} stderr={done.stderr!r}"
    assert "ok" in done.stdout


def test_app_still_reexports_the_moved_names():
    """`app.py` needs a real `quadraui`, but once that's available every
    name `fs`/`search`/`places`/`tags` define is still reachable straight
    off `quadraui_files.app`, unchanged for every other test in this suite."""
    script = f"""
import sys
sys.path.insert(0, {str(SRC)!r})
from quadraui_files import app
for name in (
    "Node", "load_children", "ensure_loaded", "build_root", "FS_WATCH_WAKE",
    "SearchState", "SEARCH_WAKE",
    "Place", "PlaceSection", "default_sections",
    "TagColor", "TAG_COLOR_NAMES", "TagReader", "_MacTagReader", "_NullTagReader", "TAG_READER",
):
    assert hasattr(app, name), name
print("ok")
"""
    done = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, f"stdout={done.stdout!r} stderr={done.stderr!r}"
    assert "ok" in done.stdout
