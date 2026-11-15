"""#54 black-box coverage: Finder's per-file color tags -- the details
grid's colored dot, Get Info's tag picker, and the context menu's "Tags"
submenu. Real xattr I/O is macOS-only (`_MacTagReader`); every rendering/
picker path here is driven through a stubbed `TagReader` instead, per this
issue's own Verification section, and one test separately pins down that
none of the picker UI shows up at all with the platform's own default
reader on this (non-macOS) test host -- the "no-op/hidden on Windows and
Linux" half of the same section."""

import plistlib
import subprocess
from pathlib import Path

import pytest

import quadraui_files.app as app
from conftest import click as _click
from conftest import find_row as _find_row

from quadraui_files import FileManager
from quadraui_files.app import (
    DOWN_KEY,
    ENTER_KEY,
    MENU_KEY,
    RIGHT_KEY,
    TAG_COLOR_NAMES,
    _TAG_DOT_GLYPH,
    _key_event,
    _NullTagReader,
)

ESCAPE_KEY = {"Named": "Escape"}


def _open_root_tab(fm: FileManager) -> None:
    fm.step(_key_event(ENTER_KEY))


def _select(fm: FileManager, name: str) -> None:
    x, y = _find_row(fm, name)
    _click(fm, x, y)


def _accel(accel_id: str) -> dict:
    return {"Accelerator": [accel_id, {"shift": False, "ctrl": False, "alt": False, "cmd": False}]}


def _open_tag_picker_from_get_info(fm: FileManager) -> None:
    """Get Info is already open with its default ("OK") button focused;
    `Right` moves focus to "Tags…", `Enter` activates it -- a *real*
    key-driven resolve, same as every other dialog test in this repo uses
    (`Escape`/`Enter`), unlike a raw `MessageDialogResolved` push: only a
    real resolve has the backend's own widget actually remove the dialog,
    so pushing the event directly would leave Get Info's own box stacked
    underneath the picker that opens on top of it."""
    fm.step(_key_event(RIGHT_KEY))
    fm.step(_key_event(ENTER_KEY))


def _pick_tag(fm: FileManager, color: str | None) -> None:
    """Picks `color` (or `None` for "No Tag") from an already-open tag
    picker: `Down` the right number of times from "No Tag" (the first,
    always-focused item), then `Enter`."""
    steps = 0 if color is None else TAG_COLOR_NAMES.index(color) + 1
    for _ in range(steps):
        fm.step(_key_event(DOWN_KEY))
    fm.step(_key_event(ENTER_KEY))


class _StubTagReader:
    """A `TagReader` that never touches the filesystem -- an in-memory dict
    a test can both seed (`tags=`) and inspect (`sets`, every `set()` call
    in order)."""

    def __init__(self, tags: dict[Path, str | None] | None = None):
        self.tags: dict[Path, str | None] = dict(tags or {})
        self.sets: list[tuple[Path, str | None]] = []

    def get(self, path: Path) -> str | None:
        return self.tags.get(path)

    def set(self, path: Path, color: str | None) -> None:
        self.sets.append((path, color))
        self.tags[path] = color


# --- the details grid's colored dot ------------------------------------------


def test_tagged_file_shows_a_colored_dot_in_the_details_grid(sample_tree):
    (sample_tree / "readme.txt").write_text("hello")
    reader = _StubTagReader({sample_tree / "readme.txt": "Red"})
    fm = FileManager(sample_tree, tag_reader=reader)
    _open_root_tab(fm)

    assert f"{_TAG_DOT_GLYPH} readme.txt" in fm.app.screen()


def test_untagged_file_shows_no_dot(sample_tree):
    (sample_tree / "readme.txt").write_text("hello")
    fm = FileManager(sample_tree, tag_reader=_StubTagReader())
    _open_root_tab(fm)

    assert _TAG_DOT_GLYPH not in fm.app.screen()


# --- hidden without a real tag reader (Windows/Linux) ------------------------


def test_tag_picker_is_hidden_with_a_null_tag_reader(sample_tree):
    """`_NullTagReader` is what every non-macOS host falls back to
    (`TAG_READER`'s own doc) -- injected explicitly here rather than
    relying on this test host *not* being macOS (it might be), so neither
    Get Info nor the context menu should offer a tag picker."""
    (sample_tree / "readme.txt").write_text("hello")
    fm = FileManager(sample_tree, tag_reader=_NullTagReader())
    _open_root_tab(fm)
    _select(fm, "readme.txt")

    fm.step(_accel("fm:accel:get_info_cmd"))
    assert "Tag:" not in fm.app.screen()
    fm.step(_key_event(ESCAPE_KEY))

    fm.step(_key_event(MENU_KEY))
    assert "Tags" not in fm.app.screen()


# --- Get Info's tag picker ----------------------------------------------------


def test_get_info_shows_the_current_tag_and_a_tags_button(sample_tree):
    (sample_tree / "readme.txt").write_text("hello")
    reader = _StubTagReader({sample_tree / "readme.txt": "Blue"})
    fm = FileManager(sample_tree, tag_reader=reader)
    _open_root_tab(fm)
    _select(fm, "readme.txt")

    fm.step(_accel("fm:accel:get_info_cmd"))
    screen = fm.app.screen()
    assert "Tag: Blue" in screen
    assert "Tags" in screen


def test_get_info_tags_button_opens_a_picker_with_every_color(sample_tree):
    """Get Info's own button row has no wrapping and rejects a `tint`
    outright, so the picker itself opens as a (vertically stacked) context
    menu rather than one button per color -- see `_open_tag_picker`'s own
    doc."""
    (sample_tree / "readme.txt").write_text("hello")
    reader = _StubTagReader({sample_tree / "readme.txt": "Blue"})
    fm = FileManager(sample_tree, tag_reader=reader)
    _open_root_tab(fm)
    _select(fm, "readme.txt")

    fm.step(_accel("fm:accel:get_info_cmd"))
    _open_tag_picker_from_get_info(fm)

    screen = fm.app.screen()
    assert "No Tag" in screen
    for color in TAG_COLOR_NAMES:
        assert color in screen


def test_clicking_a_get_info_tag_picker_color_applies_the_tag(sample_tree):
    (sample_tree / "readme.txt").write_text("hello")
    reader = _StubTagReader()
    fm = FileManager(sample_tree, tag_reader=reader)
    _open_root_tab(fm)
    _select(fm, "readme.txt")

    fm.step(_accel("fm:accel:get_info_cmd"))
    _open_tag_picker_from_get_info(fm)
    _pick_tag(fm, "Red")

    assert reader.sets == [(sample_tree / "readme.txt", "Red")]
    assert f"{_TAG_DOT_GLYPH} readme.txt" in fm.app.screen()


def test_clicking_no_tag_clears_an_existing_tag(sample_tree):
    (sample_tree / "readme.txt").write_text("hello")
    reader = _StubTagReader({sample_tree / "readme.txt": "Green"})
    fm = FileManager(sample_tree, tag_reader=reader)
    _open_root_tab(fm)
    _select(fm, "readme.txt")

    fm.step(_accel("fm:accel:get_info_cmd"))
    _open_tag_picker_from_get_info(fm)
    _pick_tag(fm, None)

    assert reader.sets == [(sample_tree / "readme.txt", None)]
    assert _TAG_DOT_GLYPH not in fm.app.screen()


# --- the context menu's "Tags" submenu ---------------------------------------


def test_context_menu_lists_tags_right_after_get_info(sample_tree):
    (sample_tree / "readme.txt").write_text("hello")
    fm = FileManager(sample_tree, tag_reader=_StubTagReader())
    _open_root_tab(fm)
    _select(fm, "readme.txt")

    fm.step(_key_event(MENU_KEY))
    screen = fm.app.screen()
    assert "Tags" in screen
    assert screen.index("Get Info") < screen.index("Tags") < screen.index("Rename")


def test_context_menu_tag_item_applies_the_tag(sample_tree):
    (sample_tree / "readme.txt").write_text("hello")
    reader = _StubTagReader()
    fm = FileManager(sample_tree, tag_reader=reader)
    _open_root_tab(fm)
    _select(fm, "readme.txt")

    fm.step(_key_event(MENU_KEY))
    fm.step({"ContextMenuItemActivated": "tag:Purple"})

    assert reader.sets == [(sample_tree / "readme.txt", "Purple")]
    assert f"{_TAG_DOT_GLYPH} readme.txt" in fm.app.screen()


# --- _MacTagReader itself (the real, macOS-only xattr I/O) ------------------
#
# Everything above drives the picker/grid through a stubbed `TagReader` --
# there's no real Finder tag to read on this (non-macOS) test host. These
# exercise `_MacTagReader`'s own pure-Python merge/lookup logic directly,
# with the OS-level read (`_mac_user_tags`) and write (`subprocess.run`)
# monkeypatched out: exactly the path the black-box suite above can never
# reach, and where the reviewed label-index/clobber bugs lived.


def test_tag_color_label_index_matches_finders_own_numbering():
    """Finder's `kMDItemFSLabel` table, not `TAG_COLORS`' swatch-row order
    (Red/Orange/Yellow/Green/Blue/Purple/Gray) -- a file tagged "Red" here
    must carry Finder's own Red index (6), not the swatch position (1)."""
    assert app._TAG_COLOR_LABEL_INDEX == {
        "Gray": 1,
        "Green": 2,
        "Purple": 3,
        "Blue": 4,
        "Yellow": 5,
        "Red": 6,
        "Orange": 7,
    }


def _fake_run(calls: list, returncode: int = 0, stderr: bytes = b""):
    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, returncode, stdout=b"", stderr=stderr)

    return run


def test_mac_tag_reader_set_preserves_other_finder_tags(monkeypatch, tmp_path):
    """Setting a color must not drop a free-text tag (`"Invoices"`) the
    file already carries in Finder -- `set()` reads the existing array and
    only replaces the one color entry, per its own doc."""
    monkeypatch.setattr(app, "_mac_user_tags", lambda path: ["Work", "Invoices", "Blue\n4"])
    calls: list = []
    monkeypatch.setattr(app.subprocess, "run", _fake_run(calls))

    app._MacTagReader().set(tmp_path / "f.txt", "Red")

    assert len(calls) == 1
    argv = calls[0]
    assert argv[:3] == [app._XATTR_BIN, "-w", "-x"]
    written = plistlib.loads(bytes.fromhex(argv[4]))
    assert set(written) == {"Work", "Invoices", "Red\n6"}


def test_mac_tag_reader_set_none_clears_only_the_color_entry(monkeypatch, tmp_path):
    """Clearing the tag ("No Tag") must leave any other Finder tag alone --
    only the one entry naming a color comes out."""
    monkeypatch.setattr(app, "_mac_user_tags", lambda path: ["Work", "Green\n2"])
    calls: list = []
    monkeypatch.setattr(app.subprocess, "run", _fake_run(calls))

    app._MacTagReader().set(tmp_path / "f.txt", None)

    assert len(calls) == 1
    written = plistlib.loads(bytes.fromhex(calls[0][4]))
    assert written == ["Work"]


def test_mac_tag_reader_set_deletes_the_xattr_once_no_tags_remain(monkeypatch, tmp_path):
    """Clearing the only tag a file has removes the whole attribute,
    rather than writing an empty-but-present array back."""
    monkeypatch.setattr(app, "_mac_user_tags", lambda path: ["Red\n6"])
    calls: list = []
    monkeypatch.setattr(app.subprocess, "run", _fake_run(calls))

    path = tmp_path / "f.txt"
    app._MacTagReader().set(path, None)

    assert calls == [[app._XATTR_BIN, "-d", app._KMD_USER_TAGS_XATTR, str(path)]]


def test_mac_tag_reader_set_raises_on_a_failed_write(monkeypatch, tmp_path):
    """A failed `xattr -w` (read-only volume, EPERM, ...) raises `OSError`
    rather than being silently swallowed -- `FileManager._set_tag_color`
    reports it instead of claiming the tag stuck."""
    monkeypatch.setattr(app, "_mac_user_tags", lambda path: [])
    monkeypatch.setattr(
        app.subprocess, "run", _fake_run([], returncode=1, stderr=b"Operation not permitted")
    )

    with pytest.raises(OSError):
        app._MacTagReader().set(tmp_path / "f.txt", "Red")


def test_mac_tag_reader_set_tolerates_deleting_a_tag_that_was_never_set(monkeypatch, tmp_path):
    """Clearing a tag on a file with no color tag at all (and no other
    Finder tags) is a no-op, not a reported failure, even though
    `xattr -d` itself exits non-zero for "no such attribute"."""
    monkeypatch.setattr(app, "_mac_user_tags", lambda path: [])
    monkeypatch.setattr(
        app.subprocess,
        "run",
        _fake_run([], returncode=1, stderr=b"xattr: No such xattr: com.apple.metadata:_kMDItemUserTags"),
    )

    app._MacTagReader().set(tmp_path / "f.txt", None)  # must not raise


def test_mac_tag_reader_get_ignores_non_color_tags(monkeypatch, tmp_path):
    """`get()` only reports the one entry naming a Finder color -- other
    free-text tags on the same file don't confuse it."""
    monkeypatch.setattr(app, "_mac_user_tags", lambda path: ["Work", "Purple\n3", "Invoices"])

    assert app._MacTagReader().get(tmp_path / "f.txt") == "Purple"
