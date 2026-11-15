"""Black-box coverage for live filesystem watching: an external change to the
active tab's own folder (another process adding, removing, or rewriting an
entry -- Finder, a terminal, `rm`/`mv`, ...) shows up without the user
pressing `r`.

Mirrors `test_hot_reload.py`'s shape: `enable_fs_watch(interval=None)` is the
synchronous path exercised directly here, and a couple of tests cover the
real background-thread wiring (`interval=...`) and the wake event it posts
through the waker. The watcher itself (`_FolderSnapshot`) only stats one
folder's own listing -- no OS-level watcher, no new dependency."""

import os
import shutil
import time
from pathlib import Path

import pytest

from quadraui_files import FileManager
from quadraui_files.app import DOWN_KEY, ENTER_KEY, FS_WATCH_WAKE, LEFT_KEY, _key_event


def _touch(path: Path) -> None:
    """Bump a file's mtime into the future without changing its content, so
    the watcher's (mtime, size) stamp reports a change no matter the
    filesystem's timestamp granularity or a fast follow-up edit."""
    stamp = max(time.time(), path.stat().st_mtime) + 10
    os.utime(path, (stamp, stamp))


@pytest.fixture
def fm(sample_tree):
    manager = FileManager(sample_tree, width=120, height=30)
    yield manager
    manager.disable_fs_watch()  # no watcher thread outlives its test


def test_no_change_until_the_active_folder_actually_changes(fm):
    fm.enable_fs_watch(interval=None)
    assert fm.fs_watch_if_changed() is False


def test_an_external_file_added_to_the_active_folder_is_picked_up(fm, sample_tree):
    fm.enable_fs_watch(interval=None)

    (sample_tree / "new_from_outside.txt").write_text("hi")

    assert fm.fs_watch_if_changed() is True
    assert "new_from_outside.txt" in fm.app.screen()


def test_an_external_delete_is_picked_up_and_clears_a_stale_selection(fm, sample_tree):
    fm.enable_fs_watch(interval=None)
    fm.step(_key_event(DOWN_KEY))  # select the first row ("alpha/")
    assert fm.selected_file is not None

    shutil.rmtree(sample_tree / "alpha")

    assert fm.fs_watch_if_changed() is True
    assert "alpha" not in [n.name for n in fm.cursor.children]
    assert fm.selected_file is None, "the selection survived the folder it pointed at being deleted"


def test_an_external_content_rewrite_is_also_a_change(fm, sample_tree):
    fm.enable_fs_watch(interval=None)
    _touch(sample_tree / "readme.txt")

    assert fm.fs_watch_if_changed() is True
    assert fm.cursor.load_error is False
    screen = fm.app.screen()
    assert "readme.txt" in screen
    assert "reloaded" in fm.message


def test_the_watcher_threads_wake_event_triggers_a_refresh(fm, sample_tree):
    fm.enable_fs_watch(interval=None)  # the wake path, minus the thread
    (sample_tree / "new_from_outside.txt").write_text("hi")

    # A `User` payload is in-process-only (`push_event` rejects it); it
    # reaches the loop through the waker, exactly as the watcher thread
    # posts it.
    fm.app.waker().post(FS_WATCH_WAKE)
    fm.app.step()

    assert "new_from_outside.txt" in fm.app.screen()


def test_the_watcher_thread_notices_an_external_change_and_the_pump_refreshes(fm, sample_tree):
    fm.enable_fs_watch(interval=0.05)

    (sample_tree / "new_from_outside.txt").write_text("hi")

    deadline = time.time() + 3
    while "new_from_outside.txt" not in fm.app.screen():
        assert time.time() < deadline, "watcher thread never posted its wake"
        fm.app.step()  # each pump drains waker-posted events
        time.sleep(0.05)


def test_switching_tabs_moves_the_watch_to_the_new_active_folder(fm, sample_tree):
    fm.enable_fs_watch(interval=None)
    fm.step(_key_event(DOWN_KEY))   # select "alpha/"
    fm.step(_key_event(ENTER_KEY))  # drill into it: cursor.path is now .../alpha
    assert fm.cursor.path == sample_tree / "alpha"

    # The very first check against the newly-active folder always reports a
    # change (it hasn't been baselined yet) -- consume that one first.
    fm.fs_watch_if_changed()

    (sample_tree / "alpha" / "added_after_drilling_in.txt").write_text("hi")
    assert fm.fs_watch_if_changed() is True
    assert "added_after_drilling_in.txt" in fm.app.screen()


def test_left_goes_up_and_the_watch_does_not_clear_that_selection(sample_tree):
    """A navigation (Up/Back/breadcrumb) pre-selects the folder just left --
    see `tests/test_navigation.py`'s own coverage of that. With the watch
    running, the first tick against the newly-active folder must not read
    as "changed" (it was never watched before) and silently drop that
    selection via a spurious `_refresh()`."""
    fm = FileManager(sample_tree / "alpha", width=120, height=30)
    fm.enable_fs_watch(interval=None)

    fm.step(_key_event(LEFT_KEY))

    assert fm.cursor.path == sample_tree
    assert fm.selected_file is not None and fm.selected_file.name == "alpha"

    assert fm.fs_watch_if_changed() is False
    assert fm.selected_file is not None and fm.selected_file.name == "alpha"


def test_enable_disable_cycle_starts_and_stops_the_watcher_thread(fm):
    fm.enable_fs_watch(interval=0.05)
    assert fm._fw_thread is not None
    fm.disable_fs_watch()
    assert fm._fw_thread is None


def test_fs_watch_if_changed_without_enabling_first_raises(fm):
    with pytest.raises(RuntimeError):
        fm.fs_watch_if_changed()
