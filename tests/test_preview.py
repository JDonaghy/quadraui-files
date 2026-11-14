"""T3 black-box tests: the read-only preview pane -- selecting a file in a
details table shows its content (or, for a binary file, a size/type
placeholder) in the third (preview) region of the frame, driven headlessly
through `FileManager.step` exactly like the other feature tranches' tests."""

import os

from conftest import activate_child as _activate_child

from quadraui_files import FileManager
from quadraui_files.app import DELETE_KEY, ENTER_KEY, PREVIEW_MAX_BYTES, _key_event


def _open_root_tab(fm: FileManager) -> None:
    fm.step(_key_event(ENTER_KEY))


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
