"""#54 black-box coverage: Finder's per-file color tags -- the details
grid's colored dot, Get Info's tag picker, and the context menu's "Tags"
submenu. Real xattr I/O is macOS-only (`_MacTagReader`); every rendering/
picker path here is driven through a stubbed `TagReader` instead, per this
issue's own Verification section, and one test separately pins down that
none of the picker UI shows up at all with the platform's own default
reader on this (non-macOS) test host -- the "no-op/hidden on Windows and
Linux" half of the same section."""

from pathlib import Path

from conftest import click as _click
from conftest import find_row as _find_row

from quadraui_files import FileManager
from quadraui_files.app import DOWN_KEY, ENTER_KEY, MENU_KEY, RIGHT_KEY, TAG_COLOR_NAMES, _TAG_DOT_GLYPH, _key_event

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


def test_tag_picker_is_hidden_with_the_default_reader_on_this_host(sample_tree):
    """The default reader on this (non-macOS) test host is `_NullTagReader`
    -- neither Get Info nor the context menu should offer a tag picker."""
    (sample_tree / "readme.txt").write_text("hello")
    fm = FileManager(sample_tree)
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
