"""F6c black-box coverage: real pointer-hover tooltips on the toolbar, the
tree and the details table -- `InteractionEngine::handle`'s hit-tested
`MouseEntered`/`MouseLeft` (quadraui#2122/#2125) drives this app's own
`self.waker.post_after`-delayed `show_tooltip`/`hide_tooltip` through
`self.actions` (see `app.py`'s "chrome: hover tooltips" section doc), not
the keyboard cursor or the last-clicked details row the old pseudo-hover
used.

A real `MouseMoved` at painted coordinates (`find_row`, same as
`tests/test_toolbar.py`/`tests/test_tree_click.py`) exercises the exact hit
test a real pointer would; a short, real `time.sleep` past a `tooltip_delay_ms`
this suite shortens through `fm.app.set_style`/`fm.refresh_tooltip_delay`
(this app's own hand-rolled timer is wall-clock-driven via
`QuiAppWaker.post_after`, unlike the host's own virtual-clock-driven
`HoverTooltipTracker` `quadraui-py/tests/test_tooltips.py` drives with
`set_test_clock_ms`) stands in for a user holding the pointer still."""

import time

from conftest import find_row as _find_row
from quadraui_files import FileManager
from quadraui_files.app import ENTER_KEY, _key_event

# Short enough that this suite stays fast, long enough to never flake against
# a loaded CI box's wall-clock scheduling.
DELAY_MS = 30
_SLEEP_S = (DELAY_MS + 70) / 1000

# Far outside every painted pane (toolbar, tree, details) at the widths this
# file's tests use -- moving here always counts as "left" whatever was hovered.
_OFF_X, _OFF_Y = 0.0, 1.0


def _move_to(fm: FileManager, x: float, y: float) -> None:
    """A real synthesized `MouseMoved` at painted coordinates `(x, y)` --
    the engine hit-tests it against the painted layout and synthesizes the
    `MouseEntered`/`MouseLeft` pair `_on_hover_entered`/`_on_hover_left`
    react to, same as a real pointer move would on every backend."""
    fm.app.push_event(
        {
            "MouseMoved": {
                "position": {"x": x, "y": y},
                "buttons": {"left": False, "right": False, "middle": False},
            }
        }
    )
    fm.app.step()


def _shorten_tooltip_delay(fm: FileManager) -> None:
    """Overrides `Style.tooltip_delay_ms` to `DELAY_MS` and makes `fm` pick
    it up -- see `FileManager.refresh_tooltip_delay`'s own doc for why both
    calls are needed."""
    fm.app.set_style({"tooltip_delay_ms": DELAY_MS})
    fm.refresh_tooltip_delay()


def _wait_past_the_delay_and_tick(fm: FileManager) -> None:
    """Real-sleeps past `DELAY_MS`, then ticks `fm.app` with nothing
    pushed, which drains whatever `self.waker.post_after` delivered since
    the last step (`QuiApp.step`'s own documented order) -- the "show"
    timer `_on_hover_entered` armed, if the pointer never moved off."""
    time.sleep(_SLEEP_S)
    fm.app.step()


def _open_root_tab(fm: FileManager) -> None:
    """Opens the root folder (the initial cursor) as a details tab -- same
    `ENTER_KEY` shortcut `tests/test_chrome.py`'s own `_open_root_tab` uses."""
    fm.step(_key_event(ENTER_KEY))


# --- toolbar button ----------------------------------------------------------


def test_hovering_a_toolbar_button_shows_its_tooltip_after_the_delay(sample_tree):
    fm = FileManager(sample_tree, width=160, height=30)
    _shorten_tooltip_delay(fm)

    x, y = _find_row(fm, "Expand")
    _move_to(fm, x, y)
    assert "Expand the cursored folder" not in fm.app.screen(), (
        "landing on the button must not show the tooltip before the delay elapses"
    )

    _wait_past_the_delay_and_tick(fm)
    assert "Expand the cursored folder" in fm.app.screen()

    _move_to(fm, _OFF_X, _OFF_Y)
    assert "Expand the cursored folder" not in fm.app.screen(), (
        "leaving the button must hide the tooltip immediately, no delay"
    )


# --- tree row -----------------------------------------------------------------


def test_hovering_a_tree_row_shows_its_full_path_tooltip(sample_tree):
    fm = FileManager(sample_tree, width=160, height=30)
    _shorten_tooltip_delay(fm)

    x, y = _find_row(fm, "alpha")
    _move_to(fm, x, y)
    alpha_path = str(sample_tree / "alpha")
    assert alpha_path not in fm.app.screen()

    _wait_past_the_delay_and_tick(fm)
    assert alpha_path in fm.app.screen()

    _move_to(fm, _OFF_X, _OFF_Y)
    assert alpha_path not in fm.app.screen()


def test_moving_from_one_tree_row_to_another_replaces_the_tooltip_text(sample_tree):
    """Row "alpha" to row "beta" within the same tree: the engine
    synthesizes `MouseLeft`/`MouseEntered` around the hit-detail change
    (same `WidgetId`, different `TreeRow{row}`) exactly as it would for two
    different widgets, so this must behave like any other hover change --
    the old tooltip gone immediately, the new one replacing it, never both
    at once."""
    fm = FileManager(sample_tree, width=160, height=30)
    _shorten_tooltip_delay(fm)

    alpha_x, alpha_y = _find_row(fm, "alpha")
    _move_to(fm, alpha_x, alpha_y)
    _wait_past_the_delay_and_tick(fm)
    alpha_path = str(sample_tree / "alpha")
    beta_path = str(sample_tree / "beta")
    assert alpha_path in fm.app.screen()
    assert beta_path not in fm.app.screen()

    beta_x, beta_y = _find_row(fm, "beta")
    _move_to(fm, beta_x, beta_y)
    assert alpha_path not in fm.app.screen(), (
        "moving onto a different row must hide the old tooltip right away, not stack it"
    )
    assert beta_path not in fm.app.screen(), "the new row's tooltip is still delayed"

    _wait_past_the_delay_and_tick(fm)
    assert beta_path in fm.app.screen()
    assert alpha_path not in fm.app.screen()


# --- details row --------------------------------------------------------------


def test_hovering_a_details_row_shows_path_size_and_modified_time(sample_tree):
    fm = FileManager(sample_tree, width=160, height=30)
    _shorten_tooltip_delay(fm)
    _open_root_tab(fm)

    x, y = _find_row(fm, "readme.txt")
    _move_to(fm, x, y)
    readme_path = str(sample_tree / "readme.txt")
    assert readme_path not in fm.app.screen()

    _wait_past_the_delay_and_tick(fm)
    screen = fm.app.screen()
    assert readme_path in screen
    assert "B" in screen  # the human-readable size ("5 B")

    _move_to(fm, _OFF_X, _OFF_Y)
    assert readme_path not in fm.app.screen()
