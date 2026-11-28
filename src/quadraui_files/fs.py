"""The lazily-scanned filesystem model: `Node`, loading it from disk, the
name sort it's kept in, and the fs-watch signature `FileManager.
enable_fs_watch` diffs against. Framework-free -- no `quadraui` import, so
it loads (and is unit-testable) even on a host with no quadraui wheel
installed at all.

`quadraui_files.app` re-exports every public name here; tests and
`--reload` keep importing them from there.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Only for the `Node.search` type hint below -- `search.py` imports
    # `Node` from here, so importing it back at runtime would be a cycle;
    # `from __future__ import annotations` keeps every annotation a string,
    # so this guarded import costs nothing outside a type checker.
    from .search import SearchState

# The `User` payload `FileManager.enable_fs_watch`'s watcher thread posts
# through the waker on a filesystem change -- the same shape `HOT_RELOAD_WAKE`
# is for hot reload, just this app's own sentinel rather than one imported
# from `quadraui.app.hot_reload`.
FS_WATCH_WAKE = "quadraui_files.fs_watch"


@dataclass
class Node:
    """One filesystem entry in the lazily-scanned model.

    `children is None` means "not loaded yet" -- a directory whose contents
    have never been read. After loading, `children` is a (possibly empty)
    list. Files always keep `children is None` and are never loaded.
    `expanded` is True only for directories the user has opened in the tree.
    """

    name: str
    path: Path
    is_dir: bool
    size_bytes: int | None = None
    mtime: float | None = None
    parent: "Node | None" = field(default=None, repr=False)
    children: list["Node"] | None = None
    expanded: bool = False
    load_error: bool = False
    load_error_reason: str | None = None  # e.g. "Permission denied", set with load_error
    # Set only on a search tab's own node (#56): its `children` are the
    # results, not a directory listing. Read it with `_search_of`, which
    # also covers a `Node` built before a hot reload added this field.
    search: "SearchState | None" = field(default=None, repr=False)

    def subdirs(self) -> list["Node"]:
        """Loaded child directories in display order (empty if not loaded)."""
        return [c for c in (self.children or ()) if c.is_dir]


def _safe_size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None


def _safe_mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _sort_key(node: Node) -> tuple[bool, str]:
    """Directories first, then case-insensitive name."""
    return (not node.is_dir, node.name.lower())


def _invalid_rename_name(new_name: str) -> str | None:
    """None if `new_name` is safe to rename onto; otherwise a human-readable
    reason it's rejected. A path separator (`/`, or `os.sep`/`os.altsep` on
    this platform) makes `Path.with_name` raise `ValueError` instead of the
    `OSError` a failed rename raises, so it has to be caught here rather
    than relying on that except clause. A name that is only dots (`.`/`..`)
    raises the same way. A leading dot is rejected too: `load_children`
    skips dotfiles, so a renamed entry would silently vanish from the
    listing on the very next refresh."""
    separators = {"/", os.sep, os.altsep} - {None}
    if any(sep in new_name for sep in separators):
        return "name can't contain a path separator"
    if new_name.startswith("."):
        return "hidden names aren't shown here"
    return None


def _unique_sibling_name(parent: Node, base: str, suffix: str = "") -> str:
    """The first of `base+suffix`, `base 2+suffix`, `base 3+suffix`, ... that
    isn't already a name in `parent.children` (case-insensitive, matching a
    case-insensitive filesystem's own collision rule -- same check `_rename`
    makes). Used for New Folder's "untitled folder"/"untitled folder 2"/...
    and Duplicate/Paste's "name copy"/"name copy 2"/..., Finder's own
    numbering for both."""
    existing = {c.name.lower() for c in (parent.children or ())}
    name = f"{base}{suffix}"
    if name.lower() not in existing:
        return name
    n = 2
    while True:
        name = f"{base} {n}{suffix}"
        if name.lower() not in existing:
            return name
        n += 1


def _copy_entry_to(source: Node, new_path: Path, parent: Node) -> Node:
    """Copy `source`'s file (or, recursively, its whole directory tree) onto
    `new_path` and return the `Node` for it, parented under `parent` --
    shared by `_duplicate` (same folder) and `_paste` (possibly a different
    one). Raises `OSError` on failure; the caller reports it as a message,
    same as `_rename`'s own disk-op failures."""
    if source.is_dir:
        shutil.copytree(source.path, new_path)
    else:
        shutil.copy2(source.path, new_path)
    return Node(
        name=new_path.name,
        path=new_path,
        is_dir=source.is_dir,
        size_bytes=None if source.is_dir else _safe_size(new_path),
        mtime=_safe_mtime(new_path),
        parent=parent,
    )


def load_children(node: Node) -> None:
    """Read `node`'s immediate children (one level only), dotfiles skipped and
    directories sorted first. On an unreadable directory (`PermissionError`/
    other `OSError` -- e.g. macOS blocking `~/Documents` for some terminals
    under its privacy sandbox), leaves it empty and flags `load_error`, with
    `load_error_reason` set to the OS's own message (`exc.strerror`) so a
    caller can tell the user *why*, not just that it failed. Files are a
    no-op."""
    if not node.is_dir:
        return
    try:
        entries = [c for c in node.path.iterdir() if not c.name.startswith(".")]
    except OSError as exc:
        node.children = []
        node.load_error = True
        node.load_error_reason = exc.strerror or str(exc)
        return
    kids = [
        Node(
            name=child.name,
            path=child,
            is_dir=child.is_dir(),
            size_bytes=None if child.is_dir() else _safe_size(child),
            mtime=_safe_mtime(child),
            parent=node,
        )
        for child in entries
    ]
    kids.sort(key=_sort_key)
    node.children = kids
    node.load_error = False
    node.load_error_reason = None


def ensure_loaded(node: Node) -> None:
    """Load `node`'s children once; cheap no-op if already loaded or a file."""
    if node.is_dir and node.children is None:
        load_children(node)


def _folder_signature(path: Path) -> tuple[tuple[str, int, int], ...] | None:
    """A cheap, dependency-free stamp of `path`'s own immediate listing, used
    by `FileManager.enable_fs_watch` to notice an external change (Finder,
    another terminal, `rm`/`mv`, ...) with no OS-level watcher (inotify/
    FSEvents/ReadDirectoryChangesW) and no new runtime dependency -- just a
    `stat()` per entry, on the one folder the active tab is showing. Skips
    dotfile entries, matching `load_children`'s own filtering, so hidden-file
    churn the app never displays (Finder rewriting `.DS_Store`, `.git`
    changing during other work in the same folder) doesn't trigger a visible
    refresh; a visible<->hidden rename still changes the visible set either
    way. Each remaining entry's (name, mtime, size), sorted so creation order
    doesn't matter -- changes on an add, a remove, a rename, or a rewrite of
    an entry's own content/metadata. An entry that disappears mid-scan (a
    race with another process's own delete/rename) is just skipped rather
    than failing the whole signature. `None` means `path` itself can't be
    read right now (just deleted, or a permission revoked); callers treat
    that as "nothing new to report" for the purpose of noticing a change --
    `_report_load_error` is what surfaces that failure, the next time
    something actually reloads this folder."""
    try:
        listing = []
        for entry in os.scandir(path):
            if entry.name.startswith("."):
                continue
            try:
                stat = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            listing.append((entry.name, stat.st_mtime_ns, stat.st_size))
    except OSError:
        return None
    return tuple(sorted(listing))


class _FolderSnapshot:
    """The baseline `FileManager.enable_fs_watch` diffs the active folder
    against -- the filesystem-watch analogue of `ModuleWatcher` (quadraui's
    hot-reload baseline). Keeps one baseline *per path*, not just the most
    recently watched one, so a tab switch or a drill-down to a folder this
    session has never watched before doesn't itself read as "changed" --
    `changed()` takes that folder's first baseline silently and reports
    nothing new. A folder this session *has* watched before (switch away
    and back) keeps comparing against its own last-known listing, so a real
    external edit made while a different tab was active is still caught the
    moment this one becomes active again -- the only thing a navigation-time
    check needs to buy."""

    def __init__(self) -> None:
        self._signatures: dict[Path, tuple[tuple[str, int, int], ...] | None] = {}

    def snapshot(self, path: Path) -> None:
        """Record (or re-arm) `path`'s current listing as its baseline."""
        self._signatures[path] = _folder_signature(path)

    def changed(self, path: Path) -> bool:
        """`True` when `path`'s listing differs from its last-recorded
        baseline. A `path` with no baseline yet takes one now and reports no
        change -- arriving somewhere isn't itself an edit. Otherwise
        read-only: comparing against an existing baseline never updates it;
        `snapshot()` is the explicit re-arm, done after a change is actually
        acted on (see `FileManager.fs_watch_if_changed`)."""
        if path not in self._signatures:
            self.snapshot(path)
            return False
        return _folder_signature(path) != self._signatures[path]


def _is_under(path: Path, ancestor: Path) -> bool:
    return path == ancestor or ancestor in path.parents


def _reparent_paths(node: Node) -> None:
    """After `node.path` changes (a rename), fix every already-loaded
    descendant's cached `path` to sit under it. Children were computed by
    `iterdir()` under the old path and would otherwise keep pointing at a
    location that no longer exists once the rename lands on disk."""
    for child in node.children or ():
        child.path = node.path / child.name
        _reparent_paths(child)


def build_root(root_path: Path) -> Node:
    """A filesystem root (`/`, `C:\\`), loaded one level deep. Every other
    node hangs off one of these -- see `FileManager._node_for`."""
    root = Node(name=root_path.name or str(root_path), path=root_path, is_dir=root_path.is_dir())
    ensure_loaded(root)
    root.expanded = True
    return root
