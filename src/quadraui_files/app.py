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
    │                                      └─ second : a read-only preview of
    │                                                  the last file selected
    │                                                  in a details table
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
  click a tree row         select it and toggle its expansion
  activate a details row   drill into that subfolder, or open a file with
                            the OS's default app for it
  click a details header   sort every open details table by that column
                            (marked with ▲/▼ on the active header); click
                            the same header again to reverse it
  click a tab / its ×      switch to / close that tab
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
    directories sorted first. On an unreadable directory, leaves it empty and
    flags `load_error`. Files are a no-op."""
    if not node.is_dir:
        return
    try:
        entries = [c for c in node.path.iterdir() if not c.name.startswith(".")]
    except OSError:
        node.children = []
        node.load_error = True
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
            note = "(unreadable)"
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
# resize glyph during a divider drag.
#
# Each of the four calls this needs has a different safety story on the
# backend this app's own `self.app` always talks to (the headless
# `TuiBackend` -- see the module doc's reentrancy note for why `run_native`
# moving the app's descriptors/handlers onto a real GTK/AppKit/Win32 window
# doesn't change which backend `self.app` itself queries):
#
#   * `set_title` -- always safe. Every backend implements `WindowControl::
#     set_title` (the TUI one via OSC 0/2), so `_sync_window_title` calls it
#     unconditionally on every navigation.
#   * `set_cursor` -- always safe. `Backend::set_cursor` returns whether the
#     glyph was actually applied rather than raising (`False`, never an
#     error, on a backend with no native pointer concept), so a divider drag
#     calls it unconditionally too.
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
#     call on `sys.platform == "darwin"`.
#   * `set_tray_icon` / `set_tray_tooltip` / `set_tray_menu` -- gated on
#     `backend_caps()["tray"]`, read once at startup. `Backend::tray`
#     returns `None` permanently on `TuiBackend` (a terminal has no
#     notification-area concept at all), so this is always skipped on that
#     backend -- see `tests/test_window_tray.py`'s own caps tests, kept
#     exactly for that reason.


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
        if isinstance(payload, list) and len(payload) == 2 and isinstance(payload[1], dict):
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
        self.open: list[Node] = []      # folder nodes shown as tabs, in order
        self.active_tab = 0             # index into self.open
        self.message = ""               # transient status hint
        self.selected_file: Node | None = None  # last file activated in a details tab

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
        # before a `run_native()` call on `sys.platform == "darwin"`.
        self.native_window_chrome = False
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
        self._preview_leaf = preview_leaf(self.selected_file, capacity=self._tree_capacity())
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
        # Window title (C13): called directly on `self.app`, not through
        # `self.actions` -- `__init__` is top-level code, same as
        # `register_accelerator`/`set_theme` above, so it owns the one
        # exclusive borrow outright rather than needing the deferred-action
        # workaround a handler would. `_sync_window_title` (called from
        # `_handle`) takes over from here, through `self.actions`, once a
        # run loop owns the app.
        self._window_title = _window_title(self.cursor.path)
        self.app.set_title(self._window_title)
        # Tray icon + menu (C13): also top-level, also gated -- `self.app`'s
        # own backend is the headless one (`run_native` moves this app's
        # descriptors/handlers onto a real window; it does not change what
        # `self.app` itself queries), which never has a tray, so this is a
        # no-op on every backend reachable from this call. Wrapped the same
        # defensive way as `register_accelerator`, above: a backend that
        # declares `"tray"` but rejects one of the three calls anyway
        # should not take `__init__` down with it.
        if self.app.backend_caps()["tray"]:
            try:
                self.app.set_tray_icon({"Bytes": _tray_icon_png()})
                self.app.set_tray_tooltip("quadraui-files")
                self.app.set_tray_menu(_tray_menu_items())
            except QuadrauiError:
                pass

    def _apply_system_theme(self) -> None:
        """OS theme match (C14): read the OS's light/dark preference once at
        startup and merge in the matching VS Code-like palette, and pick the
        matching status-bar colors (`StatusBarSegment` isn't theme-driven,
        see `_STATUS_DARK_FG`'s own doc). Falls back to the backend's own
        default theme and the dark status colors, both untouched, when
        `system_theme()` raises `InternalError` -- `Unsupported`, on the
        headless TUI backend with no `$COLORFGBG` set (see that method's own
        doc)."""
        try:
            info = self.app.system_theme()
        except InternalError:
            return
        dark = info["dark"]
        self.app.set_theme(_VSCODE_DARK_THEME if dark else _VSCODE_LIGHT_THEME)
        self._status_fg = _STATUS_DARK_FG if dark else _STATUS_LIGHT_FG
        self._status_bg = _STATUS_DARK_BG if dark else _STATUS_LIGHT_BG
        self._status_accent = _STATUS_DARK_ACCENT if dark else _STATUS_LIGHT_ACCENT

    def _sync_window_title(self) -> None:
        """Window title (C13), called from `_handle` after every event:
        if the cursored folder changed since the last call, queues a
        `set_title` -- unconditionally, `set_title` is safe on every
        backend -- and, where `native_window_chrome` says it's safe (see
        that attribute's own doc), a `set_represented_filename` for the
        same folder. A plain equality check against the cached title
        rather than tracking `self.cursor` itself, so this fires exactly
        when the *displayed* title would actually change (not, e.g., on
        every keystroke that leaves the cursor on the same node)."""
        title = _window_title(self.cursor.path)
        if title == self._window_title:
            return
        self._window_title = title
        self.actions.set_title(title)
        if self.native_window_chrome:
            self.actions.set_represented_filename(str(self.cursor.path))

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
        capacity too -- `_render` reuses it as the preview's line cap."""
        chrome_rows = 3 * self._chrome_line_height / self._line_height
        return max(1, int(self._viewport_height / self._line_height - chrome_rows))

    def _refresh_preview(self) -> None:
        """Rebuild the cached preview-pane leaf from `self.selected_file`.
        Reading, decoding and line-splitting a file is I/O, and every other
        piece of state `_render` reads is computed here in the handler, not
        inside the render callback itself (the native backends in particular
        repaint far more often than the TUI) -- so this runs once, whenever
        the selection changes, rather than every frame."""
        self._preview_leaf = preview_leaf(self.selected_file, capacity=self._tree_capacity())

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
        on."""
        x = self.ratio * self._viewport_width
        y = self._chrome_line_height + self._line_height  # below the table's header row
        width = max(1.0, (1.0 - self.ratio) * self.preview_ratio * self._viewport_width)
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

    def _open(self, node: Node | None = None) -> None:
        """Open `node` (default: the cursor) as a details tab, expanding it;
        focus its tab if already open. A file just reports itself."""
        node = node or self.cursor
        if not node.is_dir:
            self.message = f"{node.name} ({_human_size(node.size_bytes)})"
            return
        ensure_loaded(node)
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
            self.message = f"reloaded {node.name}"

    def _close_tab(self, index: int) -> None:
        if 0 <= index < len(self.open):
            del self.open[index]
            if self.active_tab >= len(self.open):
                self.active_tab = max(0, len(self.open) - 1)

    def _on_row_click(self, path: list[int]) -> None:
        """A tree-row click: select that folder and toggle its expansion."""
        rows, nodes = folder_rows(self.root)
        for idx, (row, node) in enumerate(zip(rows, nodes)):
            if row["path"] == list(path):
                self.cursor = node
                self._show_tree_tooltip(node, idx)
                ensure_loaded(node)
                if node.subdirs():
                    node.expanded = not node.expanded
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
        context menu was requested)."""
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
        would show."""
        self.app.push_event(event)
        self.app.step()

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

    def _segment(self, text: str, *, accent: bool = False, bold: bool = False) -> dict:
        """One `StatusBarSegment`: styled text with the colors
        `_apply_system_theme` picked for the current OS light/dark
        preference (see `_STATUS_DARK_FG`'s own doc for why this needs its
        own instance-level colors rather than theme-driven `StyledText`)."""
        return {
            "text": text,
            "fg": self._status_accent if accent else self._status_fg,
            "bg": self._status_bg,
            "bold": bold,
        }

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
        the frame is sidebar | details | preview overall. Reads only."""
        rows, nodes = self._visible()
        cursor_index = nodes.index(self.cursor)
        selected_path = rows[cursor_index]["path"]
        self._scroll_to_cursor(cursor_index, len(rows))
        details_and_preview = {
            "split": {
                "id": "fm:detail_split",
                "orientation": "horizontal",  # details beside its preview, vertical divider
                "ratio": self.preview_ratio,
                "first": self._details_pane(),
                "second": self._preview_leaf,
            }
        }
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
        """Per-event entry point: `_dispatch` does the real work, then this
        syncs the window title (C13) against wherever the cursor landed --
        after every event, not just a navigation one, so it still catches
        a `TabClosed`/`_forget` pulling the cursor back onto a different
        node with no dedicated "move" call of its own."""
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
                # shape. Always safe to call: `set_cursor` answers whether
                # the glyph was actually applied rather than raising (see
                # this section's own "native chrome" doc), `False` rather
                # than an error on a backend -- the TUI one included --
                # with no native pointer concept at all.
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
        try:
            fm.app.run_tui()
        except _Quit:
            pass
    elif "--native" in flags:
        _wrap_quit(fm)  # OS window: GTK / AppKit / Win32 per the built feature
        # Only safe to flip right here, right before the one call that
        # actually opens a real macOS window -- see `native_window_chrome`'s
        # own doc for why a TUI session on a Mac must never set this.
        fm.native_window_chrome = sys.platform == "darwin"
        try:
            fm.app.run_native(title=fm._window_title)
        except _Quit:
            pass
    else:
        _run_headless(fm)  # Python owns the loop; prints the final screen
