"""T4 headless coverage: window title / dirty-dot / tray / cursor (C13).

The installed quadraui-py has no Python-callable binding for
`WindowControl::set_title`/`set_document_edited`/`set_represented_filename`,
`TrayService`, or `PointerCursor::set_cursor` yet -- see `app.py`'s own
"native chrome" doc, right above `FileManager`. Nothing in this app calls
into any of them today, so there is nothing to drive through `FileManager`
here. What *is* already reachable headlessly is `QuiApp.backend_caps()`,
which reports whether the live backend has the underlying capability; these
tests pin down today's no-op state as a regression check (that query never
raises, and the TUI backend's own caps for `tray`/`pointer_cursor` are
`False`) so the gap -- and the day the binding lands and these start
failing because there is finally something to wire up -- is visible here
rather than only in a PR description.
"""

from quadraui_files import FileManager


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


def test_quiapp_has_no_window_tray_or_cursor_action_yet(sample_tree):
    """Documents the exact upstream gap: neither `QuiApp` itself nor the
    handler-safe `QuiApp.actions()` handle carries a window-title, tray, or
    pointer-cursor setter today, so `FileManager` has nothing it could call
    to implement C13 without quadraui-py growing one."""
    fm = FileManager(sample_tree, width=60, height=20)
    for name in ("set_title", "set_document_edited", "set_represented_filename", "set_cursor", "tray"):
        assert not hasattr(fm.app, name), f"QuiApp grew {name!r} -- C13 may now be implementable"
        assert not hasattr(fm.actions, name), f"QuiApp.actions() grew {name!r} -- C13 may now be implementable"
