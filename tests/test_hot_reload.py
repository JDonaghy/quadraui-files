"""Black-box coverage for `FileManager`'s hot reload (`--reload`): the running
app re-imports its watched modules when their source files change, keeps the
session's state across the swap, survives a broken edit with the last good
code, and surfaces a failed reload in the status bar.

The watcher/rebind machinery is quadraui's own (`quadraui.app.hot_reload`,
exercised exhaustively by quadraui-py's suite); what these tests pin down is
the wiring this app adds around it: the wake event the watcher thread posts,
the state-preserving `__class__` swap, the rollback, and the status-bar
surface. All reloads are synchronous (`interval=None`) -- the thread itself
only posts the wake event driven here. The app module's own file is touched
with `os.utime` only -- a reload trigger, never a content change.
"""

import importlib
import os
import sys
import textwrap
import time
import uuid
from pathlib import Path

import pytest

import quadraui_files.app as app_module
from quadraui_files import FileManager
from quadraui_files.app import DOWN_KEY, ENTER_KEY, HOT_RELOAD_WAKE, _key_event


def _touch(path: Path) -> None:
    """Bump a file's mtime into the future without changing its content, so
    the watcher's (mtime, size) stamp reports a change no matter the
    filesystem's timestamp granularity or a fast follow-up edit."""
    stamp = max(time.time(), path.stat().st_mtime) + 10
    os.utime(path, (stamp, stamp))


class _TempModule:
    """A throwaway importable module written under `tmp_path` -- the way to
    put a genuinely broken (or edited) module through the watcher without
    touching this repo's own sources."""

    def __init__(self, tmp_path: Path, source: str):
        self.name = "fm_hot_reload_fixture_" + uuid.uuid4().hex[:8]
        self.path = tmp_path / f"{self.name}.py"
        self.path.write_text(textwrap.dedent(source))
        # `importlib.reload` re-resolves the module's spec, so its directory
        # must stay importable for the whole test. The name is unique, so the
        # stale entry is harmless.
        sys.path.insert(0, str(tmp_path))
        self.module = importlib.import_module(self.name)

    def write(self, source: str) -> None:
        self.path.write_text(textwrap.dedent(source))
        _touch(self.path)


@pytest.fixture
def fm(sample_tree):
    manager = FileManager(sample_tree)
    yield manager
    manager.disable_hot_reload()  # no watcher thread outlives its test


def test_no_reload_until_a_source_file_changes(fm):
    fm.enable_hot_reload(interval=None)
    assert fm.reload_if_changed() is False
    assert fm.reload_count == 0


def test_reimport_keeps_the_session_and_rebinds_the_class(fm):
    fm.enable_hot_reload(interval=None)
    fm.step(_key_event(ENTER_KEY))  # open the root as a tab (session state)
    old_class = type(fm)

    _touch(Path(app_module.__file__))

    assert fm.reload_if_changed() is True
    assert fm.reload_error is None
    assert type(fm) is not old_class, "the class never swapped to the reloaded one"
    assert [n.name for n in fm.open] == [fm.root.name], "open tabs lost"
    assert fm.cursor is fm.root, "cursor lost"
    fm.step(_key_event(DOWN_KEY))  # the reloaded code drives the app fine
    assert fm.cursor.name == "alpha"


def test_a_broken_edit_keeps_the_last_good_code_and_surfaces_the_error(fm, tmp_path):
    helper = _TempModule(tmp_path, "VALUE = 1\n")
    fm.enable_hot_reload(app_module, helper.module, interval=None)
    fm.step(_key_event(ENTER_KEY))

    helper.write("def broken(:\n")

    assert fm.reload_if_changed() is False
    assert type(fm.reload_error).__name__ == "SyntaxError"
    assert "reload failed" in fm.app.screen(), "status bar never showed the failure"
    fm.step(_key_event(DOWN_KEY))  # the last good code still drives
    assert fm.cursor.name == "alpha"

    helper.write("VALUE = 2\n")  # a later good save clears the error
    assert fm.reload_if_changed() is True
    assert fm.reload_error is None


def test_the_watcher_threads_wake_event_triggers_the_reload(fm):
    fm.enable_hot_reload(interval=None)  # the wake path, minus the thread
    _touch(Path(app_module.__file__))

    # A `User` payload is in-process-only and never survives the wire
    # (`push_event` rejects it) -- it reaches the loop through the waker,
    # exactly as the watcher thread posts it.
    fm.app.waker().post(HOT_RELOAD_WAKE)
    fm.app.step()

    assert fm.reload_count == 1
    assert fm.reload_error is None


def test_a_first_render_that_raises_rolls_back_to_the_last_good_code(fm):
    fm.enable_hot_reload(interval=None)
    old_class = type(fm)
    _touch(Path(app_module.__file__))
    assert fm.reload() is True  # class swapped; rollback armed for one frame

    # Break the reloaded class's render. The mutation dies with the rollback:
    # the class object it lands on is dropped from the module namespace, and
    # `fm` goes back to `old_class`.
    broken_class = type(fm)
    broken_class._render = lambda self: 1 / 0
    fm.step(_key_event(DOWN_KEY))  # the first frame with the new code raises

    assert type(fm.reload_error).__name__ == "ZeroDivisionError"
    assert fm.reload_count == 0
    assert type(fm) is old_class
    fm.step(_key_event(ENTER_KEY))  # the rolled-back code still drives
    assert fm.open and fm.app.screen(), "the rolled-back code no longer drives the app"


def test_the_watcher_thread_notices_an_edit_and_the_pump_reloads(fm, tmp_path):
    """The real `--reload` shape: a background thread notices the file change
    and the next pump of the event loop does the reload. Polls with a
    deadline instead of sleeping a fixed interval, so it is no flakier than
    the watcher thread itself."""
    helper = _TempModule(tmp_path, "VALUE = 1\n")
    fm.enable_hot_reload(helper.module, interval=0.05)
    helper.write("VALUE = 2\n")

    deadline = time.time() + 3
    while fm.reload_count == 0:
        assert time.time() < deadline, "watcher thread never posted its wake"
        fm.app.step()  # each pump drains waker-posted events
        time.sleep(0.05)

    assert fm.reload_error is None
    assert helper.module.VALUE == 2


def test_enable_disable_cycle_starts_and_stops_the_watcher_thread(fm):
    fm.enable_hot_reload(interval=0.05)
    assert fm._hr_thread is not None
    fm.disable_hot_reload()
    assert fm._hr_thread is None
