"""Finder-style search (#56): a search tab whose listing is the result set.

A search runs on a daemon thread (`_search_worker`), never in `render()` or
the handler, and hands its results over through `SearchState.pending`; the
thread posts `SEARCH_WAKE` through the waker and the wake, dispatched on the
run loop's own thread, moves them into the tab (`FileManager.
_drain_searches`). Two scopes, Finder's own: the folder the search started
from (walk its subfolders -- every OS, and what the test suite drives) and
"This Mac" (Spotlight's `mdfind`, macOS only). Both match names only,
case-insensitively, and skip dotfiles the same way `load_children` does.

Results are *detached* `Node`s (`parent is None`): giving each one a real
parent chain would mean `_node_for` reading every ancestor directory on the
UI thread. Anything that needs the real model node -- navigating into a
folder result, rename, trash, Get Info -- resolves it by path
(`FileManager._resolve_result`).

Framework-free -- no `quadraui` import. `quadraui_files.app` re-exports
every public name here; tests and `--reload` keep importing them from
there.
"""

from __future__ import annotations

import os
import subprocess
import sys
import shutil
import threading
import time
from pathlib import Path
from typing import Callable, Iterable, Iterator

from .fs import Node, _is_under

SEARCH_WAKE = "quadraui_files.search"
SEARCH_SCOPE_FOLDER = "folder"
SEARCH_SCOPE_MAC = "mac"
SEARCH_SCOPE_ACTION_PREFIX = "fm:search:scope:"
SEARCH_FIELD_ACTION = "fm:search:field"  # the address bar's search field, see `_search_field_segment`
SEARCH_RESULT_CAP = 1000  # past this many hits the search stops, like a capped Finder window
_SEARCH_POST_INTERVAL = 0.15  # seconds between wakes while results stream in


class SearchState:
    """One running (or finished) search. The worker thread only ever touches
    `pending`/`done`/`capped`/`error` (under `lock`) and reads `cancel`; the
    run-loop thread drains `pending` into the tab's `node.children` and sets
    `finished` once it has drained a `done` search, which tells the worker to
    stop re-posting its final wake."""

    def __init__(self, query: str, scope: str, root: Node, node: Node) -> None:
        self.query = query
        self.scope = scope
        self.root = root  # the folder the search was started from
        self.node = node  # the search tab's own node
        self.lock = threading.Lock()
        self.pending: list[Node] = []
        self.done = False
        self.capped = False
        self.error: str | None = None
        self.finished = False
        self.cancel = threading.Event()


def _search_of(node: Node | None) -> SearchState | None:
    """`node`'s search, if it is a search tab's node."""
    return getattr(node, "search", None)


def _result_node(path: Path) -> Node | None:
    """A detached result row for `path` (see this section's doc), or `None`
    if it vanished between being found and being stat'ed."""
    try:
        st = path.stat()
    except OSError:
        return None
    is_dir = os.path.isdir(path)
    return Node(
        name=path.name,
        path=path,
        is_dir=is_dir,
        size_bytes=None if is_dir else st.st_size,
        mtime=st.st_mtime,
    )


def _walk_matches(root: Path, query: str) -> Iterator[Path]:
    """Every non-dot entry below `root` whose name contains `query`
    (case-insensitive), breadth of each folder before its subfolders. Dot
    folders aren't descended into, symlinked folders aren't followed, and an
    unreadable folder is skipped rather than ending the search."""
    q = query.lower()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        base = Path(dirpath)
        for name in [*dirnames, *sorted(f for f in filenames if not f.startswith("."))]:
            if q in name.lower():
                yield base / name


def _mdfind(query: str) -> Iterator[str]:
    """Spotlight's name search (`mdfind -name`), one path per line as it
    streams. Closing the generator early kills `mdfind`."""
    proc = subprocess.Popen(
        ["mdfind", "-name", query],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            yield line.rstrip("\n")
    finally:
        proc.kill()
        proc.wait()


def default_spotlight() -> Callable[[str], Iterable[str]] | None:
    """The "This Mac" search runner on this host: `mdfind` on macOS, `None`
    (no This Mac scope offered) anywhere else."""
    if sys.platform == "darwin" and shutil.which("mdfind"):
        return _mdfind
    return None


def _search_worker(state: SearchState, waker, spotlight: Callable[[str], Iterable[str]] | None) -> None:
    """The search thread: find matches, hand them over in batches, and keep
    posting `SEARCH_WAKE` until the run loop has drained the final batch --
    the same re-post-until-acknowledged safety net `_fs_watch_loop`'s doc
    gives, for a backend that drops or coalesces a wake."""
    if state.scope == SEARCH_SCOPE_MAC and spotlight is not None:
        source = (Path(p) for p in spotlight(state.query) if p)
    else:
        source = _walk_matches(state.root.path, state.query)
    count = 0
    last_post = 0.0
    try:
        for path in source:
            if state.cancel.is_set():
                return
            if any(part.startswith(".") for part in path.parts):
                continue  # Spotlight returns dotfiles; the app never lists them
            node = _result_node(path)
            if node is None:
                continue
            with state.lock:
                state.pending.append(node)
            count += 1
            if count >= SEARCH_RESULT_CAP:
                with state.lock:
                    state.capped = True
                break
            now = time.monotonic()
            if now - last_post >= _SEARCH_POST_INTERVAL:
                last_post = now
                waker.post(SEARCH_WAKE)
    except Exception as exc:  # a failed search reports itself, it doesn't kill the app
        with state.lock:
            state.error = str(exc) or type(exc).__name__
    finally:
        close = getattr(source, "close", None)
        if close is not None:
            close()  # stops `mdfind` early on a cap or a cancel
        with state.lock:
            state.done = True
    for _ in range(40):  # ~10s of re-posts at most
        if state.finished or state.cancel.is_set():
            return
        waker.post(SEARCH_WAKE)
        state.cancel.wait(0.25)


def _where_text(path: Path, root: Path | None = None, root_label: str = "") -> str:
    """The search results' Where column: the folder `path` is in. Under the
    folder the search started from (`root`), relative to it (that folder
    itself shows as `root_label`), so a long shared prefix doesn't push the
    part that tells results apart off the end of the column; otherwise with
    the home folder shortened to `~` the way `_window_title` does it."""
    parent = path.parent
    if root is not None and _is_under(parent, root):
        rel = parent.relative_to(root)
        return root_label if rel == Path(".") else rel.as_posix()
    home = Path.home()
    if parent == home:
        return "~"
    try:
        return f"~/{parent.relative_to(home)}"
    except ValueError:
        return str(parent)
