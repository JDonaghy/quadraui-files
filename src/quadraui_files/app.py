"""Cross-backend file manager: an interactive two-pane browser built from one
set of `quadraui` descriptors that run unchanged on TUI, GTK, macOS, and
Windows -- only the final run call differs per platform.

Layout (the `render` callback returns a *layout tree*):

    split (vertical: chrome + body stacked over a status bar)
    ├─ first  : sidebar_panel
    │            ├─ toolbar : a key-legend affordance strip (reserved top slot)
    │            └─ content : split (resizable divider, draggable)
    │                          ├─ first  : a FOLDERS-ONLY tree (navigation)
    │                          └─ second : split (resizable divider, draggable)
    │                                      ├─ first  : the details area --
    │                                      │           tabs, one per opened
    │                                      │           folder, each tab a
    │                                      │           data_table of that
    │                                      │           folder's contents
    │                                      └─ second : a split (header over
    │                                                  content) -- a one-line
    │                                                  header naming/sizing
    │                                                  the last file selected
    │                                                  in a details table,
    │                                                  over a read-only
    │                                                  preview of it; `p`
    │                                                  hides the whole thing
    └─ second : a live status bar (cursored folder, item count, open tabs)

The tree loads lazily: only one directory level is read at a time, so you can
browse an arbitrarily deep filesystem without scanning it up front. Folders
expand and collapse; a folder's children are read the first time it is opened.

The UI is *live*: plain Python attributes hold what changes (the cursor node,
the split ratio, which folders are open as tabs, the active tab, a transient
status hint), the event handler mutates them, and `render()` rebuilds the whole
layout tree from them every frame. Neither callback calls back into `QuiApp`.

Interaction (keyboard drives, mouse works too):
  Up / Down    move the folder cursor
  Right        expand the cursored folder (load on demand); if already
               expanded, descend into its first subfolder
  Left         collapse the cursored folder; if already collapsed, jump to
               its parent
  Enter / o    open the cursored folder as a details tab (and expand it)
  r            reload the cursored folder from disk
  Delete       trash the selected file (or the cursored folder) -- after a
               Cancel/Delete confirm dialog -- and show a toast whose Undo
               button puts the trashed path back
  Menu         open a context menu (Open / Reveal in file manager / Move to
               Trash) for the selected file or the cursored folder
  /            open the bottom filter box; typing narrows every open
               details table live, Enter closes the box (filter stays
               applied), Esc closes it and clears the filter
  F2           open an inline rename box seeded with the selected file's
               (or cursored folder's) name; Enter commits a real rename on
               disk, Esc cancels
  p            toggle the preview pane (its header and content both) on
               or off; hiding gives its width back to the details table,
               and the divider ratio is remembered for next time it shows
  click a tree row         select it and show it in the details pane,
                            replacing the active tab's folder (expansion is
                            untouched -- only the chevron, or Left/Right,
                            expands/collapses)
  click a tree chevron     expand or collapse that row, leaving the
                            cursor/details pane untouched
  activate a details row   drill into that subfolder, or open a file with
                            the OS's default app for it
  click a details header   sort every open details table by that column
                            (marked with ▲/▼ on the active header); click
                            the same header again to reverse it
  click a tab / its ×      switch to / close that tab
  click the preview header's × close the preview pane (same as pressing `p`
                            while it's shown)
  q / Escape   quit the real run loops

A right-click would be the natural way to open the context menu, but the
installed quadraui's `Tree`/`DataTable` row-click events don't report which
mouse button triggered them, so a right click on a row can't be told apart
from a left one here -- `Menu` is the keyboard stand-in.

The overlay surfaces (`show_message_dialog` / `show_context_menu` /
`show_toast` / `show_tooltip`), the platform service `send_notification`, the
OS actions (`open_path` / `reveal_in_file_manager` / `move_to_trash` /
`restore_from_trash`), and the native-chrome calls (`set_title` /
`set_document_edited` / `set_represented_filename` / `set_cursor` -- C13, see
that section's own doc) are never called on `QuiApp` itself from `_handle`/
`_render`: `QuiApp` holds its one mutable borrow for the whole dispatch into
either callback and rejects a reentrant call. They go through the
deferred-action handle `QuiApp.actions()` returns instead -- obtained once in
`__init__`, before any run loop starts, and called straight from the handler,
which validates the arguments on the spot and queues the action. Every event
pump -- `QuiApp.step`, `run_tui`'s loop, and `run_native`'s GTK/AppKit/Win32
loops -- drains that queue right after the dispatch that filled it, so the
dialog, menu, toast, tooltip, notification or OS call lands on every backend
without any Python code needing to run between events.

    python quadraui-py/examples/file_manager.py [PATH]            # headless demo
    python quadraui-py/examples/file_manager.py [PATH] --tui      # real terminal
    python quadraui-py/examples/file_manager.py [PATH] --native   # OS window
    python quadraui-py/examples/file_manager.py [PATH] --dump     # descriptor dump
"""

from __future__ import annotations

import mimetypes
import os
import struct
import sys
import zlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from quadraui import InternalError, QuadrauiError, QuiApp

try:
    # Which native backend (if any) a `run_native()` call on this build would
    # actually open -- `"gtk"` / `"macos"` / `"win"` / `None` (headless-only
    # build, or no feature enabled). Decided by the *built* Cargo feature, not
    # the host OS a `sys.platform` check would read -- a `--features gtk`
    # build runs fine on macOS, for instance. Not re-exported by `quadraui`'s
    # own `__init__.py`, only reachable through its compiled extension
    # submodule; `ImportError` means an older `quadraui-py` build that
    # predates this attribute, so this app treats that the same as "no native
    # backend built in" rather than failing to import at all.
    from quadraui._quadraui import _NATIVE_BACKEND
except ImportError:  # pragma: no cover - defensive, see doc above
    _NATIVE_BACKEND = None

# Can a trashed path be put back? `restore_from_trash` is implemented for the
# freedesktop.org trash spec (Linux/BSD) and the Windows recycle bin, and
# raises on macOS, which exposes no programmatic trash listing to delegate to.
# This is a *host* capability, not a backend one -- the same value holds for
# TUI, GTK, AppKit and Win32 on a given machine -- so gating the undo
# affordance on it keeps one descriptor set running on every backend.
UNDO_SUPPORTED = sys.platform != "darwin"


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


def _reparent_paths(node: Node) -> None:
    """After `node.path` changes (a rename), fix every already-loaded
    descendant's cached `path` to sit under it. Children were computed by
    `iterdir()` under the old path and would otherwise keep pointing at a
    location that no longer exists once the rename lands on disk."""
    for child in node.children or ():
        child.path = node.path / child.name
        _reparent_paths(child)


def build_root(root_path: Path) -> Node:
    """The model root: loaded one level deep and expanded, so the tree opens on
    the root's immediate subfolders."""
    root = Node(name=root_path.name or str(root_path), path=root_path, is_dir=root_path.is_dir())
    ensure_loaded(root)
    root.expanded = True
    return root


# --- model -> folders-only tree descriptor ----------------------------------
#
# The tree pane shows *only directories* -- files live in the details tabs. We
# walk the model depth-first in display order over *expanded* folders only,
# emitting a row per directory and tagging it with its `path`: the route from
# the root as a list of child indices among *folders* (a `TreePath`, read on
# the Rust side as `Vec<u16>`). A folder's path stays a valid prefix of its
# subfolders' paths, so a click on a row resolves back to its node. `indent` is
# folder depth.

TREE_STYLE = {
    "indent": 2,  # columns of indent per depth level
    "show_chevrons": True,  # draw the twisty on directories
    "chevron_expanded": "▾",  # down triangle
    "chevron_collapsed": "▸",  # right triangle
    "row_height": 22,  # px; TUI ignores it, native backends honour it
}

# `icon` is an `Icon`: a Nerd Font `glyph` plus an ASCII/basic-Unicode
# `fallback` the backend uses when the glyph can't render (so the TUI stays
# legible without a Nerd Font). `color: None` lets the row's theme foreground
# through.
FOLDER_ICON = {"glyph": "\U0001f4c1", "fallback": "/", "color": None}  # folder
FILE_ICON = {"glyph": "\U0001f4c4", "fallback": " ", "color": None}  # page


def _styled_text(text: str) -> dict:
    """One `StyledText` with a single uncolored span -- the shape tree `text`,
    data-table cells, and text_display lines all use; the theme picks colors."""
    return {"spans": [{"text": text, "fg": None, "bg": None}]}


def folder_rows(root: Node) -> tuple[list[dict], list[Node]]:
    """Walk the expanded model into index-aligned `(rows, nodes)`, directories
    only. Recomputed each frame, since expanding/collapsing changes which rows
    are visible."""
    rows: list[dict] = []
    nodes: list[Node] = []

    def walk(node: Node, path: list[int], indent: int) -> None:
        rows.append(
            {
                "path": path,
                "indent": indent,
                "icon": FOLDER_ICON,
                "text": _styled_text(node.name),
                "badge": None,
                "is_expanded": node.expanded,
            }
        )
        nodes.append(node)
        if node.expanded:
            for i, child in enumerate(node.subdirs()):
                walk(child, path + [i], indent + 1)

    walk(root, path=[], indent=0)
    return rows, nodes


def tree_leaf(rows: list[dict], *, selected_path: list[int], scroll_offset: int) -> dict:
    """A layout-tree *leaf* wrapping the folders-only tree descriptor. A leaf is
    `{"id", "<kind>": <descriptor>}`; the id is unique across the whole tree.
    `has_focus` keeps arrow keys / Enter routed here on the real backends.
    `scroll_offset` is the index of the first painted row -- the tree is purely
    declarative (it renders `rows[scroll_offset..]`), so the app owns it and
    advances it to keep the cursor in view; the backend derives the scrollbar
    thumb from it."""
    return {
        "id": "fm:tree",
        "tree": {
            "id": "fm:tree",
            "rows": rows,
            "selection_mode": "Single",
            "selected_path": selected_path,
            "scroll_offset": scroll_offset,
            "has_focus": True,
            "style": TREE_STYLE,
        },
    }


# --- folder -> details data_table --------------------------------------------
#
# Each details tab lists the immediate children (files + subfolders) of one
# opened folder. `width` is `{"Flex": w}` -- unitless proportional weights that
# lay out the same on every backend, unlike `{"Fixed": n}` (surface-native
# units: cells on TUI, *pixels* on native). Activating a row emits a
# `DataTable/RowActivated` event whose `idx` indexes straight into the folder's
# `children`, so a click on a subfolder row can drill into it.

_SIZE_UNITS = ("B", "KB", "MB", "GB", "TB")


def _human_size(n: int | None) -> str:
    """Human-readable byte count; "" for directories (size_bytes is None)."""
    if n is None:
        return ""
    size = float(n)
    i = 0
    while size >= 1024 and i < len(_SIZE_UNITS) - 1:
        size /= 1024
        i += 1
    return f"{int(size)} {_SIZE_UNITS[i]}" if i == 0 else f"{size:.1f} {_SIZE_UNITS[i]}"


def _human_mtime(ts: float | None) -> str:
    """Human-readable last-modified timestamp; "" if unreadable or
    out of `datetime`'s representable range -- a pathological `st_mtime`
    (`OverflowError`/`OSError`/`ValueError`) must not break the whole
    details table it renders inside, same as `_safe_size`/`_safe_mtime`
    are defensive about a bad `stat()`."""
    if ts is None:
        return ""
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except (OverflowError, OSError, ValueError):
        return ""


def _filter_children(children: list[Node], query: str) -> list[Node]:
    """`children` narrowed to those whose name contains `query`
    (case-insensitive); an empty/blank query matches everything."""
    q = query.strip().lower()
    if not q:
        return list(children)
    return [c for c in children if q in c.name.lower()]


def _size_sort_key(node: Node) -> tuple[bool, int]:
    """Size ascending, with a missing value (a directory's size) first."""
    return (node.size_bytes is None, node.size_bytes or 0)


def _mtime_sort_key(node: Node) -> tuple[bool, float]:
    """Modified-time ascending, with a missing value first."""
    return (node.mtime is None, node.mtime or 0.0)


_COLUMN_SORT_KEYS = {0: _sort_key, 1: _size_sort_key, 2: _mtime_sort_key}


def _sort_children(children: list[Node], col: int, reverse: bool) -> list[Node]:
    """`children` ordered by details-table column `col` (0 Name, 1 Size, 2
    Modified). Name sorts directories first then case-insensitive name --
    the tree's own order, so the unsorted (`col == 0`, not `reverse`) case
    matches a freshly loaded folder exactly. Size/Modified sort purely by
    value, with a missing value (a directory's size) sorting first."""
    key = _COLUMN_SORT_KEYS.get(col, _sort_key)
    ordered = sorted(children, key=key)
    return list(reversed(ordered)) if reverse else ordered


def details_table(
    folder: Node,
    index: int,
    *,
    children: list[Node] | None = None,
    sort_col: int = 0,
    sort_reverse: bool = False,
) -> dict:
    """The data_table descriptor for one opened folder's contents, as the
    content subtree of tab `index`. `children` is the rows' display order
    (filtered/sorted by the caller); defaults to `folder.children` as-is.
    Row order matches `children`, so a `RowActivated{idx}` maps straight
    back to the same list the caller used to build it. `sort_col`/
    `sort_reverse` only drive a `▲`/`▼` marker on the active column's
    title -- the actual ordering is `children`'s, already sorted by the
    caller."""
    table_id = f"fm:grid:{index}"
    columns = [
        {"title": "Name", "width": {"Flex": 2.0}, "align": "Left"},
        {"title": "Size", "width": {"Flex": 1.0}, "align": "Right"},
        {"title": "Modified", "width": {"Flex": 1.5}, "align": "Left"},
    ]
    if 0 <= sort_col < len(columns):
        arrow = "▼" if sort_reverse else "▲"
        columns[sort_col] = {**columns[sort_col], "title": f"{columns[sort_col]['title']} {arrow}"}

    all_children = folder.children or []
    shown = all_children if children is None else children
    if not shown:
        if folder.load_error:
            reason = folder.load_error_reason
            note = f"(can't read: {reason})" if reason else "(unreadable)"
        elif all_children:
            note = "(no matches)"
        else:
            note = "(empty folder)"
        rows = [{"cells": [_styled_text(note), _styled_text(""), _styled_text("")]}]
    else:
        rows = []
        for child in shown:
            # A trailing "/" hints the row is navigable (activate to drill in).
            name = f"{child.name}/" if child.is_dir else child.name
            size = "" if child.is_dir else _human_size(child.size_bytes)
            modified = _human_mtime(child.mtime)
            rows.append(
                {"cells": [_styled_text(name), _styled_text(size), _styled_text(modified)]}
            )

    return {"id": table_id, "columns": columns, "rows": rows}


# --- selected file -> read-only preview --------------------------------------
#
# A third region, to the right of the details tabs: a read-only preview of
# whichever file was last selected (activated) in a details table. Built with
# `text_display`, the same read-only line-list primitive the empty-details
# placeholder already uses -- the installed quadraui's `editor` primitive
# wants a caller-measured pixel `rect` and a long list of editor-only fields
# (gutter, diagnostics, git-status markers) rather than slotting into a split
# leaf sized by the layout tree the way every other primitive here does, so
# it does not fit this app's "backend lays out, app only describes" model yet.
# `text_display` is the documented fallback for exactly that gap.
#
# `text_display` defaults to auto-scrolling to the tail of `lines` (built for
# a log/console tail, not a document viewer), but its descriptor also carries
# `scroll_offset` and `auto_scroll` fields -- `auto_scroll: False` plus
# `scroll_offset: 0` pins it to row 0 instead, which is what a preview wants.
# `preview_leaf` sets both explicitly. The `capacity` cap on top of that is
# no longer what keeps the head on screen; it just bounds how much of an
# arbitrarily large file ever gets read and painted.

PREVIEW_MAX_BYTES = 64 * 1024  # read at most this many bytes before truncating


def _looks_binary(sample: bytes) -> bool:
    """A NUL byte or invalid UTF-8 anywhere in `sample` marks it binary --
    the same quick heuristic common file-preview tools use rather than a
    full content-type sniff."""
    if b"\x00" in sample:
        return True
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return False


def _trim_incomplete_utf8_tail(data: bytes) -> bytes:
    """Drop a trailing partial UTF-8 multi-byte sequence, if one is there.
    A hard byte cutoff (like `PREVIEW_MAX_BYTES`) can slice through the
    middle of a multi-byte character; left alone, that dangling fragment
    makes an otherwise-valid text sample decode as invalid (or, worse, read
    as binary). Looks back at most 4 bytes -- the longest a UTF-8 sequence
    gets -- for a lead byte whose sequence runs past the end of `data`."""
    limit = min(4, len(data))
    for i in range(1, limit + 1):
        byte = data[-i]
        if byte & 0xC0 == 0x80:
            continue  # a continuation byte; keep walking back
        if byte & 0xE0 == 0xC0:
            seq_len = 2
        elif byte & 0xF0 == 0xE0:
            seq_len = 3
        elif byte & 0xF8 == 0xF0:
            seq_len = 4
        else:
            return data  # an ASCII byte (or an invalid lead byte): nothing to trim
        return data[:-i] if seq_len > i else data
    return data


def preview_lines(node: Node | None, *, capacity: int) -> list[dict]:
    """Styled-text lines for the preview pane: no selection, a directory, or
    a non-regular file (pipe/socket/device -- opening one of those can block
    or hang) all get a short hint; a binary/undecodable file gets a one-line
    "N bytes · <type>" placeholder; a text file gets its content, truncated
    (by bytes read, and again to `capacity` lines) so an arbitrarily large
    file never has to be painted in full. `capacity` is always at least 1,
    so there is room for a lone truncation marker even against a one-row
    pane."""
    if node is None:
        return [_styled_text("No file selected.")]
    if node.is_dir:
        return [_styled_text("Select a file to preview it.")]
    if not node.path.is_file():
        return [_styled_text("Not a regular file.")]
    capacity = max(1, capacity)
    try:
        with node.path.open("rb") as f:
            data = f.read(PREVIEW_MAX_BYTES + 1)
    except FileNotFoundError:
        return [_styled_text(f"{node.name} is no longer there")]
    except OSError as exc:
        reason = exc.strerror or str(exc)
        return [_styled_text(f"{node.name} can't be read ({reason})")]
    byte_truncated = len(data) > PREVIEW_MAX_BYTES
    if byte_truncated:
        data = _trim_incomplete_utf8_tail(data[:PREVIEW_MAX_BYTES])
    if _looks_binary(data):
        kind, _encoding = mimetypes.guess_type(node.name)
        size = _human_size(node.size_bytes if node.size_bytes is not None else len(data))
        return [_styled_text(f"{size} · {kind or 'binary'}")]
    lines = data.decode("utf-8", errors="replace").splitlines() or [""]
    line_truncated = len(lines) > capacity
    needs_marker = byte_truncated or line_truncated
    # Only steal a content row for the truncation marker when there isn't
    # already a free one below the last line -- otherwise `capacity` rows
    # of a file that just barely overflowed its byte cap would lose a line
    # it didn't need to.
    shown = capacity - 1 if (needs_marker and len(lines) >= capacity) else min(capacity, len(lines))
    rows = [_styled_text(line) for line in lines[:shown]]
    if needs_marker:
        rows.append(_styled_text("… (truncated)"))
    return rows


def preview_leaf(node: Node | None, *, capacity: int) -> dict:
    """The layout-tree leaf for the preview pane: a read-only `text_display`
    of `preview_lines(node, capacity=capacity)`, pinned to the head of the
    file (`auto_scroll: False`, `scroll_offset: 0`) rather than its default
    tail-follow behavior."""
    return {
        "id": "fm:preview",
        "text_display": {
            "id": "fm:preview",
            "lines": preview_lines(node, capacity=capacity),
            "auto_scroll": False,
            "scroll_offset": 0,
        },
    }


# --- preview header: name/size/type + a close control ------------------------
#
# A one-line header above the preview's own content, naming what it's
# showing: the file name (ellipsised -- there's no char-width/pixel-width
# metric this app can read back from either backend, similar to why
# `_show_file_tooltip` can't learn a `DataTable`'s own scroll offset, so
# this is a conservative character cap rather than a pixel-exact one) and
# its size, paired the same way `_tooltip_payload` already pairs them for a
# file, both in the header's *left* segments -- `StatusBar`'s own layout
# never drops a left segment, unlike the right half's priority-drop (see
# `fit_right_start`'s doc at the pin), so the size survives at realistic
# window widths instead of being the first thing dropped. The modified
# time and the close control are the right segments, ordered least-
# important first (`fit_right_start`'s own convention) so a narrow column
# drops the timestamp before ever touching the close control. Built with
# `status_bar` -- the same left/right-segment primitive the bottom status
# bar already uses -- rather than `text_display`, because a
# `StatusBarSegment` can carry an `action_id`: the close control is just a
# segment with one set, and clicking it raises a `StatusBar`/`SegmentClicked`
# event carrying that id back, same mechanism a closable tab's × already
# relies on for its own `TabClosed`. No bespoke hit-testing or widget needed.

PREVIEW_HEADER_CLOSE_ACTION = "fm:preview:close"
_PREVIEW_NAME_MAX_CHARS = 40  # upper bound; the header leaf tightens this per the column's own width
_PREVIEW_HEADER_RESERVED_CELLS = 2 + 3  # MIN_GAP_CELLS + " × " -- see the header leaf's own doc


def _ellipsize(name: str, max_chars: int) -> str:
    """`name` capped to `max_chars` characters, with a trailing "…" marker
    when it had to be cut."""
    if len(name) <= max_chars:
        return name
    return name[: max_chars - 1] + "…"


def _preview_header_parts(node: Node | None) -> tuple[str, str, str]:
    """`(name, size, modified)` text for the preview header. `name` is the
    raw, un-ellipsized file name (or "No file selected") -- how much of it
    actually fits depends on the column's current cell width, which this
    free function has no way to read, so sizing it is the header leaf's
    job. `size`/`modified` are `""` where there's nothing to say about
    either (no selection, or a folder -- `_tooltip_payload` already
    reports a folder's own size/mtime as meaningless, see its own doc)."""
    if node is None:
        return "No file selected", "", ""
    if node.is_dir:
        return node.name, "", ""
    return node.name, _human_size(node.size_bytes), _human_mtime(node.mtime)


# --- chrome: toolbar band + status bar ---------------------------------------
#
# The toolbar is the body's chrome, carried by a `sidebar_panel` wrapper whose
# reserved top slot paints it above the content on every backend. The bindings
# don't route clicks on toolbar buttons to events yet, so it is a *key legend*
# -- an affordance, not a control; the keyboard and the tree/table clicks drive
# everything. The status bar is a live bottom band, rebuilt from state each
# frame.

TOOLBAR = {
    "id": "fm:toolbar",
    "buttons": [
        {"Action": {"id": "fm:k:move", "label": "↑↓ Move"}},
        {"Action": {"id": "fm:k:expand", "label": "→ Expand"}},
        {"Action": {"id": "fm:k:collapse", "label": "← Collapse"}},
        {"Action": {"id": "fm:k:open", "label": "↵ Open"}},
        {"Action": {"id": "fm:k:preview", "label": "p Preview"}},
        {"Action": {"id": "fm:k:refresh", "label": "r Refresh"}},
        {"Action": {"id": "fm:k:delete", "label": "Del Trash"}},
        {"Action": {"id": "fm:k:menu", "label": "Menu ≡"}},
        {"Action": {"id": "fm:k:search", "label": "/ or ^F Search"}},
        {"Action": {"id": "fm:k:rename", "label": "F2 Rename"}},
        {"Action": {"id": "fm:k:quit", "label": "q Quit"}},
    ],
}

# `StatusBarSegment` requires explicit fg + bg (unlike the theme-driven
# `StyledText` spans elsewhere, `set_theme` never touches it) -- so the status
# bar needs its own light/dark pair, picked by `_apply_system_theme` from the
# same `system_theme()` read that chooses between `_VSCODE_DARK_THEME` and
# `_VSCODE_LIGHT_THEME`, stored on the instance (`self._status_fg`/`_bg`/
# `_accent`) rather than as one fixed module-level triple -- otherwise the
# band stayed dark navy regardless of the OS's light/dark preference. The
# accent foreground highlights the cursored folder's name.
_STATUS_DARK_FG = {"r": 220, "g": 220, "b": 230, "a": 255}
_STATUS_DARK_BG = {"r": 30, "g": 32, "b": 48, "a": 255}
_STATUS_DARK_ACCENT = {"r": 245, "g": 224, "b": 138, "a": 255}

_STATUS_LIGHT_FG = {"r": 40, "g": 40, "b": 40, "a": 255}
_STATUS_LIGHT_BG = {"r": 225, "g": 225, "b": 225, "a": 255}
_STATUS_LIGHT_ACCENT = {"r": 0, "g": 95, "b": 184, "a": 255}


# --- chrome: OS theme + global keybindings -----------------------------------
#
# `set_theme`/`register_accelerator` are, like `line_height`/`chrome_line_height`
# in `FileManager.__init__`, only reachable from top-level code: both need the
# same exclusive borrow on `QuiApp` that `_handle`/`_render` already hold for
# the whole dispatch that invokes them, so calling either from inside one
# raises the same "already borrowed" error the module doc's reentrancy note
# describes for the overlay/OS calls -- and neither is on the `QuiApp.actions()`
# handle that works around that for those. Called once, from `__init__`,
# before `run_tui`/`run_native` ever takes over: both "take effect immediately
# on this app's own live backend" and are separately replayed onto whichever
# real backend a later `run_tui`/`run_native` call constructs, so one call here
# covers every backend.

# A VS Code-like palette, as a `set_theme` override merged onto whichever
# backend's own default theme -- only the handful of `Theme` fields this app's
# own chrome (tree, details grid, tabs) actually paints need a value here;
# every other field keeps the installed theme's own default. The status bar
# is NOT painted from this palette -- `StatusBarSegment` takes its own
# explicit fg/bg, so it is picked separately in `_apply_system_theme` from
# the `_STATUS_DARK_*`/`_STATUS_LIGHT_*` pair, right below.
_VSCODE_DARK_THEME = {
    "background": "#1e1e1e",
    "foreground": "#d4d4d4",
    "surface_bg": "#252526",
    "surface_fg": "#cccccc",
    "accent_bg": "#007acc",
    "accent_fg": "#ffffff",
    "selected_bg": "#264f78",
    "selection_bg": "#264f78",
    "hover_bg": "#2a2d2e",
    "hover_fg": "#d4d4d4",
    "header_bg": "#2d2d2d",
    "header_fg": "#cccccc",
    "border_fg": "#3c3c3c",
    "separator": "#3c3c3c",
    "muted_fg": "#9d9d9d",
    "tab_bar_bg": "#252526",
    "tab_active_bg": "#1e1e1e",
    "tab_active_fg": "#ffffff",
    "tab_inactive_fg": "#969696",
    "input_bg": "#3c3c3c",
    "scrollbar_thumb": "#424242",
    "scrollbar_track": "#1e1e1e",
}

_VSCODE_LIGHT_THEME = {
    "background": "#ffffff",
    "foreground": "#1e1e1e",
    "surface_bg": "#f3f3f3",
    "surface_fg": "#424242",
    "accent_bg": "#005fb8",
    "accent_fg": "#ffffff",
    "selected_bg": "#add6ff",
    "selection_bg": "#add6ff",
    "hover_bg": "#e8e8e8",
    "hover_fg": "#1e1e1e",
    "header_bg": "#f3f3f3",
    "header_fg": "#424242",
    "border_fg": "#c8c8c8",
    "separator": "#c8c8c8",
    "muted_fg": "#6e6e6e",
    "tab_bar_bg": "#f3f3f3",
    "tab_active_bg": "#ffffff",
    "tab_active_fg": "#1e1e1e",
    "tab_inactive_fg": "#6e6e6e",
    "input_bg": "#ffffff",
    "scrollbar_thumb": "#c2c2c2",
    "scrollbar_track": "#f3f3f3",
}

# Real OS-level accelerators (C15) for the bindings that are safe to claim
# globally. `register_accelerator`'s `scope` only ever matches as `Global`
# today -- `Widget`/`Mode` are accepted but silently never fire, see that
# method's own doc -- so there is no way to suppress a binding while the
# filter/rename text box has focus. Only non-printable/chorded bindings are
# registered here for exactly that reason: a single printable letter (`r`
# reload, `q` quit, a bare `Enter` to open) stays a plain, Python-dispatched
# key instead of a registered accelerator, since claiming one of those
# globally would steal it from the edit box unconditionally, breaking typing
# that very letter into a rename/filter query. `_handle` still ignores every
# accelerator below while `edit_mode` is set, same as it already ignores the
# equivalent plain keys there.
ACCELERATORS = [
    {"id": "fm:accel:rename", "binding": {"Literal": "F2"}, "scope": "Global", "label": "Rename"},
    {"id": "fm:accel:delete", "binding": {"Literal": "Delete"}, "scope": "Global", "label": "Move to Trash"},
    {"id": "fm:accel:search", "binding": {"Literal": "ctrl+f"}, "scope": "Global", "label": "Search"},
    {"id": "fm:accel:search_cmd", "binding": {"Literal": "cmd+f"}, "scope": "Global", "label": "Search"},
]


# --- chrome: hover tooltips ---------------------------------------------------
#
# A tooltip describing the file/folder the user's attention is currently on:
# its full path, plus (for a file) a human size and modified time.
# `quadraui`'s event model has no mouse-hover primitive this app can reach --
# `MouseMoved` is delivered with no hit-testing against the painted layout
# (unlike `MouseDown`/`MouseUp`/`DoubleClick`/`Scroll`, which all resolve to a
# `"hit"` detail or a semantic `Tree`/`DataTable` event), and the TUI
# backend -- the one the black-box suite drives -- never emits
# `MouseEntered`/`MouseLeft` either (crossterm surfaces no such signal). So
# "hover" here is the row the keyboard cursor is on (the tree) or the file
# last activated in a details table (`self.selected_file`) -- the same two
# notions of "the thing the user means right now" `_delete_candidate` already
# keys its own target off. Shown via `self.actions.show_tooltip` (not
# `QuiApp.show_tooltip`, which raises "already borrowed" inside a handler --
# see the module doc), from `_move`/`_on_row_click` (tree) and
# `_set_selected_file` (details).
#
# `anchor` is a `(x, y, width, height)` rect in this app's own cell grid --
# the same units `line_height`/`chrome_line_height`/`viewport` already
# measure for `_tree_capacity`. It is a best-effort placement, not a
# pixel-exact hit-test (this app has no way to ask the backend for one --
# see above): exact for a tree row (this app owns the tree's scroll
# offset), approximate for a details row (a `DataTable`'s own scroll offset
# is backend-owned and never reported back). `Tooltip::layout` clamps/flips
# the result to stay inside the viewport either way, so an approximate
# anchor never overflows or crashes -- it just occasionally sits a row or
# two off the exact one.


def _tooltip_payload(widget_id: str, node: Node) -> dict:
    """A `Tooltip` descriptor for `node`. A folder's `size_bytes`/`mtime`
    describe the folder itself, not a meaningful "contents" summary, so
    only a file gets the second line."""
    lines = [str(node.path)]
    if not node.is_dir:
        lines.append(f"{_human_size(node.size_bytes)} · {_human_mtime(node.mtime)}")
    return {"id": widget_id, "text": "\n".join(lines)}


# --- native chrome: window title / dirty-dot / tray / cursor ----------------
#
# C13: the window title tracks the current path, a dirty-dot (and, on macOS,
# a represented-filename proxy icon) marks a pending rename, a tray icon +
# menu appear where the backend has one, and the pointer cursor swaps to a
# resize glyph during a divider drag, restored once the drag ends.
#
# Each of the four calls this needs has a different safety story on the
# backend this app's own `self.app` always talks to (the headless
# `TuiBackend` -- see the module doc's reentrancy note for why `run_native`
# moving the app's descriptors/handlers onto a real GTK/AppKit/Win32 window
# doesn't change which backend `self.app` itself queries, but *does* change
# which backend a deferred action queued through `self.actions` is drained
# against -- that queue is replayed by whichever loop, `run_tui` or
# `run_native`, is actually pumping events when the handler fills it):
#
#   * `set_title` -- always safe. Every backend implements `WindowControl::
#     set_title` (the TUI one via OSC 0/2), so `_sync_window_title` calls it
#     unconditionally on every navigation.
#   * `set_cursor` -- always safe. `Backend::set_cursor` returns whether the
#     glyph was actually applied rather than raising (`False`, never an
#     error, on a backend with no native pointer concept), so a divider drag
#     calls it unconditionally too, and the drag-ends-here reset (any event
#     other than another divider drag, while `self._dragging` is set --
#     typically `MouseUp`) calls it back to `"default"` the same way.
#   * `set_document_edited` / `set_represented_filename` -- only `MacBackend`
#     overrides either; every other backend (TUI included, even running on
#     a Mac) inherits `WindowControl`'s default `BackendError::Unsupported`,
#     surfaced as `InternalError` -- and that error, raised while draining a
#     handler's queued deferred action, would tear down the whole
#     `run_tui`/`run_native` loop, not just no-op the one call. There is no
#     `backend_caps()` name that distinguishes this (`"window_control"` is
#     `True` on every backend, TUI included, since `set_title` does work
#     there). So these two are gated on `self.native_window_chrome`, an
#     opt-in flag this app never sets itself -- only `cli.py`/this module's
#     own `__main__` block sets it, and only right before a `run_native()`
#     call where `_NATIVE_BACKEND == "macos"` (the *built* feature, not the
#     host OS: a `--features gtk` build run on macOS must not set this).
#   * `set_tray_icon` / `set_tray_tooltip` / `set_tray_menu` -- `Backend::
#     tray` returns `None` permanently on `TuiBackend` (a terminal has no
#     notification-area concept at all -- see `tests/test_window_tray.py`'s
#     own caps tests, kept exactly for that reason), but `self.app.
#     backend_caps()` always reads *that* dormant headless backend, even
#     once `run_native` has moved this app's descriptors onto a real window
#     -- `self.app` itself never queries any other backend (same reentrancy
#     note as above), so `backend_caps()["tray"]` can never usefully gate
#     this. Gated on `self.native_tray` instead, an opt-in flag exactly like
#     `native_window_chrome`'s, set `True` where `_NATIVE_BACKEND` names any
#     of the three native backends (all of which declare `tray: True`).
#     Queued through `self.actions` from `_prime_native_chrome`, called once
#     from the first `_handle` dispatch of a run loop that set the flag --
#     not from `__init__`, which only ever owns the dormant headless
#     backend and so could never make the tray appear regardless of what
#     it called.


def _window_title(path: Path) -> str:
    """`~/Documents — quadraui-files`-style window title for `path`: `~`
    relative to the user's home directory when `path` is under it (the
    bare home directory itself renders as `~`, not `~/`), the full path
    otherwise."""
    home = Path.home()
    if path == home:
        label = "~"
    else:
        try:
            label = f"~/{path.relative_to(home)}"
        except ValueError:
            label = str(path)
    return f"{label} — quadraui-files"


def _tray_icon_png() -> bytes:
    """A minimal valid 1x1 opaque-white PNG -- just enough bytes for
    `set_tray_icon`'s `ImageSource` decoder to accept, built in code rather
    than checked in as a binary asset. The real glyph a packaged app would
    want is an OS-level concern (an `.ico`/`.icns`/themed SVG this project
    does not ship) outside this demo's scope."""
    sig = b"\x89PNG\r\n\x1a\n"

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)  # 1x1, 8-bit RGBA
    idat = zlib.compress(b"\x00\xff\xff\xff\xff", 9)  # filter byte + one opaque white pixel
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


TRAY_MENU_OPEN_HOME_ID = "fm:tray:open_home"
TRAY_MENU_QUIT_ID = "fm:tray:quit"


def _tray_menu_items() -> list[dict]:
    """The tray icon's click menu: `Open home` (via `open_path`, the OS's
    own file manager/app for it, same as this app's own context-menu
    `Open`) and `Quit`."""
    return [
        {"id": TRAY_MENU_OPEN_HOME_ID, "label": _styled_text("Open home")},
        {"id": TRAY_MENU_QUIT_ID, "label": _styled_text("Quit")},
    ]


# --- the live QuiApp ---------------------------------------------------------
#
# event -> handler mutates plain Python attributes -> the runner repaints ->
# `render()` reads them and returns the whole frame's layout tree.

UP_KEY = {"Named": "Up"}
DOWN_KEY = {"Named": "Down"}
LEFT_KEY = {"Named": "Left"}
RIGHT_KEY = {"Named": "Right"}
ENTER_KEY = {"Named": "Enter"}
DELETE_KEY = {"Named": "Delete"}
MENU_KEY = {"Named": "Menu"}  # the dedicated "open context menu" key


def _key_name(key) -> str | None:
    """Canonical name of a raw key. A plain `KeyPressed` carries a tagged dict
    (`{"Named": "Down"}` / `{"Named": {"F": 2}}` / `{"Char": "o"}`); a
    focus-scoped leaf event carries the already-stringified name (`"Down"` /
    `"o"`). Both collapse to the name -- a function key becomes `"F2"`."""
    if isinstance(key, str):
        return key
    if isinstance(key, dict):
        named = key.get("Named")
        if isinstance(named, dict) and "F" in named:
            return f"F{named['F']}"
        if isinstance(named, str):
            return named
        return key.get("Char")
    return None


def _event_key(event: dict) -> str | None:
    """The canonical key name from a key event in any shape the backends
    deliver: a plain `KeyPressed`, or a focus-scoped `{"Tree"/"List"/"TabBar":
    [id, {"KeyPressed": ...}]}` (the focus manager rewrites a focused leaf's
    keys into its own variant, with the key already stringified). Returns None
    for a non-key event."""
    pressed = event.get("KeyPressed")
    if isinstance(pressed, dict):
        return _key_name(pressed.get("key"))
    for wrap in ("Tree", "List", "TabBar"):
        payload = event.get(wrap)
        if isinstance(payload, (list, tuple)) and len(payload) == 2 and isinstance(payload[1], dict):
            inner = payload[1].get("KeyPressed")
            if isinstance(inner, dict):
                return _key_name(inner.get("key"))
            return None
    return None


class FileManager:
    """Holds the lazily-scanned model and the live UI state the `render` and
    handler callbacks share. Build one, then call `run_*` for a real backend or
    drive it headlessly with `step`, the push-and-dispatch pair the run loops
    perform per event."""

    def __init__(self, root_path: Path, width: int = 100, height: int = 30):
        self.root = build_root(root_path)
        self.height = height
        self.cursor: Node = self.root   # the selected folder node
        self.scroll = 0                 # index of the first painted tree row
        self.ratio = 0.3                # tree pane width fraction
        self.preview_ratio = 0.65       # details-vs-preview width fraction, within the body's second pane
        self.preview_visible = True     # `p`/header-× toggle; preview_ratio is kept either way
        self.open: list[Node] = []      # folder nodes shown as tabs, in order
        self.active_tab = 0             # index into self.open
        self.message = ""               # transient status hint
        self.selected_file: Node | None = None  # last file activated in a details tab
        # `build_root` already attempted the root's own load; surface it
        # right away rather than leaving the tree looking like an ordinary
        # empty folder with no explanation -- e.g. macOS blocking a
        # sandboxed terminal's access to `~/Documents`.
        self._report_load_error(self.root)

        # Filter/sort/rename state for the active details table.
        self.filter_text = ""           # live search query; "" narrows nothing
        self.sort_col = 0               # details column last clicked (0 Name/1 Size/2 Modified)
        self.sort_reverse = False       # reversed by a second click on the same column
        self.edit_mode: str | None = None  # None | "filter" | "rename": which box the bottom panel shows
        self.edit_text = ""             # live buffer for whichever box is open
        self.rename_target: Node | None = None  # node a "rename" edit_mode would commit onto

        # Which node the currently open confirm dialog / context menu is for,
        # so the `MessageDialogResolved` / `ContextMenuItemActivated` event that
        # closes it knows what to act on.
        self._delete_target: Node | None = None
        self._menu_target: Node | None = None
        # The one trashed node an `Undo` click may put back, consumed on use:
        # a second restore of the same path has nothing left to find and fails
        # inside the event pump, where this app cannot catch it.
        self._undo_target: Node | None = None
        self._toast_seq = 0  # makes each toast's id unique
        # Tray's `Quit` item (C13) can't raise `_Quit` itself -- that
        # exception only means anything to `_wrap_quit`'s own wrapper, two
        # call frames up from `_on_menu_item`. Set here, checked there,
        # right after every `inner(event)` dispatch.
        self._quit_requested = False
        # Opt-in: only `MacBackend` implements `WindowControl::
        # set_document_edited`/`set_represented_filename` (see this
        # section's own "native chrome" doc, above `_window_title`) --
        # every other backend, TUI included even on a Mac, raises
        # `InternalError` for either, which would tear down the whole
        # `run_tui`/`run_native` loop. `FileManager` never sets this itself;
        # `cli.py`/this module's own `__main__` sets it to `True` only right
        # before a `run_native()` call where `_NATIVE_BACKEND == "macos"`.
        self.native_window_chrome = False
        # Opt-in, same story as `native_window_chrome` just above but for
        # the tray: `True` only where `_NATIVE_BACKEND` names a backend that
        # actually has one (`"gtk"` / `"macos"` / `"win"`, all of which
        # declare `tray: True`). `FileManager` never sets this itself either.
        self.native_tray = False
        # Opt-in: whether there is a real terminal or window to title. The
        # TUI backend's `set_title` writes an OSC 0/2 escape straight to
        # stdout, so a headless run (Python driving `step`, the test suite,
        # piped output) would get raw escapes mixed into its output.
        # `cli.py`/this module's own `__main__` set it right before
        # `run_tui()`/`run_native()`; `FileManager` never sets it itself.
        self.live_title = False
        # Latches the one-time native-chrome setup `_prime_native_chrome`
        # does on the first `_handle` dispatch of whichever run loop set
        # `native_window_chrome`/`native_tray` above -- see that method's
        # own doc.
        self._native_chrome_primed = False
        # Set while a divider drag (C13) is live, between the
        # `SplitDividerDragged` that sets the resize pointer cursor and
        # whatever event ends the drag -- see `_dispatch`'s own doc.
        self._dragging = False
        # The dark/light flag a `SystemThemeChanged` event most recently
        # recorded, `None` once applied -- `_dispatch` only records it
        # (calling `self.app.set_theme()` from inside the handler hits the
        # same reentrant-borrow restriction as any other `QuiApp` call made
        # mid-dispatch); `step` applies and clears it right after
        # `self.app.step()` returns control to this top-level code. See
        # `step`'s own doc for which callers this actually reaches live.
        self._pending_theme_dark: bool | None = None
        # `_tree_capacity` needs these, but `_render` -- which calls it --
        # cannot query them live: `QuiApp`'s constructor below renders frame
        # 0 synchronously, before `self.app` itself exists to query, and
        # every later render runs from inside an active `self.app` call
        # (`step`/`screen`/`screen_contains`), which cannot be re-entered.
        # These placeholders cover that first render; overwritten with the
        # real measured values from `self.app` right after it exists.
        self._line_height = 1.0
        self._chrome_line_height = 1.0
        self._viewport_height = float(height)
        self._viewport_width = float(width)
        # Status-bar colors, same placeholder-then-overwrite dance as the
        # metrics above: `_apply_system_theme` (below) picks the real
        # light/dark pair from `system_theme()` right after `self.app`
        # exists, but frame 0 renders before that, inside `QuiApp`'s own
        # constructor -- so `_status_leaf` needs something paintable here
        # first. Defaults dark, matching this placeholder set's previous
        # fixed (always-dark) behavior.
        self._status_fg = _STATUS_DARK_FG
        self._status_bg = _STATUS_DARK_BG
        self._status_accent = _STATUS_DARK_ACCENT
        # The preview pane's layout-tree leaf, cached from `self.selected_file`
        # by `_set_selected_file` -- see that method for why `_render` only
        # reads this instead of reading+decoding the file itself every frame.
        self._preview_leaf = preview_leaf(self.selected_file, capacity=self._preview_content_capacity())
        self.app = QuiApp(width, height, render=self._render)
        # Obtained here, from top-level code: `actions()` is the only way the
        # handler can reach an overlay/OS call, and it is unreachable once a
        # run loop owns the app. See the module doc.
        self.actions = self.app.actions()
        self.app.set_handler(self._handle)
        self._line_height = self.app.line_height()
        self._chrome_line_height = self.app.chrome_line_height()
        self._viewport_width, self._viewport_height, _scale = self.app.viewport()
        self._refresh_preview()  # frame 0 ran with the placeholder capacity above
        self._apply_system_theme()
        for accelerator in ACCELERATORS:
            try:
                self.app.register_accelerator(accelerator)
            except QuadrauiError:
                # A backend that doesn't recognize this chord (`cmd+f` off
                # macOS, say) rejects the registration; skip just that one
                # entry rather than letting it raise out of `__init__` and
                # take every other, otherwise-fine, accelerator down with it.
                pass
        # Window title (C13): only cached here, never sent -- nothing is
        # titled until a run loop has a terminal or window to title (see
        # `live_title`). `start_live_title` sends this initial value and
        # `_sync_window_title` (called from `_handle`) keeps it current.
        self._title_cache = _window_title(self.cursor.path)
        # Tray icon + menu, and the represented-filename proxy icon for the
        # start folder (C13): unlike the calls above, neither is safe to
        # attempt here -- `self.app` only ever talks to the dormant headless
        # backend at this point (see this section's own "native chrome"
        # doc), so nothing done to `self.app`/`self.actions` in `__init__`
        # could ever reach a real tray or window. `_prime_native_chrome`,
        # called once from the first `_handle` dispatch instead, is what
        # actually sets these up on a `native_tray`/`native_window_chrome`
        # run.

    def _apply_system_theme(self) -> None:
        """OS theme match (C14): read the OS's light/dark preference once at
        startup and merge in the matching VS Code-like palette, and pick the
        matching status-bar colors (`StatusBarSegment` isn't theme-driven,
        see `_STATUS_DARK_FG`'s own doc). Falls back to the backend's own
        default theme and the dark status colors, both untouched, when
        `system_theme()` raises `InternalError` -- `Unsupported`, on the
        headless TUI backend with no `$COLORFGBG` set (see that method's own
        doc).

        Only ever reads the headless driver `self.app` wraps before any run
        loop starts -- `run_tui()`/`run_native()` haven't moved this app's
        state onto a real terminal/window backend yet at construction time,
        so a native run's initial palette is still this TUI-only
        `$COLORFGBG` heuristic, not the OS's own light/dark preference.
        `_dispatch`/`step` (see their own docs) keep that palette current
        for a `SystemThemeChanged` event, but only for a caller pumping
        `step`/`run` itself -- a real `run_tui()`/`run_native()` session has
        no way yet to re-read or react to the live backend's own OS theme."""
        try:
            info = self.app.system_theme()
        except InternalError:
            return
        self._set_theme(info["dark"])

    def _set_theme(self, dark: bool) -> None:
        """Merge in the VS Code light/dark palette and pick the matching
        status-bar colors for `dark`. Only safe to call from top-level code
        holding no handler-dispatch borrow on `self.app` -- see
        `_dispatch`'s and `step`'s own docs for why a `SystemThemeChanged`
        event can't call this directly from the handler that receives it."""
        self.app.set_theme(_VSCODE_DARK_THEME if dark else _VSCODE_LIGHT_THEME)
        self._status_fg = _STATUS_DARK_FG if dark else _STATUS_LIGHT_FG
        self._status_bg = _STATUS_DARK_BG if dark else _STATUS_LIGHT_BG
        self._status_accent = _STATUS_DARK_ACCENT if dark else _STATUS_LIGHT_ACCENT

    @property
    def window_title(self) -> str:
        """The title this app last set (or, before any event, the one
        `__init__` set at construction) -- `cli.py`'s/this module's own
        `__main__`'s public read of `_title_cache`, so a `run_native()`
        caller doesn't have to reach into a private attribute to derive its
        own `title=` argument from the start path."""
        return self._title_cache

    def start_live_title(self) -> None:
        """Turn on window/terminal titling and send the current title. Call
        from top-level code right before `run_tui()` -- like
        `register_accelerator` in `__init__`, it calls `self.app` directly,
        which a handler cannot. `TuiBackend::set_title` writes straight to
        stdout, so a closed or console-less stdout can make it fail; a
        cosmetic call must not stop the app from starting."""
        self.live_title = True
        try:
            self.app.set_title(self._title_cache)
        except QuadrauiError:
            pass

    def _sync_window_title(self) -> None:
        """Window title (C13), called from `_handle` after every event:
        if the cursored folder changed since the last call, updates the
        cached title and, once `live_title` is on, queues a `set_title`
        (safe on every backend) and, where `native_window_chrome` says it's safe (see
        that attribute's own doc), a `set_represented_filename` for the
        same folder. A plain equality check against the cached title
        rather than tracking `self.cursor` itself, so this fires exactly
        when the *displayed* title would actually change (not, e.g., on
        every keystroke that leaves the cursor on the same node)."""
        title = _window_title(self.cursor.path)
        if title == self._title_cache:
            return
        self._title_cache = title
        if not self.live_title:
            return
        self.actions.set_title(title)
        if self.native_window_chrome:
            self.actions.set_represented_filename(str(self.cursor.path))

    def _prime_native_chrome(self) -> None:
        """One-time native-chrome setup, called from the top of `_handle` on
        the first dispatch of whichever run loop set `native_window_chrome`/
        `native_tray` (`__init__` can't do this itself -- see this module's
        "native chrome" doc, above `_window_title`, for why `self.app`/
        `self.actions` there could never reach a real window or tray).

        A represented-filename proxy icon for the *start* folder, where
        `native_window_chrome` says that's safe -- `_sync_window_title`
        only ever queues one when the cursor actually moves, which the
        start folder by definition hasn't done yet.

        A tray icon, tooltip and menu, where `native_tray` says the live
        backend has one. Wrapped the same defensive way as
        `register_accelerator` in `__init__`: a backend that declares a
        tray but rejects one of the three calls anyway should not break
        the run loop its own first dispatch is part of."""
        if self._native_chrome_primed:
            return
        self._native_chrome_primed = True
        if self.native_window_chrome:
            self.actions.set_represented_filename(str(self.cursor.path))
        if self.native_tray:
            try:
                self.actions.set_tray_icon({"Bytes": _tray_icon_png()})
                self.actions.set_tray_tooltip("quadraui-files")
                self.actions.set_tray_menu(_tray_menu_items())
            except QuadrauiError:
                pass

    # --- navigation helpers --------------------------------------------------

    def _visible(self) -> tuple[list[dict], list[Node]]:
        """Current folder rows/nodes, with the cursor pulled back to its nearest
        still-visible ancestor if a collapse hid it."""
        rows, nodes = folder_rows(self.root)
        if self.cursor not in nodes:
            node = self.cursor
            while node is not None and node not in nodes:
                node = node.parent
            self.cursor = node or self.root
        return rows, nodes

    def _move(self, delta: int) -> None:
        rows, nodes = self._visible()
        i = nodes.index(self.cursor)
        new_i = max(0, min(len(nodes) - 1, i + delta))
        self.cursor = nodes[new_i]
        self._show_tree_tooltip(self.cursor, new_i)

    def _tree_capacity(self) -> int:
        """Painted rows that fit in the body's row band: the app's measured
        viewport height less the three chrome rows above/below it -- the
        toolbar row, the outer split's divider, and the bottom status line
        -- each `chrome_line_height` tall, converted into row units via
        `line_height`. Reads the cached metrics `__init__` measured from
        `self.app` itself (`viewport`/`line_height`/`chrome_line_height`)
        rather than guessing from the constructor's `height` argument.
        Named for the tree, its first caller, but the details and preview
        panes sit in that same vertical band (the nested detail/preview
        split is side-by-side, not stacked) so this doubles as their row
        capacity too -- `_preview_content_capacity` derives the preview's
        own (one row smaller, for its header) line cap from it."""
        chrome_rows = 3 * self._chrome_line_height / self._line_height
        return max(1, int(self._viewport_height / self._line_height - chrome_rows))

    def _preview_content_capacity(self) -> int:
        """Rows available for the preview's own `text_display` content: two
        fewer than the shared row band `_tree_capacity` measures -- one for
        the one-line header above it, one for that header's own split
        divider (a split reserves a row for its divider on top of whatever
        its two panes get, same as the outer split's divider shows up as
        its own screen row beyond the chrome/status panes it separates).
        See `_preview_pane`'s own doc for the matching split math."""
        return max(1, self._tree_capacity() - 2)

    def _refresh_preview(self) -> None:
        """Rebuild the cached preview-pane leaf from `self.selected_file`.
        Reading, decoding and line-splitting a file is I/O, and every other
        piece of state `_render` reads is computed here in the handler, not
        inside the render callback itself (the native backends in particular
        repaint far more often than the TUI) -- so this runs once, whenever
        the selection changes, rather than every frame."""
        self._preview_leaf = preview_leaf(self.selected_file, capacity=self._preview_content_capacity())

    def _set_selected_file(self, node: Node | None) -> None:
        """The one place `selected_file` is assigned, so the cached preview
        leaf above never goes stale."""
        self.selected_file = node
        self._refresh_preview()
        if node is not None:
            self._show_file_tooltip(node)

    def _show_tree_tooltip(self, node: Node, row_index: int) -> None:
        """Hover tooltip (see that section's own doc) for tree row
        `row_index`, currently painted at `node`. Anchored exactly: this
        app owns the tree's own `scroll` offset, so the row's on-screen
        position is fully known, not approximated."""
        x = 0.0
        y = self._chrome_line_height + (row_index - self.scroll) * self._line_height
        width = max(1.0, self.ratio * self._viewport_width)
        self.actions.show_tooltip(
            _tooltip_payload("fm:tooltip:tree", node), (x, y, width, self._line_height)
        )

    def _show_file_tooltip(self, node: Node) -> None:
        """Hover tooltip (see that section's own doc) for a details-table
        row that just became `node`. Anchored near the top of the details
        pane rather than at the row's own position: unlike the tree, this
        app never learns a `DataTable`'s own (backend-owned) scroll offset,
        so there is no way to know which screen row `node` actually painted
        on. The details pane's own width is `preview_ratio`'s fraction of
        the body's second split only while the preview is actually showing
        and that split exists at all; with the preview hidden, the details
        pane fills that whole second slot by itself (`_render`'s own doc)."""
        x = self.ratio * self._viewport_width
        y = self._chrome_line_height + self._line_height  # below the table's header row
        second_split_width = (1.0 - self.ratio) * self._viewport_width
        details_width = second_split_width * self.preview_ratio if self.preview_visible else second_split_width
        width = max(1.0, details_width)
        self.actions.show_tooltip(
            _tooltip_payload("fm:tooltip:details", node), (x, y, width, self._line_height)
        )

    def _scroll_to_cursor(self, cursor_index: int, row_count: int) -> None:
        """Advance `scroll` so the cursor row stays within the painted window,
        then clamp it so the last page never leaves a blank gap. The tree is
        declarative -- it renders `rows[scroll..]` -- so without this the view
        never follows the cursor and the scrollbar thumb never moves."""
        capacity = self._tree_capacity()
        if cursor_index < self.scroll:
            self.scroll = cursor_index
        elif cursor_index >= self.scroll + capacity:
            self.scroll = cursor_index - capacity + 1
        self.scroll = max(0, min(self.scroll, max(0, row_count - capacity)))

    def _expand(self) -> None:
        """Expand the cursored folder (loading it on demand); if it is already
        expanded, descend into its first subfolder."""
        node = self.cursor
        if not node.is_dir:
            return
        ensure_loaded(node)
        self._report_load_error(node)
        subdirs = node.subdirs()
        if not node.expanded and subdirs:
            node.expanded = True
        elif node.expanded and subdirs:
            self.cursor = subdirs[0]

    def _collapse(self) -> None:
        """Collapse the cursored folder; if already collapsed, jump to parent."""
        node = self.cursor
        if node.is_dir and node.expanded:
            node.expanded = False
        elif node.parent is not None:
            self.cursor = node.parent

    def _reveal(self, node: Node) -> None:
        """Expand every ancestor so `node` is a visible tree row."""
        parent = node.parent
        while parent is not None:
            ensure_loaded(parent)
            parent.expanded = True
            parent = parent.parent

    def _report_load_error(self, node: Node) -> None:
        """After an `ensure_loaded(node)` that may have just failed: if it
        did, set `self.message` naming the folder and the OS's own reason
        (`load_error_reason`), with a macOS-specific hint appended -- this
        is exactly the shape of failure a sandboxed terminal hits reading
        `~/Documents`/`~/Desktop`/etc on that platform. A no-op when the
        load succeeded (or hasn't been attempted)."""
        if node.load_error:
            reason = node.load_error_reason or "unknown error"
            hint = (
                " (macOS: System Settings → Privacy & Security → Files and Folders)"
                if sys.platform == "darwin"
                else ""
            )
            self.message = f"Can't read {node.path}: {reason}{hint}"

    def _show_folder_in_active_tab(self, node: Node) -> None:
        """A tree-row click: show `node`'s listing in the details pane,
        replacing the active tab's folder (VS Code/Finder sidebar
        behaviour) rather than opening a new tab -- opening a new tab stays
        a deliberate action (`_open`, via Enter / the context menu). With
        no tab open yet, opens the first one."""
        ensure_loaded(node)
        self._report_load_error(node)
        if not self.open:
            self.open.append(node)
            self.active_tab = 0
            return
        self.open[self.active_tab] = node

    def _open(self, node: Node | None = None) -> None:
        """Open `node` (default: the cursor) as a details tab, expanding it;
        focus its tab if already open. A file just reports itself."""
        node = node or self.cursor
        if not node.is_dir:
            self.message = f"{node.name} ({_human_size(node.size_bytes)})"
            return
        ensure_loaded(node)
        self._report_load_error(node)
        for i, existing in enumerate(self.open):
            if existing.path == node.path:
                self.active_tab = i
                return
        self.open.append(node)
        self.active_tab = len(self.open) - 1

    def _refresh(self) -> None:
        node = self.cursor
        if node.is_dir:
            node.children = None
            ensure_loaded(node)
            self._report_load_error(node)
            if not node.load_error:
                self.message = f"reloaded {node.name}"

    def _close_tab(self, index: int) -> None:
        if 0 <= index < len(self.open):
            del self.open[index]
            if self.active_tab >= len(self.open):
                self.active_tab = max(0, len(self.open) - 1)

    def _toggle_preview(self) -> None:
        """`p`: show/hide the preview pane (its header and content both).
        `preview_ratio` is left untouched either way, so re-showing it
        restores the same divider position it had before."""
        self.preview_visible = not self.preview_visible

    def _on_row_click(self, path: list[int]) -> None:
        """A tree-row click: select that folder and show it in the details
        pane (see `_show_folder_in_active_tab`), without touching its
        expansion state -- only the chevron (`_on_row_toggle_expand`) or
        Left/Right (`_expand`/`_collapse`) ever expands or collapses a row,
        so clicking around the tree is never "jumpy"."""
        rows, nodes = folder_rows(self.root)
        for idx, (row, node) in enumerate(zip(rows, nodes)):
            if row["path"] == list(path):
                self.cursor = node
                self._show_tree_tooltip(node, idx)
                self._show_folder_in_active_tab(node)
                return

    def _on_row_toggle_expand(self, path: list[int]) -> None:
        """A chevron click: toggle that folder's expansion in place, leaving
        the cursor wherever it already was (a row-body click selects the row
        too; the chevron is narrower, since it is reachable without first
        moving the cursor there)."""
        rows, nodes = folder_rows(self.root)
        for row, node in zip(rows, nodes):
            if row["path"] == list(path):
                ensure_loaded(node)
                self._report_load_error(node)
                if node.subdirs():
                    node.expanded = not node.expanded
                return

    def _visible_children(self, folder: Node) -> list[Node]:
        """`folder`'s children in the details table's current display order:
        narrowed by the live filter query, then ordered by whichever column
        was last clicked (Name/Size/Modified, ascending or reversed). With
        no filter and the default Name/ascending sort this is exactly
        `folder.children` -- a freshly loaded folder is already sorted that
        way -- so `RowActivated{idx}` keeps mapping straight back to it."""
        children = folder.children or []
        shown = _filter_children(children, self.filter_text)
        return _sort_children(shown, self.sort_col, self.sort_reverse)

    def _on_header_clicked(self, col: int) -> None:
        """A details-table header click: sort by that column, or reverse the
        current sort if it's already the active column. `sort_col`/
        `sort_reverse` are app-global, so this re-sorts every open details
        table, not just the one the click came from -- `_details_pane`
        applies them to every tab."""
        if self.sort_col == col:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_col = col
            self.sort_reverse = False

    def _activate_detail(self, idx: int) -> None:
        """A details-table row was activated (clicked): drill into a subfolder,
        or select the file and queue opening it with the OS's default app.
        `idx` indexes the same filtered/sorted order the table was painted
        with, not raw `folder.children`."""
        if not self.open:
            return
        folder = self.open[self.active_tab]
        children = self._visible_children(folder)
        if not (0 <= idx < len(children)):
            return
        child = children[idx]
        if child.is_dir:
            folder.expanded = True
            self._reveal(child)
            self.cursor = child
            self._open(child)
        else:
            self._set_selected_file(child)
            self.message = f"opening {child.name} ({_human_size(child.size_bytes)})"
            self._open_with_os(child)

    # --- file actions: delete/trash, open, reveal, context menu -------------
    #
    # Every overlay/OS call below goes through `self.actions`, the deferred
    # handle, so these are safe to reach from `_handle`; see the module doc.
    # Paths are checked for existence first: the queue applies an action after
    # the handler returns, and a `move_to_trash` of a vanished path fails
    # inside the event pump, where this app has no way to catch it.

    def _open_with_os(self, node: Node) -> None:
        """Hand `node` to the OS's default application for it."""
        if not node.path.exists():
            self.message = f"{node.name} is no longer there"
            return
        self.actions.open_path(str(node.path))

    def _reveal_in_os(self, node: Node) -> None:
        """Show `node` in the desktop's own file manager."""
        if not node.path.exists():
            self.message = f"{node.name} is no longer there"
            return
        self.actions.reveal_in_file_manager(str(node.path))

    def _delete_candidate(self) -> Node:
        """What a bare Delete keystroke (or the `Menu` key) acts on: the last
        file activated in the *current* tab, if it's still listed there,
        else the tree cursor."""
        if self.open and self.selected_file in (self.open[self.active_tab].children or ()):
            return self.selected_file
        return self.cursor

    # --- filter box, inline rename -------------------------------------------
    #
    # Both share one bottom-panel text_input (`edit_mode` says which) and one
    # key-handling path (`_handle_edit_key`): typed characters/Backspace edit
    # `edit_text` directly (a filter also mirrors every edit into
    # `filter_text` so the listing narrows live), Enter commits, Escape
    # cancels. No `QuiApp` call happens here, same as every other handler path.

    def _start_filter(self) -> None:
        """`/`: open the bottom filter box, seeded with whatever query (if
        any) is already narrowing the listing."""
        self.edit_mode = "filter"
        self.edit_text = self.filter_text

    def _start_rename(self, node: Node) -> None:
        """F2: open an inline rename box seeded with `node`'s current name,
        and mark the window dirty (C13) where that's safe (see
        `native_window_chrome`'s own doc) -- cleared again by
        `_commit_edit`/`_cancel_edit`."""
        if node is self.root:
            self.message = "can't rename the browser's root"
            return
        self.edit_mode = "rename"
        self.rename_target = node
        self.edit_text = node.name
        if self.native_window_chrome:
            self.actions.set_document_edited(True)

    def _edit_insert(self, text: str) -> None:
        self.edit_text += text
        if self.edit_mode == "filter":
            self.filter_text = self.edit_text

    def _edit_backspace(self) -> None:
        self.edit_text = self.edit_text[:-1]
        if self.edit_mode == "filter":
            self.filter_text = self.edit_text

    def _handle_edit_key(self, event: dict) -> bool:
        """Key events while the filter/rename box is open go through here
        instead of the normal dispatch -- returns True so `_handle`
        swallows them rather than falling through to navigation. A real
        `--tui` session never emits `CharTyped` for a plain keystroke
        (crossterm has no such variant -- every character lands as
        `KeyPressed{Char}`, same as this app's other single-letter
        shortcuts), so a bare printable `Char` is treated as typed text
        here too; `CharTyped` is still honoured for native/GTK hosts and
        for a test pushing it directly.

        Returns False for anything that isn't a key event at all --
        `MessageDialogResolved`, `ToastActionClicked`, a `DataTable`/`Tree`/
        `TabBar` activation, a divider drag -- so `_handle` falls through
        to its normal dispatch for those instead of silently dropping them
        (e.g. the undo toast's button still works while the filter box is
        open)."""
        if "CharTyped" in event:
            self._edit_insert(event["CharTyped"])
            return True
        key = _event_key(event)
        if key is None:
            return False
        if key == "Backspace":
            self._edit_backspace()
        elif key == "Enter":
            self._commit_edit()
        elif key == "Escape":
            self._cancel_edit()
        elif len(key) == 1:
            self._edit_insert(key)
        # else: a non-printable named key (Up/Down/Tab/F2/...) -- ignore.
        return True

    def _commit_edit(self) -> None:
        """Enter: a rename becomes a real rename on disk; a filter's query
        was already live -- this just closes the box and leaves it applied.
        Clears the dirty-dot (C13) a pending rename set, same gate as
        `_start_rename`."""
        was_renaming = self.edit_mode == "rename"
        if was_renaming:
            self._rename(self.rename_target, self.edit_text)
        self.edit_mode = None
        self.rename_target = None
        self.edit_text = ""
        if was_renaming and self.native_window_chrome:
            self.actions.set_document_edited(False)

    def _cancel_edit(self) -> None:
        """Escape: discard the rename (or clear the filter query) and close
        the box. Same dirty-dot clear as `_commit_edit` when the box being
        cancelled was a rename, not a filter."""
        was_renaming = self.edit_mode == "rename"
        if self.edit_mode == "filter":
            self.filter_text = ""
        self.edit_mode = None
        self.rename_target = None
        self.edit_text = ""
        if was_renaming and self.native_window_chrome:
            self.actions.set_document_edited(False)

    def _rename(self, node: Node | None, new_name: str) -> None:
        """Commit a pending rename: a real `Path.rename`, then update the
        model in place (name, path, and every loaded descendant's path) so
        the tree/details listing reflects it without a reload. A no-op
        name, an invalid name, a name collision, or an OS failure reports a
        message and leaves the node untouched."""
        new_name = new_name.strip()
        if node is None or not new_name or new_name == node.name:
            return
        invalid = _invalid_rename_name(new_name)
        if invalid is not None:
            self.message = invalid
            return
        new_path = node.path.with_name(new_name)
        if new_path.exists():
            # A case-only rename (`README.txt` -> `readme.txt`) legitimately
            # resolves to the same file on a case-insensitive filesystem;
            # only a genuinely different, already-occupied path is a
            # collision.
            try:
                same_file = new_path.samefile(node.path)
            except OSError:
                same_file = False
            if not same_file:
                self.message = f'"{new_name}" already exists'
                return
        try:
            node.path.rename(new_path)
        except (OSError, ValueError) as exc:
            self.message = f"rename failed: {exc}"
            return
        node.path = new_path
        node.name = new_name
        _reparent_paths(node)
        parent = node.parent
        if parent is not None and parent.children is not None:
            parent.children.sort(key=_sort_key)
        self.message = f"renamed to {new_name}"

    def _request_delete(self, node: Node) -> None:
        """Put up a Cancel/Delete confirm dialog for `node`."""
        if node is self.root:
            self.message = "can't trash the browser's root"
            return
        self._delete_target = node
        kind = "folder" if node.is_dir else "file"
        self.actions.show_message_dialog(
            title="Move to Trash",
            body=f'Move "{node.name}" ({kind}) to the Trash?',
            buttons=[
                {"id": "cancel", "label": "Cancel", "is_cancel": True},
                {"id": "delete", "label": "Delete", "is_default": True},
            ],
            severity="warning",
        )

    def _on_dialog_resolved(self, button_id: str) -> None:
        """The confirm dialog closed with `button_id`: trash on "delete", drop
        the pending target either way."""
        target = self._delete_target
        self._delete_target = None
        if button_id == "delete" and target is not None:
            self._trash(target)

    def _request_context_menu(self, node: Node) -> None:
        """Put up a context menu (Open / Reveal in file manager / Move to
        Trash) for `node`."""
        self._menu_target = node
        self.actions.show_context_menu(
            items=[
                {"id": "open", "label": _styled_text("Open")},
                {"id": "reveal", "label": _styled_text("Reveal")},
                {"id": "trash", "label": _styled_text("Move to Trash")},
            ],
            position=(2, 2),
        )

    def _on_menu_item(self, item_id: str) -> None:
        """A `ContextMenuItemActivated` event: a tray-menu item (C13) fires
        through the same event type a right-click context menu's item
        does (see `_tray_menu_items`'s own doc), so those two ids are
        checked first, independent of `self._menu_target`. Otherwise,
        run the matching action on `self._menu_target` (set when the
        context menu was requested).

        `tests/test_window_tray.py`'s tray-activation tests push this
        event directly and pin down that it reaches here correctly --
        whether a real native window's menu click actually enqueues it in
        the first place is a `quadraui` backend concern (its AppKit path
        only forces the `drawRect:` that drains a queued tray-menu
        activation when the app's own window happens to be `keyWindow` at
        click time -- see `quadraui::macos::tray::QuadraMenuTarget`), not
        this app's."""
        if item_id == TRAY_MENU_OPEN_HOME_ID:
            self.actions.open_path(str(Path.home()))
            return
        if item_id == TRAY_MENU_QUIT_ID:
            self._quit_requested = True
            return
        node = self._menu_target
        self._menu_target = None
        if node is None:
            return
        if item_id == "open":
            self._open_with_os(node)
        elif item_id == "reveal":
            self._reveal_in_os(node)
        elif item_id == "trash":
            self._request_delete(node)

    def _on_toast_action(self, action_id: str) -> None:
        """An action button on a toast was clicked: `undo` puts the last
        trashed path back where it came from."""
        if action_id != "undo":
            return
        node = self._undo_target
        self._undo_target = None
        if node is None:
            self.message = "nothing left to undo"
            return
        self.actions.restore_from_trash(str(node.path))
        # Optimistic, exactly as `_trash` is: the restore itself runs when the
        # pump drains the queue, after this handler returns.
        self._remember(node)
        self.message = f"restored {node.name}"
        # Fire-and-forget (see `send_notification`'s own doc): queued right
        # behind the restore, with nothing here to check it landed.
        self.actions.send_notification(title="Restored from Trash", body=node.name)

    def _trash(self, node: Node) -> None:
        """Move `node` to the trash, drop it from the model and any open tab,
        and put up an undo toast."""
        if not node.path.exists():
            self.message = f"{node.name} is no longer there"
            self._forget(node)
            return
        self.actions.move_to_trash(str(node.path))
        # Optimistic: the trash itself runs when the pump drains the queue, so
        # the model is updated now and the toast queued behind the removal.
        self._forget(node)
        self.message = ""
        self._undo_target = node if UNDO_SUPPORTED else None
        self._toast_seq += 1
        toast: dict = {
            "id": f"fm:toast:{self._toast_seq}",
            "title": "Moved to Trash — Undo" if UNDO_SUPPORTED else "Moved to Trash",
            "body": node.name,
        }
        if UNDO_SUPPORTED:
            toast["actions"] = [{"id": "undo", "label": "Undo", "style": "Default"}]
        self.actions.show_toast(toast=toast)
        # Fire-and-forget (see `send_notification`'s own doc): queued right
        # behind the toast, so a trash completing while this window isn't
        # focused still surfaces through the OS's own notification center.
        self.actions.send_notification(title="Moved to Trash", body=node.name)

    def _forget(self, node: Node) -> None:
        """Drop `node` from the model after it's been trashed: remove it from
        its parent's children, close its details tab if it had one, and pull
        the cursor/selection off it."""
        parent = node.parent
        if parent is not None and parent.children is not None:
            parent.children = [c for c in parent.children if c is not node]
        self.open = [f for f in self.open if f is not node]
        if self.active_tab >= len(self.open):
            self.active_tab = max(0, len(self.open) - 1)
        if self.cursor is node:
            self.cursor = parent or self.root
        if self.selected_file is node:
            self._set_selected_file(None)

    def _remember(self, node: Node) -> None:
        """Put `node` back into the model after a restore, in display order.
        The inverse of `_forget`, minus the tab/cursor state that restoring a
        path says nothing about: an undone delete re-lists the entry, it does
        not reopen the tab it closed."""
        parent = node.parent
        if parent is None or parent.children is None:
            return
        if node not in parent.children:
            parent.children = sorted([*parent.children, node], key=_sort_key)

    def step(self, event: dict) -> None:
        """Push `event` and dispatch it. `QuiApp.step` also drains the
        deferred-action queue the handler may have filled (a confirm dialog, a
        context menu, a toast, an open/reveal/trash), exactly as `run_tui`'s
        own pump does, so one call leaves the app in the state a real session
        would show.

        Also applies a `SystemThemeChanged` event's palette right here, now
        that `self.app.step()` has returned control to this top-level code
        -- `_dispatch` (see its own doc) only ever records the new dark/light
        flag, since `self.app.set_theme()` can't be called from inside the
        handler `self.app.step()` was still running. That means this only
        reaches a real OS theme switch live when something -- this app's own
        black-box suite, or any other caller pumping `step`/`run` by hand --
        drives the app this same way; a session started via
        `run_tui()`/`run_native()` blocks until it exits and never returns
        control here, so it cannot react to a live OS appearance change at
        all yet."""
        self.app.push_event(event)
        self.app.step()
        if self._pending_theme_dark is not None:
            self._set_theme(self._pending_theme_dark)
            self._pending_theme_dark = None

    # --- render + handle -----------------------------------------------------

    def _details_pane(self) -> dict:
        """The body split's second pane: a placeholder until a folder is opened,
        then a closable tabs container with one data_table tab per open folder."""
        if not self.open:
            return {
                "id": "fm:empty",
                "text_display": {
                    "id": "fm:empty",
                    "lines": [_styled_text("Select a folder and press Enter to open it.")],
                },
            }
        return {
            "id": "fm:tabs",
            "tabs": {
                "id": "fm:tabs",
                "selected": self.active_tab,
                "closable": True,
                "tabs": [
                    {
                        "id": f"tab:{i}",
                        "title": folder.name,
                        "closable": True,
                        "content": {
                            "id": f"fm:grid:{i}",
                            "data_table": details_table(
                                folder,
                                i,
                                children=self._visible_children(folder),
                                sort_col=self.sort_col,
                                sort_reverse=self.sort_reverse,
                            ),
                        },
                    }
                    for i, folder in enumerate(self.open)
                ],
            },
        }

    def _preview_column_width_cells(self) -> float:
        """Cell width of the preview column (header + content): the
        viewport's share left after the tree pane (`ratio`) and the
        details pane (`preview_ratio` of what's left) are taken out --
        the complementary fraction to `_show_file_tooltip`'s own details-
        pane width."""
        return max(1.0, (1.0 - self.ratio) * (1.0 - self.preview_ratio) * self._viewport_width)

    def _preview_header_name_max_chars(self, size_text: str) -> int:
        """How many characters the header's name segment gets before
        `_ellipsize` has to cut it: the preview column's own cell width,
        less the size segment sitting next to it (never priority-dropped,
        so it must always fit too) and `_PREVIEW_HEADER_RESERVED_CELLS`
        for the close control and the left/right min gap -- capped at
        `_PREVIEW_NAME_MAX_CHARS` so a very wide window doesn't paint an
        absurdly long name."""
        column_width = int(self._preview_column_width_cells())
        size_cells = len(size_text) + 2 if size_text else 0  # padded " <size> "
        name_padding = 2  # padded " <name> "
        budget = column_width - size_cells - _PREVIEW_HEADER_RESERVED_CELLS - name_padding
        return max(4, min(_PREVIEW_NAME_MAX_CHARS, budget))

    def _preview_header_leaf(self) -> dict:
        """The preview column's one-line header: the file name and its size
        as left segments (left segments are never priority-dropped, so the
        size always survives), the modified time and a close (×) control
        as right segments ordered least-important first (so a narrow
        column drops the timestamp, never the close control) -- see the
        preview-header section's own doc for why a `status_bar` fits this
        and how the close control actually fires."""
        name, size, mtime = _preview_header_parts(self.selected_file)
        name = _ellipsize(name, self._preview_header_name_max_chars(size))
        left_segments = [self._segment(f" {name} ", bold=True)]
        if size:
            left_segments.append(self._segment(f" {size} "))
        right_segments = []
        if mtime:
            right_segments.append(self._segment(f" {mtime} "))
        right_segments.append(self._segment(" × ", action_id=PREVIEW_HEADER_CLOSE_ACTION))
        return {
            "id": "fm:preview_header",
            "status_bar": {
                "id": "fm:preview_header",
                "left_segments": left_segments,
                "right_segments": right_segments,
            },
        }

    def _preview_pane(self) -> dict:
        """The detail split's second pane: a vertical split stacking the
        one-line header over the preview's own content, sized so the header
        always gets exactly one row and the content gets the rest of the
        shared row band (`_tree_capacity`) -- the same `first_min`/
        `second_min` floor-at-a-line-count trick `_render`'s outer split
        already uses for its own status bar, just with the fixed pane on
        top instead of the bottom.

        `total_rows` is the band `_tree_capacity` measures; `available` is
        one row less than that, since this split (like the outer one) gets
        its own divider row free, on top of whatever its two panes get --
        `ratio` has to target that reduced space, not `total_rows` itself,
        or the header would end up taller than one row. `second_min`
        matches `_preview_content_capacity`'s own `- 2` exactly: one row
        for the header, one for this divider."""
        total_rows = max(3.0, float(self._tree_capacity()))
        header_rows = 1.0
        available = total_rows - 1.0
        return {
            "split": {
                "id": "fm:preview_header_split",
                "orientation": "vertical",  # header stacked over content
                "ratio": header_rows / available,
                "first_min": header_rows,
                "second_min": available - header_rows,
                "first": self._preview_header_leaf(),
                "second": self._preview_leaf,
            }
        }

    def _segment(
        self,
        text: str,
        *,
        accent: bool = False,
        bold: bool = False,
        action_id: str | None = None,
    ) -> dict:
        """One `StatusBarSegment`: styled text with the colors
        `_apply_system_theme` picked for the current OS light/dark
        preference (see `_STATUS_DARK_FG`'s own doc for why this needs its
        own instance-level colors rather than theme-driven `StyledText`).
        `action_id`, left unset everywhere but the preview header's close
        control, makes the segment clickable -- a click raises a
        `StatusBar`/`SegmentClicked` event carrying it back (see the
        preview-header section's own doc)."""
        segment = {
            "text": text,
            "fg": self._status_accent if accent else self._status_fg,
            "bg": self._status_bg,
            "bold": bold,
        }
        if action_id is not None:
            segment["action_id"] = action_id
        return segment

    def _status_leaf(self) -> dict:
        """The outer split's bottom pane: a live status bar showing the cursored
        folder, its item count, the open-tab summary, and any transient hint."""
        node = self.cursor
        if node.children is None:
            count_text = "unopened"
        else:
            count_text = f"{len(node.children)} items"
        left = [
            self._segment(f" {node.name} ", accent=True, bold=True),
            self._segment(f" {count_text} "),
        ]
        if self.message:
            left.append(self._segment(f" {self.message} "))
        if self.filter_text:
            left.append(self._segment(f' filter: "{self.filter_text}" '))
        open_n = len(self.open)
        if open_n:
            right = [self._segment(f" tab {self.active_tab + 1}/{open_n} ")]
        else:
            right = [self._segment(" no tabs ")]
        right.append(self._segment(f" {int(round(self.ratio * 100))}% "))
        return {
            "id": "fm:status",
            "status_bar": {
                "id": "fm:status",
                "left_segments": left,
                "right_segments": right,
            },
        }

    def _edit_leaf(self) -> dict:
        """The outer split's bottom pane while the filter/rename box is
        open: a live text_input showing its label and buffer, swapped in
        for the status bar."""
        label = "Filter" if self.edit_mode == "filter" else "Rename"
        text = f"{label}: {self.edit_text}"
        return {
            "id": "fm:edit",
            "text_input": {
                "id": "fm:edit",
                "lines": [text],
                "cursor_line": 0,
                "cursor_col": len(text),
                "has_focus": True,
            },
        }

    def _render(self) -> dict:
        """Per-frame: rebuild the whole frame from state. An outer vertical split
        stacks the chrome+body (top) over a one-line status bar (bottom); the
        body is the resizable tree/(details|preview) split, wrapped in a
        `sidebar_panel` whose reserved slot paints the toolbar above it. The
        details and preview panes are themselves a nested resizable split, so
        the frame is sidebar | details | preview overall -- unless
        `preview_visible` is off, in which case the preview (header and
        content both) is dropped and the details pane fills that whole
        second slot on its own, giving its width back without disturbing
        `preview_ratio` (restored from, unchanged, the next time the
        preview is shown again). Reads only."""
        rows, nodes = self._visible()
        cursor_index = nodes.index(self.cursor)
        selected_path = rows[cursor_index]["path"]
        self._scroll_to_cursor(cursor_index, len(rows))
        details_and_preview = (
            {
                "split": {
                    "id": "fm:detail_split",
                    "orientation": "horizontal",  # details beside its preview, vertical divider
                    "ratio": self.preview_ratio,
                    "first": self._details_pane(),
                    "second": self._preview_pane(),
                }
            }
            if self.preview_visible
            else self._details_pane()
        )
        body = {
            "split": {
                "id": "fm:split",
                "orientation": "horizontal",  # panes side by side, vertical divider
                "ratio": self.ratio,
                "first": tree_leaf(rows, selected_path=selected_path, scroll_offset=self.scroll),
                "second": details_and_preview,
            }
        }
        chrome = {
            "sidebar_panel": {
                "id": "fm:chrome",
                "toolbar": TOOLBAR,  # reserved top slot, one line per backend
                "content": body,
            }
        }
        # Pin the status bar to the bottom line: `ratio` derives from the known
        # height so the bottom pane is ~one line, and `second_min` floors it at
        # one line if the real terminal is a different size. Drags on this outer
        # divider are ignored by the handler (it keys on the body split's id).
        # The filter/rename text_input needs 3 rows (every backend borders it,
        # even TUI), so the bottom pane grows to 3 while `edit_mode` is set --
        # but never past what the chrome's own 3.0 `first_min` leaves available,
        # so the two mins can never sum past the viewport on a tiny terminal
        # (e.g. `h == 4` would otherwise ask for 3.0 + 3.0 of 4.0 rows).
        h = max(self.height, 2)
        first_min = 3.0
        available_for_bottom = max(1.0, h - first_min)
        bottom_rows = min(3.0, available_for_bottom) if self.edit_mode else 1.0
        return {
            "split": {
                "id": "fm:outer",
                "orientation": "vertical",  # chrome+body stacked over the status bar
                "ratio": (h - bottom_rows) / h,
                "first_min": first_min,
                "second_min": bottom_rows,
                "first": chrome,
                "second": self._edit_leaf() if self.edit_mode else self._status_leaf(),
            }
        }

    def _handle(self, event) -> None:
        """Per-event entry point: primes native chrome (C13) on the very
        first dispatch of a run that opted into it, then `_dispatch` does
        the real work, then this syncs the window title against wherever
        the cursor landed -- after every event, not just a navigation one,
        so it still catches a `TabClosed`/`_forget` pulling the cursor back
        onto a different node with no dedicated "move" call of its own."""
        self._prime_native_chrome()
        self._dispatch(event)
        self._sync_window_title()

    def _dispatch(self, event) -> None:
        """Per-event: move the cursor, expand/collapse, open/close tabs, drill
        into folders, resize, queue a file action. Mutates state only; never
        calls into `QuiApp` -- see the module doc's reentrant-borrow note."""
        if event == "ContextMenuDismissed":
            self._menu_target = None
            return
        if not isinstance(event, dict):
            return

        if "SystemThemeChanged" in event:
            # Recorded only -- `self.app.set_theme()` cannot be called from
            # in here: it hits the same reentrant-borrow restriction as
            # every other `QuiApp` call the module doc describes, and
            # unlike `set_cursor`/`set_tray_icon`/the file actions below,
            # there is no deferred, handler-safe `self.actions` equivalent
            # for a theme change to queue instead. `step` applies this
            # once `self.app.step()` returns to its own top-level code;
            # see that method's doc for which run loops this actually
            # reaches live.
            self._pending_theme_dark = event["SystemThemeChanged"]["dark"]
            return

        if self._dragging and "SplitDividerDragged" not in event:
            # The divider drag that set the resize cursor, below, has ended
            # -- `MouseUp` is the event the engine actually sends, but any
            # other event arriving instead (focus loss, a resize, ...) means
            # the drag is just as over, so this doesn't key specifically off
            # `MouseUp`. Restore the pointer before falling through to this
            # event's own handling (a `MouseUp` itself has none here).
            self._dragging = False
            self.actions.set_cursor("default")

        if self.edit_mode is not None and self._handle_edit_key(event):
            return

        # `edit_mode is not None` here means `_handle_edit_key` returned
        # False just above -- an event that isn't a key at all, not an
        # accelerator the filter/rename box is meant to swallow. Every
        # accelerator registered in `ACCELERATORS` maps onto an action the
        # edit box already suppresses from its equivalent plain key (see
        # that list's own doc), so this drops it the same way instead of
        # firing while the box has focus.
        if "Accelerator" in event:
            if self.edit_mode is None:
                self._on_accelerator(event["Accelerator"][0])
            return

        if "MessageDialogResolved" in event:
            self._on_dialog_resolved(event["MessageDialogResolved"])
            return
        if "ContextMenuItemActivated" in event:
            self._on_menu_item(event["ContextMenuItemActivated"])
            return
        if "ToastActionClicked" in event:
            self._on_toast_action(event["ToastActionClicked"])
            return

        key = _event_key(event)
        if key is not None:
            self._on_key(key)
            return

        if "DataTable" in event:
            activation = event["DataTable"][1]
            if "RowActivated" in activation:
                self._activate_detail(activation["RowActivated"]["idx"])
            elif "HeaderClicked" in activation:
                self._on_header_clicked(activation["HeaderClicked"]["col"])
        elif "Tree" in event:
            activation = event["Tree"][1]
            if "RowClicked" in activation:
                self._on_row_click(activation["RowClicked"]["path"])
            elif "RowToggleExpand" in activation:
                self._on_row_toggle_expand(activation["RowToggleExpand"]["path"])
        elif "TabBar" in event:
            activation = event["TabBar"][1]
            if "TabActivated" in activation:
                self.active_tab = activation["TabActivated"]["index"]
            elif "TabClosed" in activation:
                self._close_tab(activation["TabClosed"]["index"])
        elif "StatusBar" in event:
            activation = event["StatusBar"][1]
            if "SegmentClicked" in activation:
                clicked_id = activation["SegmentClicked"]["id"]
                if clicked_id == PREVIEW_HEADER_CLOSE_ACTION:
                    self.preview_visible = False
        elif "SplitDividerDragged" in event:
            drag = event["SplitDividerDragged"]
            # Only the two body splits are user-resizable; the outer
            # chrome/status split is fixed, so ignore drags that aren't one
            # of theirs.
            tree = drag.get("tree")
            if tree == "fm:split":
                self.ratio = drag["new_ratio"]
            elif tree == "fm:detail_split":
                self.preview_ratio = drag["new_ratio"]
            if tree in ("fm:split", "fm:detail_split"):
                # Pointer cursor (C13): both dividers are vertical (panes
                # side by side -- see `_render`'s own comment), so
                # `"col_resize"` rather than the compass-edge `"resize"`
                # shape. Always safe to call: `QuiAppActions.set_cursor`
                # queues the shape for whichever backend is live when the
                # queue next drains rather than raising for one that can't
                # show it -- the TUI one included, which has no native
                # pointer concept at all (see this section's own "native
                # chrome" doc). `self._dragging`, reset by the top of this
                # method once the drag ends, is what restores `"default"`.
                self._dragging = True
                self.actions.set_cursor("col_resize")

    def _on_key(self, name: str) -> None:
        self.message = ""
        if name == "Down":
            self._move(1)
        elif name == "Up":
            self._move(-1)
        elif name == "Right":
            self._expand()
        elif name == "Left":
            self._collapse()
        elif name in ("Enter", "o"):
            self._open()
        elif name == "r":
            self._refresh()
        elif name == "Delete":
            self._request_delete(self._delete_candidate())
        elif name == "Menu":
            self._request_context_menu(self._delete_candidate())
        elif name == "/":
            self._start_filter()
        elif name == "F2":
            self._start_rename(self._delete_candidate())
        elif name == "p":
            self._toggle_preview()

    def _on_accelerator(self, accel_id: str) -> None:
        """A registered global accelerator (C15, `ACCELERATORS`) fired --
        the same actions `_on_key` runs for the equivalent plain key,
        reached here instead because the chord (`ctrl+f`/`cmd+f`) or the
        OS-level binding (`F2`/`Delete`) arrives as its own `Accelerator`
        event rather than a plain `KeyPressed` once registered.

        Dropped outright while the delete-confirm dialog or the context
        menu is open: an `Accelerator` is matched earlier in the pipeline
        than a plain `KeyPressed`, so it reaches this handler even while
        one of those overlays is up and the modal's own `KeyPressed`/
        `MouseDown` interception never gets a chance to swallow it first.
        Without this guard, `Delete` mid-confirm re-enters
        `_request_delete`, overwriting `_delete_target` and queueing a
        second dialog on top of the first; `F2` opens the rename box
        behind either overlay. Mirrors `edit_mode`'s own suppression of
        these same accelerators, just above."""
        if self._delete_target is not None or self._menu_target is not None:
            return
        self.message = ""
        if accel_id == "fm:accel:rename":
            self._start_rename(self._delete_candidate())
        elif accel_id == "fm:accel:delete":
            self._request_delete(self._delete_candidate())
        elif accel_id in ("fm:accel:search", "fm:accel:search_cmd"):
            self._start_filter()


# --- inspection / headless helpers -------------------------------------------


def _dump(node: Node, indent: int = 0) -> None:
    """Human-readable dump of the loaded model."""
    pad = "  " * indent
    if node.is_dir:
        chevron = "v" if node.expanded else ">"
        print(f"{pad}{chevron} {node.name}/")
        for child in node.children or ():
            _dump(child, indent + 1)
    else:
        size = "" if node.size_bytes is None else f"  ({node.size_bytes} B)"
        print(f"{pad}  {node.name}{size}")


def _dump_folder_rows(rows: list[dict]) -> None:
    """Human-readable dump of the folders-only tree rows."""
    for row in rows:
        pad = "  " * row["indent"]
        chevron = "▾ " if row["is_expanded"] else "▸ "
        glyph = row["icon"]["glyph"]
        text = row["text"]["spans"][0]["text"]
        path = ",".join(str(i) for i in row["path"]) or "-"
        print(f"  path=[{path:<8}] {pad}{chevron}{glyph} {text}")


def _dump_grid(descriptor: dict) -> None:
    """Human-readable dump of a details table."""
    titles = [c["title"] for c in descriptor["columns"]]
    widths = [20, 10, 8]

    def _row_text(cells_text: list[str]) -> str:
        return "  ".join(f"{t:<{w}}" for t, w in zip(cells_text, widths))

    print("  " + _row_text(titles))
    for row in descriptor["rows"]:
        cells_text = ["".join(s["text"] for s in cell["spans"]) for cell in row["cells"]]
        print("  " + _row_text(cells_text))


def _dump_steps(root_path: Path) -> None:
    root = build_root(root_path)
    print("# model (root loaded one level)")
    _dump(root)
    print("\n# folders-only tree rows")
    rows, _nodes = folder_rows(root)
    _dump_folder_rows(rows)
    print("\n# details table for the root folder")
    _dump_grid(details_table(root, 0))


class _Quit(Exception):
    """Raised from the handler to unwind out of `run_tui()`/`run_native()` --
    a terminal has no window-manager close event, so a quit keystroke is the
    only way to ask `run_tui()` to return."""


def _wrap_quit(fm: FileManager) -> None:
    """Wrap the handler so `q`/Escape exits the real run loops, leaving the
    headless demo (which never sees those keys) untouched.

    `run_tui()`/`run_native()` block the Python thread for their whole run,
    dispatching events straight to this handler with no point in between
    where top-level script code -- the only place free to call `QuiApp`,
    per the module doc's reentrant-borrow note -- ever gets control back.
    The file actions do not need such a point: they are queued on the
    deferred-action handle and drained by those loops' own pumps, so the
    confirm dialog, context menu, toast and OS calls appear on a real
    backend exactly as they do headlessly. Only the quit keystroke needs
    this wrapper, since a terminal has no close event to unwind on.

    Skipped entirely while the filter/rename box is open: `q` is then a
    character to type, not a shortcut, and `Escape` cancels the box
    instead of the whole app -- both routed to `inner` just like every
    other key, which already knows how to tell the two states apart.

    Also the only place the tray's `Quit` item (C13) can end a real run
    loop: `_on_menu_item` can't raise `_Quit` itself (it has no idea this
    wrapper exists), so it just sets `fm._quit_requested` and this checks
    that flag right after every dispatch, same as it checks the plain
    keystroke above."""
    inner = fm._handle

    def handler(event) -> None:
        key = _event_key(event) if isinstance(event, dict) else None
        if fm.edit_mode is None and key in ("q", "Escape"):
            raise _Quit
        inner(event)
        if fm._quit_requested:
            raise _Quit

    fm.app.set_handler(handler)


def _key_event(key: dict) -> dict:
    return {
        "KeyPressed": {
            "key": key,
            "modifiers": {"shift": False, "ctrl": False, "alt": False, "meta": False},
            "repeat": False,
        }
    }


def _run_headless(fm: FileManager) -> None:
    """Drive the app with Python owning the loop: expand a folder, open it as a
    tab, drill into a subfolder from its details table, then print the final
    screen -- runnable with no feature build."""
    steps = [
        _key_event(DOWN_KEY),    # cursor onto the first subfolder
        _key_event(RIGHT_KEY),   # expand it (load on demand)
        _key_event(ENTER_KEY),   # open it as a details tab
        # Activate the first details row (a click would deliver this), drilling
        # into it if it is a subfolder.
        {"DataTable": ["fm:grid:0", {"RowActivated": {"idx": 0}}]},
    ]
    for event in steps:
        fm.step(event)
    print(fm.app.screen())
    open_names = [n.name for n in fm.open]
    print(f"\ncursor={fm.cursor.name}  open_tabs={open_names}  "
          f"active_tab={fm.active_tab}  ratio={fm.ratio}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    root = Path(args[0]) if args else Path.cwd()

    if "--dump" in flags:
        _dump_steps(root.resolve())
        sys.exit(0)

    fm = FileManager(root.resolve())

    # --- the only platform-specific line is the run call below --------------
    if "--tui" in flags:
        _wrap_quit(fm)  # real terminal: raw mode, live redraw on key events
        fm.start_live_title()
        try:
            fm.app.run_tui()
        except _Quit:
            pass
    elif "--native" in flags:
        _wrap_quit(fm)  # OS window: GTK / AppKit / Win32 per the built feature
        fm.live_title = True  # `run_native(title=...)` sets the initial one
        # Only safe to flip right here, right before the one call that
        # actually opens a real native window -- see `native_window_chrome`/
        # `native_tray`'s own docs for why this reads the *built* backend
        # (`_NATIVE_BACKEND`), not the host OS.
        fm.native_window_chrome = _NATIVE_BACKEND == "macos"
        fm.native_tray = _NATIVE_BACKEND in ("gtk", "macos", "win")
        try:
            fm.app.run_native(title=fm.window_title)
        except _Quit:
            pass
    else:
        _run_headless(fm)  # Python owns the loop; prints the final screen
