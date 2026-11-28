"""Finder's own per-file color tags (macOS only, #54) -- the 7 built-in
colors it's shipped since Mavericks, painted as a colored dot next to a
file's name and offered as a picker from Get Info / the context menu.
Windows/Nautilus have no equivalent metadata to anchor a cross-platform
design on (VISION.md's Finder-parity backlog explicitly ranks this item
last for exactly that reason), so this is deliberately macOS-only, both in
storage (real xattr/Spotlight metadata, not app-private state -- a tag set
here shows up in a real Finder window on the same file, and vice versa)
and in the picker UI, which simply isn't offered anywhere else
(`FileManager._tags_supported`).

The colored dot itself needs no quadraui descriptor seam: `details_table`'s
Name cell is already a `StyledText` with an arbitrary per-span `fg`, so the
dot is just one more colored glyph span ahead of the name -- `_tag_dot_span`
below builds that span, but is otherwise framework-free, no `quadraui`
import. `quadraui_files.app` re-exports every public name here; tests keep
importing them from there.
"""

from __future__ import annotations

import ctypes
import os
import plistlib
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class TagColor:
    """One of Finder's 7 built-in label colors."""

    name: str
    rgb: tuple[int, int, int]


TAG_COLORS: tuple[TagColor, ...] = (
    TagColor("Red", (255, 69, 58)),
    TagColor("Orange", (255, 159, 10)),
    TagColor("Yellow", (255, 214, 10)),
    TagColor("Green", (48, 209, 88)),
    TagColor("Blue", (10, 132, 255)),
    TagColor("Purple", (191, 90, 242)),
    TagColor("Gray", (142, 142, 147)),
)
TAG_COLOR_NAMES: tuple[str, ...] = tuple(c.name for c in TAG_COLORS)
_TAG_RGB: dict[str, tuple[int, int, int]] = {c.name: c.rgb for c in TAG_COLORS}
# Finder's own legacy label index (1-7, written as the trailing digit of the
# `"<name>\n<index>"` tag string `_MacTagReader` reads/writes) -- this is
# `kMDItemFSLabel`'s own numbering, NOT the swatch order `TAG_COLORS` lists
# above (that order is only this app's own picker's/Finder's Tags-picker
# *display* row). Needs reconfirming on a real Mac before shipping (tag a
# file with each of the 7 colors in Finder, `xattr -px
# com.apple.metadata:_kMDItemUserTags` on it, and compare the trailing
# digit against this table) -- no macOS box is available in this
# environment to do that firsthand.
_TAG_COLOR_LABEL_INDEX: dict[str, int] = {
    "Gray": 1,
    "Green": 2,
    "Purple": 3,
    "Blue": 4,
    "Yellow": 5,
    "Red": 6,
    "Orange": 7,
}
_TAG_DOT_GLYPH = "●"


def _tag_dot_span(color: str | None) -> dict | None:
    """The Name cell's leading `StyledSpan` for `color` (one of
    `TAG_COLOR_NAMES`), or `None` when there's no tag to show at all --
    `DataRow` has no `Icon`-bearing field (`_codicon_glyph`'s own doc covers
    the same gap for the file-type marker), so the dot is just a colored
    glyph baked into the cell's own `StyledText.spans`."""
    if color is None:
        return None
    r, g, b = _TAG_RGB[color]
    return {"text": f"{_TAG_DOT_GLYPH} ", "fg": {"r": r, "g": g, "b": b, "a": 255}, "bg": None}


class TagReader(Protocol):
    """Reads/writes one path's Finder tag color: `None` means no tag, else
    one of `TAG_COLOR_NAMES`. `_MacTagReader` is the real, macOS-only
    implementation; `_NullTagReader` is the permanent no-op everywhere else.
    A test injects its own stub instead of either (`FileManager(...,
    tag_reader=...)`) -- the "black-box for the rendering/picker UI with a
    stubbed tag reader" story this issue's own Verification section asks
    for, since there is no real xattr to read on the box the suite runs on."""

    def get(self, path: Path) -> str | None: ...

    def set(self, path: Path, color: str | None) -> None: ...


class _NullTagReader:
    """The non-macOS `TagReader`: Windows and Linux have no `kMDItemUserTags`
    equivalent to read or write (this issue's own "no Explorer/Nautilus
    equivalent" is why color tags stay macOS-only), so every call here is a
    no-op. `FileManager._tags_supported` is `False` exactly when this is the
    active reader, which is what actually hides the picker UI -- this
    class's own no-op-ness alone would just mean every tag silently reads
    back `None`, not that the picker disappears."""

    def get(self, path: Path) -> str | None:
        return None

    def set(self, path: Path, color: str | None) -> None:
        pass


_KMD_USER_TAGS_XATTR = "com.apple.metadata:_kMDItemUserTags"
_XATTR_BIN = "/usr/bin/xattr"  # absolute, so a Homebrew/pip `xattr` on $PATH can't shadow the system one


def _darwin_getxattr(path: Path, name: str) -> bytes | None:
    """Reads extended attribute `name` off `path` in-process, via libSystem's
    own `getxattr(2)` through `ctypes` -- `_tag_color_for` calls this once
    per row on every render (`render()` rebuilds the tree every frame), so
    an `/usr/bin/xattr` subprocess spawn per row would visibly stall a
    large folder's first paint. CPython's own `os.getxattr`/`os.setxattr`
    aren't built on Darwin (`posixmodule.c`'s `HAVE_XATTR` guard, which its
    own `configure` never defines there), so `ctypes` against the libc
    already loaded into this process is the in-process route, not a
    subprocess at all -- no `timeout=` to pick here, there's no process to
    hang. Returns `None` for "no such attribute" and for any other OS-level
    failure alike (a missing/unreadable file, say) -- both mean "nothing to
    show", same as the old subprocess path's blanket `except`."""
    libc = ctypes.CDLL(None, use_errno=True)
    libc.getxattr.restype = ctypes.c_ssize_t
    libc.getxattr.argtypes = [
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_uint32,
        ctypes.c_int,
    ]
    raw_path = os.fsencode(str(path))
    raw_name = name.encode("utf-8")
    size = libc.getxattr(raw_path, raw_name, None, 0, 0, 0)
    if size < 0:
        return None
    buf = ctypes.create_string_buffer(size)
    size = libc.getxattr(raw_path, raw_name, buf, size, 0, 0)
    if size < 0:
        return None
    return buf.raw[:size]


def _mac_user_tags(path: Path) -> list[str]:
    """Every raw `"<name>\\n<label-index>"` (or plain free-text) entry of
    `path`'s own `_kMDItemUserTags`, or `[]` when it has none / isn't
    readable. Shared by `_MacTagReader.get` (which only cares about the one
    entry naming a color) and `.set` (which has to keep every *other*
    entry untouched -- see its own doc)."""
    raw = _darwin_getxattr(path, _KMD_USER_TAGS_XATTR)
    if raw is None:
        return []
    try:
        tags = plistlib.loads(raw)
    except (ValueError, plistlib.InvalidFileException, TypeError):
        return []
    if not isinstance(tags, list):
        # A plist that decodes to something other than an array -- not
        # what Finder itself ever writes, but a third-party tool's xattr
        # is input this app doesn't control; degrade to "no tags" rather
        # than let a non-iterable take the render frame down.
        return []
    return [tag for tag in tags if isinstance(tag, str)]


class _MacTagReader:
    """The real macOS `TagReader`: Finder's own `_kMDItemUserTags` xattr, a
    binary-plist array of `"<name>\\n<label-index>"` strings -- the exact
    shape Finder itself reads/writes, so a tag set here shows up in a real
    Finder window on the same file, and vice versa. Reads happen in-process
    (`_darwin_getxattr`, no subprocess spawn -- see its own doc); writes
    still shell out to `/usr/bin/xattr`, since there is no in-process
    `setxattr` to reach for either (same `HAVE_XATTR` gap), and a write is
    one per user action rather than one per rendered row. Keeps (and
    writes) only the one tag that names one of Finder's 7 built-in colors
    -- a file can carry other, free-text tags too, which aren't a color
    this app's picker offers, and both `get()` and `set()` leave those
    alone: `set()` reads the existing array first and only replaces the
    color entry, rather than overwriting the whole attribute."""

    def get(self, path: Path) -> str | None:
        for tag in _mac_user_tags(path):
            name = tag.split("\n", 1)[0]
            if name in _TAG_RGB:
                return name
        return None

    def set(self, path: Path, color: str | None) -> None:
        """Applies `color` (or clears it for `None`) without touching any
        other tag `path` already carries. Raises `OSError` if the
        underlying `xattr` write fails (read-only volume, EPERM, missing
        `xattr` binary, ...) -- `FileManager._set_tag_color` reports that
        to the user instead of claiming success for a tag that isn't
        actually on disk."""
        kept = [tag for tag in _mac_user_tags(path) if tag.split("\n", 1)[0] not in _TAG_RGB]
        if color is not None:
            kept.append(f"{color}\n{_TAG_COLOR_LABEL_INDEX[color]}")
        path_str = str(path)
        if not kept:
            result = subprocess.run(
                [_XATTR_BIN, "-d", _KMD_USER_TAGS_XATTR, path_str],
                capture_output=True,
                timeout=1,
            )
            # `xattr -d` on an attribute that was never set is already a
            # no-op from this method's own point of view (nothing left to
            # clear), so that one non-zero exit doesn't count as a failure.
            if result.returncode != 0 and b"No such xattr" not in result.stderr:
                raise OSError(result.stderr.decode(errors="replace").strip() or "xattr -d failed")
            return
        payload = plistlib.dumps(kept, fmt=plistlib.FMT_BINARY)
        result = subprocess.run(
            [_XATTR_BIN, "-w", "-x", _KMD_USER_TAGS_XATTR, payload.hex(), path_str],
            capture_output=True,
            timeout=1,
        )
        if result.returncode != 0:
            raise OSError(result.stderr.decode(errors="replace").strip() or "xattr -w failed")


# The default reader every real run picks (a test overrides it via
# `FileManager`'s own `tag_reader=` constructor arg, never this global) --
# `sys.platform` is right here, unlike the `_NATIVE_BACKEND` check at
# `app.py`'s own top: this is a host-OS capability (which xattr exists to
# read), not a built Cargo feature a cross-compiled binary could disagree
# with its host about.
TAG_READER: TagReader = _MacTagReader() if sys.platform == "darwin" else _NullTagReader()
