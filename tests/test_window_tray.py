"""T4b headless coverage: window title / dirty-dot / tray / cursor (C13).

`quadraui-py` now exposes `WindowControl::set_title`/`set_document_edited`/
`set_represented_filename`, `TrayService`, and `Backend::set_cursor` on both
`QuiApp` and the handler-safe `QuiApp.actions()` handle. Every method
resolves off this app's own headless `TuiBackend`, though -- see `app.py`'s
"native chrome" doc, right above `FileManager` -- which genuinely implements
only `set_title` (OSC 0/2) and `set_cursor` (always reports `False`, no
native pointer concept); every other method, and the whole tray surface,
stay structurally unreachable there. `QuiApp.backend_caps()` is what this
app reads to decide what's safe to attempt; these tests pin that down
(never raises, and the TUI backend's own `tray`/`pointer_cursor` caps are
`False`) alongside the title-tracking and never-raises behavior `app.py`
actually drives through `FileManager`. The *visible* effect of a real
window title/dirty-dot/tray icon/pointer glyph needs a `run_native` window
and a human at a real desktop session -- see this PR's description for the
manual macOS verification story.
"""

from quadraui_files import FileManager
from quadraui_files.app import _key_event, _window_title

F2_KEY = {"Named": {"F": 2}}
ESCAPE_KEY = {"Named": "Escape"}
DOWN_KEY = {"Named": "Down"}


def test_backend_caps_reports_the_c13_capability_names_without_raising(sample_tree):
    """A caps query is always safe to make from `_render`/`_handle` (unlike
    the mutating calls C13 would need): it never raises, on any backend."""
    fm = FileManager(sample_tree, width=60, height=20)
    caps = fm.app.backend_caps()
    assert {"window_control", "tray", "pointer_cursor"} <= caps.keys()


def test_tray_and_pointer_cursor_are_inert_on_the_tui_backend(sample_tree):
    """The headless/TUI backend this suite drives has no tray and no
    pointer-cursor control -- a tray icon/menu or a divider-drag cursor
    swap is correctly a no-op here, caps-gated, not something this app
    should attempt to call."""
    fm = FileManager(sample_tree, width=60, height=20)
    caps = fm.app.backend_caps()
    assert caps["tray"] is False
    assert caps["pointer_cursor"] is False


def test_window_title_tracks_the_root_folder_at_construction(sample_tree):
    """Set directly on `self.app` from `__init__` (top-level code, same as
    `set_theme`/`register_accelerator`) -- no event needed to see it."""
    fm = FileManager(sample_tree, width=60, height=20)
    assert fm._window_title == _window_title(sample_tree)
    assert sample_tree.name in fm._window_title
    assert fm._window_title.endswith("quadraui-files")


def test_window_title_tracks_navigation_into_a_folder(sample_tree):
    """Moving the cursor onto a different folder queues a `set_title` whose
    text this app caches on `_window_title` -- the only way to observe an
    OSC title escape sequence through this headless backend (see the
    module doc)."""
    fm = FileManager(sample_tree, width=60, height=20)
    fm.step(_key_event(DOWN_KEY))  # cursor onto "alpha", the first subfolder
    assert fm.cursor.name == "alpha"
    assert "alpha" in fm._window_title
    assert fm._window_title == _window_title(fm.cursor.path)


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


def test_tray_menu_and_icon_setup_never_raises_at_construction(sample_tree):
    """`backend_caps()["tray"]` is `False` on this backend (see above), so
    `__init__`'s tray setup is skipped outright -- constructing a
    `FileManager` must never raise either way."""
    fm = FileManager(sample_tree, width=60, height=20)
    assert fm.app.backend_caps()["tray"] is False
