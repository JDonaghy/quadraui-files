"""T3 black-box tests: the read-only preview pane -- selecting a file in a
details table shows its content (text), a real decoded picture (a raster
image, native backends only -- the TUI shows the same size/type
placeholder a binary file gets), or that same placeholder (a binary file,
or an image quadraui's own decoder can't handle) in the third (preview)
region of the frame, driven headlessly through `FileManager.step` exactly
like the other feature tranches' tests."""

import os
import struct
import zlib
from pathlib import Path

from conftest import activate_child as _activate_child

from quadraui_files import FileManager
from quadraui_files.app import DELETE_KEY, ENTER_KEY, PREVIEW_MAX_BYTES, _key_event


def _open_root_tab(fm: FileManager) -> None:
    """Opens the root folder as a details tab *and* shows the preview pane
    -- hidden by default now (View menu / `p`), but every test in this
    file is specifically about what's in it, so showing it is part of
    this file's own "open the tab" setup, not something each test repeats."""
    fm.step(_key_event(ENTER_KEY))
    fm._toggle_preview()


def _write_tiny_png(path: Path, color: tuple[int, int, int] = (255, 0, 0)) -> None:
    """A real, decodable 2x2 PNG -- unlike the deliberately-corrupt
    `image.png` below (a PNG header followed by garbage, used to exercise
    the undecodable-image fallback), this is valid enough for quadraui's
    own image decoder to accept, so it reaches `preview_leaf`'s `image`
    branch for real rather than falling back to placeholder text."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0)
    row = b"\x00" + bytes(color) * 2
    idat = zlib.compress(row * 2)
    path.write_bytes(sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b""))


def test_no_selection_shows_a_placeholder(sample_tree):
    fm = FileManager(sample_tree)
    _open_root_tab(fm)
    assert "No file selected." in fm.app.screen()


def test_selecting_a_text_file_shows_its_content(sample_tree):
    # Short enough not to wrap across preview-pane rows on a narrow terminal.
    (sample_tree / "readme.txt").write_text("zzqMARKERzz\nsecond\n")
    fm = FileManager(sample_tree)
    _open_root_tab(fm)

    _activate_child(fm, "readme.txt")

    screen = fm.app.screen()
    assert "zzqMARKERzz" in screen, f"preview missing content:\n{screen}"


def test_selecting_a_binary_file_shows_a_size_and_type_placeholder(sample_tree):
    binary_path = sample_tree / "image.png"
    binary_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    fm = FileManager(sample_tree)
    _open_root_tab(fm)

    _activate_child(fm, "image.png")

    screen = fm.app.screen()
    size = f"{binary_path.stat().st_size} B"
    assert size in screen, f"preview missing size placeholder:\n{screen}"
    assert "image/png" in screen, f"preview missing type placeholder:\n{screen}"


def test_selecting_a_valid_image_builds_a_real_image_leaf(sample_tree):
    """A real, decodable raster image routes to `preview_leaf`'s `image`
    branch -- a no-op on the headless TUI backend (nothing but
    `fallback_text` ever paints there for an `image` leaf, so there's no
    pixel to assert on), but a real decoded picture on every native
    backend. Checked on the built leaf itself rather than the screen."""
    png_path = sample_tree / "photo.png"
    _write_tiny_png(png_path)
    fm = FileManager(sample_tree)
    _open_root_tab(fm)

    _activate_child(fm, "photo.png")

    assert "image" in fm._preview_leaf, f"expected an image leaf: {fm._preview_leaf}"
    image = fm._preview_leaf["image"]
    assert image["source"] == {"Path": str(png_path)}
    assert image["fit"] == "Contain"
    assert "image/png" in image["fallback_text"]
    # Same placeholder text the undecodable-PNG test above checks for on
    # screen -- the TUI's own fallback must read identically either way.
    assert f"{png_path.stat().st_size} B" in image["fallback_text"]


def test_an_svg_still_shows_its_raw_markup_not_an_image_leaf(sample_tree):
    """`image/svg+xml` is vector/XML, not a raster format quadraui's
    `Image` primitive decodes -- it keeps going through the ordinary text
    preview exactly as before this app ever routed any image through an
    `image` leaf, rather than trading a useful markup preview for a bare
    fallback placeholder."""
    (sample_tree / "icon.svg").write_text("<svg><circle r='1'/></svg>")
    fm = FileManager(sample_tree)
    _open_root_tab(fm)

    _activate_child(fm, "icon.svg")

    assert "text_display" in fm._preview_leaf
    assert "<svg>" in fm.app.screen()


def test_selecting_a_different_file_replaces_the_preview(sample_tree):
    (sample_tree / "readme.txt").write_text("root readme content")
    (sample_tree / "alpha" / "notes.txt").write_text("zzqALPHANOTESzz")
    fm = FileManager(sample_tree)
    _open_root_tab(fm)

    _activate_child(fm, "readme.txt")
    assert "root readme content" in fm.app.screen()

    _activate_child(fm, "alpha")  # a folder opens in place
    _activate_child(fm, "notes.txt")

    screen = fm.app.screen()
    assert "zzqALPHANOTESzz" in screen, f"preview missing content:\n{screen}"
    assert "root readme content" not in screen


def test_large_text_file_is_truncated_and_shows_the_head_not_the_tail(sample_tree):
    """The preview leaf pins `text_display` to its head (`auto_scroll:
    False`, `scroll_offset: 0`) rather than its tail-following default, and
    on top of that a file bigger than the pane's row capacity is truncated
    to that capacity before it ever reaches the descriptor -- so a large
    file shows its head, not its last few rows."""
    line_count = FileManager(sample_tree)._tree_capacity() + 50
    big = "\n".join(f"line {i}" for i in range(line_count))
    (sample_tree / "big.txt").write_text(big)
    fm = FileManager(sample_tree)  # re-built so big.txt is in its scanned model
    _open_root_tab(fm)

    _activate_child(fm, "big.txt")

    screen = fm.app.screen()
    assert "line 0" in screen, f"preview should start at the file's head:\n{screen}"
    assert "truncated" in screen
    assert f"line {line_count - 1}" not in screen, f"tail leaked into the preview:\n{screen}"


def test_large_non_ascii_text_file_is_not_misreported_as_binary(sample_tree):
    """`PREVIEW_MAX_BYTES` is a hard byte cutoff, not a character-aligned
    one. A 3-byte-per-character CJK run makes that cutoff land mid-character
    whenever the byte count isn't a multiple of 3 -- true here by
    construction -- which must not make the binary check misfire on an
    otherwise-ordinary text file."""
    marker = "zzqMARKERzz\n"
    char_count = (PREVIEW_MAX_BYTES // 3) + 100  # comfortably past the byte cutoff
    # The byte offset the hard cutoff lands at, measured from the start of
    # the (3-bytes-per-character) CJK run: not a multiple of 3, so the cut
    # is guaranteed to land mid-character rather than on a boundary.
    assert (PREVIEW_MAX_BYTES - len(marker.encode())) % 3 != 0
    (sample_tree / "cjk.txt").write_text(marker + "测" * char_count)
    fm = FileManager(sample_tree)
    _open_root_tab(fm)

    _activate_child(fm, "cjk.txt")

    screen = fm.app.screen()
    assert "zzqMARKERzz" in screen, f"large non-ASCII file misread as binary:\n{screen}"


def test_a_fifo_shows_a_placeholder_instead_of_blocking_on_open(sample_tree):
    """Only a regular file is safe to `open()` from inside the render path --
    a FIFO blocks until a writer shows up, which would freeze the whole app
    with no recovery."""
    os.mkfifo(sample_tree / "pipe")
    fm = FileManager(sample_tree)
    _open_root_tab(fm)

    _activate_child(fm, "pipe")

    assert "Not a regular file." in fm.app.screen()


def test_trashing_the_previewed_file_falls_back_to_the_placeholder(sample_tree):
    (sample_tree / "readme.txt").write_text("hello")
    fm = FileManager(sample_tree)
    _open_root_tab(fm)
    _activate_child(fm, "readme.txt")
    assert "hello" in fm.app.screen()

    fm.step(_key_event(DELETE_KEY))
    fm.step(_key_event(ENTER_KEY))  # confirm the trash

    screen = fm.app.screen()
    assert "No file selected." in screen
