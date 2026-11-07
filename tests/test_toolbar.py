"""F6 black-box coverage: the toolbar's buttons are real clickable actions
-- a `MouseDown`/`MouseUp` on one resolves (via `quadraui-binding-core`'s
`SidebarPanelHit::ToolbarButton` hit-test, the same path on every backend)
to a semantic `Toolbar`/`ButtonClicked` event, which `_dispatch`'s own
`Toolbar` branch runs through `_on_toolbar_button` -- the exact handler call
its keyboard equivalent runs. No backend branches on this: the TUI
backend's own `Toolbar` painter (a `[ icon label (key) ]` cell strip, per
that primitive's documented "Backend contract") is what gives the TUI its
compact textual key legend, not a separate code path here."""

from conftest import click as _click
from conftest import find_row as _find_row
from quadraui_files import FileManager
from quadraui_files.app import DOWN_KEY, _key_event


def test_toolbar_preview_click_toggles_the_preview_pane(sample_tree):
    fm = FileManager(sample_tree, width=160, height=20)
    assert fm.preview_visible is True

    x, y = _find_row(fm, "Preview (p)")
    _click(fm, x, y)

    assert fm.preview_visible is False, (
        "a click on the toolbar's Preview button must run the same "
        "`_toggle_preview` call pressing `p` does"
    )

    # Click again: the same button toggles it back, same as a second `p`.
    x, y = _find_row(fm, "Preview (p)")
    _click(fm, x, y)
    assert fm.preview_visible is True


def test_toolbar_refresh_click_reloads_the_cursored_folder(sample_tree):
    fm = FileManager(sample_tree, width=160, height=20)
    fm.message = ""

    x, y = _find_row(fm, "Refresh (r)")
    _click(fm, x, y)

    assert fm.message == f"reloaded {fm.cursor.name}", (
        "a click on the toolbar's Refresh button must run the same "
        "`_refresh` call pressing `r` does"
    )


def test_toolbar_delete_click_opens_the_danger_confirm_dialog(sample_tree):
    """The toolbar's "Move to Trash" button is itself `ButtonVariant.Danger`
    (see `TOOLBAR`'s own doc), and a click on it must reach the same
    confirm dialog `Delete`/the Menu action does -- itself carrying a
    `ButtonVariant.Danger` `spec` (see `_request_delete`'s own doc)."""
    fm = FileManager(sample_tree, width=160, height=20)
    fm.step(_key_event(DOWN_KEY))  # off the root -- root can't be trashed

    x, y = _find_row(fm, "Move to Trash (Del)")
    _click(fm, x, y)

    assert fm._delete_target is fm.cursor, (
        "a click on the toolbar's Move to Trash button must put up the "
        "same confirm dialog `Delete`/`_request_delete` does"
    )
