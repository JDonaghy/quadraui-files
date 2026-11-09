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

import quadraui

from conftest import find_row as _find_row
from quadraui_files import app as _app_module
from quadraui_files import cli as _cli_module
from quadraui_files import FileManager
from quadraui_files.app import ENTER_KEY, _key_event

# Short enough that this suite stays fast, long enough to never flake against
# a loaded CI box's wall-clock scheduling.
DELAY_MS = 30
_SLEEP_S = (DELAY_MS + 70) / 1000

# The status bar's own row -- every test in this file builds `fm` with
# `height=30`, so row 29 is the last painted row, below the tree/details
# body band and the outer split's own divider. Nothing hit-tested there
# resolves to a `_hover_target_for` target, so moving here always counts as
# "left" whatever was hovered, through the plain `_on_hover_left` branch
# rather than `_on_hover_entered`'s own unconditional hide (unlike `(0, 1)`,
# the first body row, which still sits inside the tree/split's own hit area).
_OFF_X, _OFF_Y = 0.0, 29.0


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


def _sleep_ms(ms: float) -> None:
    time.sleep(ms / 1000)


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


def test_hovering_a_tree_rows_chevron_shows_the_same_rows_tooltip(sample_tree):
    """`_hover_target_for` folds `tree_chevron` into the same `"tree"`
    target as `tree_row` -- hovering the row's own expand/collapse
    triangle must show that row's tooltip too, not be treated as a hit
    this app has no tooltip for."""
    fm = FileManager(sample_tree, width=160, height=30)
    _shorten_tooltip_delay(fm)

    _, y = _find_row(fm, "alpha")
    line = fm.app.screen().splitlines()[int(y)]
    chevron_x = next(i for i, ch in enumerate(line) if ch in "▾▸")

    _move_to(fm, float(chevron_x), y)
    _wait_past_the_delay_and_tick(fm)
    assert str(sample_tree / "alpha") in fm.app.screen()


def test_continued_movement_within_a_tree_row_re_arms_the_auto_dismiss_window(sample_tree, monkeypatch):
    """`_on_hover_moved` re-arms the dismiss timer while a tooltip is
    already showing, so VS Code's "about 5s of no movement" contract is
    measured from the *last* move, not from when the tooltip first
    appeared -- wiggling the pointer inside the same row must not dismiss
    it on the original schedule."""
    dismiss_ms = 200
    monkeypatch.setattr(_app_module, "_TOOLTIP_AUTO_DISMISS_MS", dismiss_ms)
    fm = FileManager(sample_tree, width=160, height=30)
    _shorten_tooltip_delay(fm)

    x, y = _find_row(fm, "alpha")
    _move_to(fm, x, y)
    _wait_past_the_delay_and_tick(fm)
    alpha_path = str(sample_tree / "alpha")
    assert alpha_path in fm.app.screen()

    _sleep_ms(dismiss_ms * 0.75)
    _move_to(fm, x + 1, y)  # still inside the same row -- re-arms the window
    _sleep_ms(dismiss_ms * 0.75)
    fm.app.step()
    assert alpha_path in fm.app.screen(), (
        "continued movement inside the same row must re-arm the dismiss window"
    )

    _sleep_ms(dismiss_ms * 0.75)
    fm.app.step()
    assert alpha_path not in fm.app.screen()


def test_hover_tooltips_disabled_flag_suppresses_the_delayed_show(sample_tree):
    """`hover_tooltips_enabled` is a plain opt-out any caller can flip --
    `FileManager` itself never does, and neither does `cli.py` anymore (see
    the "chrome: hover tooltips" section doc). With the flag off,
    `_on_hover_entered` must not arm a show timer at all -- waiting past
    the delay must never show a tooltip."""
    fm = FileManager(sample_tree, width=160, height=30)
    _shorten_tooltip_delay(fm)
    fm.hover_tooltips_enabled = False

    x, y = _find_row(fm, "alpha")
    _move_to(fm, x, y)
    _wait_past_the_delay_and_tick(fm)
    assert str(sample_tree / "alpha") not in fm.app.screen()


def test_cli_native_branch_leaves_tooltips_enabled_and_a_hover_still_fires(sample_tree, monkeypatch):
    """`cli.main`'s `--native` arm sets `native_window_chrome`/`native_tray`
    right before the one call that opens a real window, but, since
    `run_native` now swaps `QuiAppWaker`'s delivery onto the live native
    backend (quadraui#2278), it no longer flips `hover_tooltips_enabled`
    off first -- that opt-out line is gone from both `cli.py` and this
    module's own `__main__`.

    A real native window/display isn't available headlessly, so this
    stubs only `QuiApp.run_native` itself (not `FileManager` or the rest
    of `cli.main`'s own code) to drive the exact same `push_event`/`step`
    hover dance the other tests in this file drive against the headless
    backend -- the closest stand-in for that native waker path, proving
    both the flag and the pipeline it gates still work on the real code
    path `cli.main` takes for `--native`."""
    captured: dict = {}

    def _fake_run_native(self, title=None):
        fm = captured["fm"]
        x, y = _find_row(fm, "alpha")
        _move_to(fm, x, y)
        _wait_past_the_delay_and_tick(fm)
        alpha_path = str(sample_tree / "alpha")
        captured["hover_tooltips_enabled"] = fm.hover_tooltips_enabled
        captured["shown_after_delay"] = alpha_path in fm.app.screen()

        _move_to(fm, _OFF_X, _OFF_Y)
        captured["hidden_after_leave"] = alpha_path not in fm.app.screen()

    monkeypatch.setattr(quadraui.QuiApp, "run_native", _fake_run_native, raising=False)

    real_file_manager = _cli_module.FileManager

    def _spy_file_manager(*args, **kwargs):
        fm = real_file_manager(*args, **kwargs)
        _shorten_tooltip_delay(fm)
        captured["fm"] = fm
        return fm

    monkeypatch.setattr(_cli_module, "FileManager", _spy_file_manager)

    assert _cli_module.main([str(sample_tree), "--native"]) == 0

    assert captured["hover_tooltips_enabled"] is True
    assert captured["shown_after_delay"] is True
    assert captured["hidden_after_leave"] is True


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
    assert "5 B" in screen  # the human-readable size, exact (plain "B" matches the toolbar too)

    _move_to(fm, _OFF_X, _OFF_Y)
    assert readme_path not in fm.app.screen()


def test_a_tree_tooltip_auto_dismisses_after_idle_timeout_with_no_movement(sample_tree, monkeypatch):
    """`_on_hover_timer`'s `_TOOLTIP_HIDE` branch: left alone (no `MouseLeft`,
    no further movement) for `_TOOLTIP_AUTO_DISMISS_MS`, a shown tooltip
    hides itself -- VS Code's own idle-timeout half of the hover-card
    contract, not just the pointer-leave half the other tests cover.
    Shortened the same way `_shorten_tooltip_delay` shortens the show
    delay, so this stays as fast as every other test here."""
    monkeypatch.setattr(_app_module, "_TOOLTIP_AUTO_DISMISS_MS", DELAY_MS)
    fm = FileManager(sample_tree, width=160, height=30)
    _shorten_tooltip_delay(fm)

    x, y = _find_row(fm, "alpha")
    _move_to(fm, x, y)
    _wait_past_the_delay_and_tick(fm)
    alpha_path = str(sample_tree / "alpha")
    assert alpha_path in fm.app.screen()

    _wait_past_the_delay_and_tick(fm)  # past the (also-shortened) auto-dismiss window, no movement
    assert alpha_path not in fm.app.screen()
