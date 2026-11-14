"""T4b headless coverage: window title / dirty-dot / tray / cursor (C13).

`quadraui-py` exposes `WindowControl::set_title`/`set_document_edited`/
`set_represented_filename`, `TrayService`, and `Backend::set_cursor` on both
`QuiApp` and the handler-safe `QuiApp.actions()` handle, genuinely backed by
a real GTK/AppKit/Win32 `run_native()` window. This suite drives the
headless `TuiBackend` instead, which only ever implements `set_title` (OSC
0/2) and `set_cursor` (always reports `False`, no native pointer concept) --
see `app.py`'s "native chrome" doc, right above `FileManager`. Every other
call (`set_document_edited`/`set_represented_filename`/the whole tray
surface) is gated on `native_window_chrome`/`native_tray`, two opt-in flags
`FileManager` never sets itself -- only `cli.py`/`app.py`'s own `__main__`
sets them, and only right before a `run_native()` call, based on which
native backend (if any) the running build actually has. Both default
`False`, so this suite's `FileManager` instances never attempt any of those
calls -- the acceptance bar here is "never raises" plus the title-tracking
and divider-drag-cursor behavior that *is* real on every backend, TUI
included. The *visible* effect of a real window title/dirty-dot/tray
icon/pointer glyph needs a `run_native` window and a human at a real
desktop session -- see this PR's description for the manual verification
story.
"""

from pathlib import Path

import pytest

from quadraui_files import FileManager
from quadraui_files.app import TRAY_MENU_OPEN_HOME_ID, TRAY_MENU_QUIT_ID, _key_event, _window_title

F2_KEY = {"Named": {"F": 2}}
ESCAPE_KEY = {"Named": "Escape"}
DOWN_KEY = {"Named": "Down"}
ENTER_KEY = {"Named": "Enter"}


class _ActionSpy:
    """Wraps a real `QuiAppActions` handle, recording every `set_title`/
    `set_cursor` call before delegating to it, so a test can pin down that
    the call genuinely happened rather than only asserting on this app's own
    cache of the last value it meant to send (see `app.py`'s `window_title`
    property and `_title_cache`) -- a cache that would stay correct even if
    the call it is supposed to mirror were deleted."""

    def __init__(self, inner):
        self._inner = inner
        self.titles: list[str] = []
        self.cursors: list[str] = []

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def set_title(self, title: str) -> None:
        self.titles.append(title)
        self._inner.set_title(title)

    def set_cursor(self, shape: str) -> None:
        self.cursors.append(shape)
        self._inner.set_cursor(shape)


def test_backend_caps_reports_the_c13_capability_names_without_raising(sample_tree):
    """A caps query is always safe to make from `_render`/`_handle` (unlike
    the mutating calls C13 would need): it never raises, on any backend."""
    fm = FileManager(sample_tree, width=60, height=20)
    caps = fm.app.backend_caps()
    assert {"window_control", "tray", "pointer_cursor"} <= caps.keys()


def test_tray_and_pointer_cursor_are_inert_on_the_tui_backend(sample_tree):
    """The headless/TUI backend this suite drives has no tray and no
    pointer-cursor control -- a tray icon/menu or a divider-drag cursor
    swap is correctly a no-op here. `FileManager` never attempts either on
    this backend regardless: `native_tray` defaults `False` (see
    `test_native_window_chrome_and_tray_default_off_on_a_plain_filemanager`),
    so nothing but the always-safe `set_cursor` call ever reaches it."""
    fm = FileManager(sample_tree, width=60, height=20)
    caps = fm.app.backend_caps()
    assert caps["tray"] is False
    assert caps["pointer_cursor"] is False


def test_native_window_chrome_and_tray_default_off_on_a_plain_filemanager(sample_tree):
    """Both opt-in flags start `False` -- only `cli.py`/`app.py`'s own
    `__main__` ever flips either, and only right before a `run_native()`
    call."""
    fm = FileManager(sample_tree, width=60, height=20)
    assert fm.native_window_chrome is False
    assert fm.native_tray is False


def test_window_title_tracks_the_root_folder_at_construction(sample_tree):
    """Set directly on `self.app` from `__init__` (top-level code, same as
    `set_theme`/`register_accelerator`) -- no event needed to see it. The
    public `window_title` property mirrors the same cache a `run_native()`
    caller reads to derive its own launch `title=` (see `cli.py`)."""
    fm = FileManager(sample_tree, width=60, height=20)
    assert fm.window_title == _window_title(sample_tree)
    assert sample_tree.name in fm.window_title
    assert fm.window_title.endswith("quadraui-files")


def test_window_title_tracks_navigation_into_a_folder(sample_tree):
    """Moving the cursor onto a different folder genuinely queues a
    `set_title` call -- not just updates this app's own cache of it, which
    a spy around `fm.actions` catches even if the real call were deleted."""
    fm = FileManager(sample_tree, width=60, height=20)
    fm.live_title = True  # what `cli.py` sets before `run_tui`/`run_native`
    spy = _ActionSpy(fm.actions)
    fm.actions = spy

    fm.step(_key_event(DOWN_KEY))  # select "alpha", the first subfolder
    fm.step(_key_event(ENTER_KEY))  # open it in place

    assert fm.cursor.name == "alpha"
    assert "alpha" in fm.window_title
    assert fm.window_title == _window_title(fm.cursor.path)
    assert spy.titles == [fm.window_title]


def test_a_headless_run_never_writes_a_title_escape_to_stdout(sample_tree, capfd):
    """With no terminal or window to title (Python driving `step`, piped
    output), construction and navigation keep the title cache current but
    send nothing: the TUI backend's `set_title` would write a raw OSC escape
    into the program's output."""
    fm = FileManager(sample_tree, width=60, height=20)
    spy = _ActionSpy(fm.actions)
    fm.actions = spy

    fm.step(_key_event(DOWN_KEY))
    fm.step(_key_event(ENTER_KEY))  # into "alpha"

    assert "alpha" in fm.window_title
    assert spy.titles == []
    assert "\x1b]" not in capfd.readouterr().out


def test_opening_and_cancelling_a_rename_never_raises_on_the_tui_backend(sample_tree):
    """`set_document_edited` raises `InternalError` on every backend but a
    macOS `run_native` window (see `native_window_chrome`'s own doc) --
    `native_window_chrome` defaults `False`, so a plain `FileManager` never
    even attempts it, on this or any other backend `_start_rename`/
    `_commit_edit`/`_cancel_edit` might run on."""
    fm = FileManager(sample_tree, width=60, height=20)
    assert fm.native_window_chrome is False

    fm.step(_key_event(DOWN_KEY))  # cursor onto "alpha" -- the root itself can't be renamed
    fm.step(_key_event(F2_KEY))
    assert fm.edit_mode == "rename"

    fm.step(_key_event(ESCAPE_KEY))  # cancel
    assert fm.edit_mode is None


def test_tray_menu_and_icon_setup_never_raises_on_the_tui_backend(sample_tree):
    """`native_tray` defaults `False`, so `_prime_native_chrome` (run once
    from the first `_handle` dispatch) skips the tray setup outright, on
    both construction and the first real event -- either way must never
    raise."""
    fm = FileManager(sample_tree, width=60, height=20)
    assert fm.native_tray is False
    fm.step(_key_event(DOWN_KEY))
    assert fm._native_chrome_primed is True


def test_tray_open_home_activation_queues_open_path_on_the_users_home(sample_tree):
    """(#21) The event every backend's `TrayService::set_menu`-attached menu
    actually emits for a click is `{"ContextMenuItemActivated": <item id>}`
    -- the same shape a right-click context menu's selection produces, and
    the one `_on_menu_item` matches on (see its own doc). Pushing it
    directly, the way the real AppKit/GTK/Win32 event-queue drain would
    once it reaches `AppLogic::handle`, is this app's whole share of C13's
    click-to-effect path: whether that event actually reaches here on a
    real native window is a `quadraui`-side concern (binding-core's
    `InteractionEngine`/each backend's queue-drain timing), not this
    app's. `_NoDesktopActions` (autouse, `conftest.py`) records `open_path`
    instead of truly opening Finder/Explorer/a file manager for every test
    run."""
    fm = FileManager(sample_tree, width=60, height=20)

    fm.step({"ContextMenuItemActivated": TRAY_MENU_OPEN_HOME_ID})

    assert fm.actions.opened == [str(Path.home())]
    assert fm._quit_requested is False


def test_tray_quit_activation_sets_the_quit_requested_flag(sample_tree):
    """`_on_menu_item` cannot raise `_Quit` itself (it has no idea
    `_wrap_quit` exists -- see that function's own doc) -- it just records
    intent on `fm._quit_requested`, the flag `_wrap_quit`'s wrapper checks
    after every dispatch to actually unwind `run_tui()`/`run_native()`.
    Same `ContextMenuItemActivated` shape as the `Open home` item above,
    just the `Quit` item's id."""
    fm = FileManager(sample_tree, width=60, height=20)

    fm.step({"ContextMenuItemActivated": TRAY_MENU_QUIT_ID})

    assert fm._quit_requested is True
    assert fm.actions.opened == []


def test_divider_drag_sets_then_restores_the_resize_cursor(sample_tree):
    """A `SplitDividerDragged` on one of the two resizable splits queues the
    `"col_resize"` pointer shape; whatever event ends the drag (`MouseUp`
    here) restores `"default"` -- both genuinely queued, caught by the spy,
    not merely "doesn't raise" (`QuiAppActions.set_cursor` would raise
    `InvalidDescriptorError` synchronously for an unrecognised shape name,
    so a bad shape here would already fail the `fm.step` calls themselves;
    this additionally pins down that a restore actually happens)."""
    fm = FileManager(sample_tree, width=60, height=20)
    spy = _ActionSpy(fm.actions)
    fm.actions = spy

    fm.step({
        "SplitDividerDragged": {"tree": "fm:split", "split_index": 0, "new_ratio": 0.4},
    })
    assert fm.ratio == pytest.approx(0.4)  # decoded through an f32 round trip
    assert spy.cursors == ["col_resize"]

    fm.step({"MouseUp": {"button": "Left", "position": {"x": 1, "y": 1}}})
    assert spy.cursors == ["col_resize", "default"]
