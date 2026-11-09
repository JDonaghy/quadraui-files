"""Console entry point: `quadraui-files [PATH] [--tui|--native|--dump]`.

The only platform-specific line is the `run_*` call — the same `FileManager`
descriptor code drives every backend.
"""

from __future__ import annotations

import sys
from importlib import metadata
from pathlib import Path

from quadraui import QuiApp

from .app import FileManager, _NATIVE_BACKEND, _Quit, _dump_steps, _run_headless, _wrap_quit

_NATIVE_FEATURE = {"darwin": "macos", "win32": "win"}.get(sys.platform, "gtk")


def _quadraui_requirement() -> str:
    """The pinned `quadraui @ git+...` requirement this install was built
    from, so the rebuild hint names the exact commit."""
    try:
        for req in metadata.requires("quadraui-files") or []:
            if "@" in req and req.split("@", 1)[0].strip() == "quadraui":
                return req.split(";")[0].strip()
    except metadata.PackageNotFoundError:
        pass
    return "quadraui @ git+https://github.com/JDonaghy/quadraui.git@<pin>#subdirectory=quadraui-py"


def _native_unavailable_message() -> str:
    """`--native` on a terminal-only quadraui build: a source build of
    quadraui-py compiles no native backend unless its Cargo feature is
    passed to maturin, and pip's wheel cache will hand back the
    featureless build unless it is bypassed."""
    return (
        "quadraui-files: --native needs quadraui built with a native backend, "
        "but the installed build is terminal-only.\n"
        "Rebuild it with the native feature for this platform:\n\n"
        f'    MATURIN_PEP517_ARGS="--features {_NATIVE_FEATURE}" pip install '
        f'--force-reinstall --no-deps --no-cache-dir "{_quadraui_requirement()}"\n\n'
        "or run in the terminal with --tui.\n"
    )


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = [a for a in argv if not a.startswith("--")]
    flags = {a for a in argv if a.startswith("--")}
    root = Path(args[0]) if args else Path.cwd()

    if "--dump" in flags:
        _dump_steps(root.resolve())
        return 0

    if "--native" in flags and "--tui" not in flags and not hasattr(QuiApp, "run_native"):
        sys.stderr.write(_native_unavailable_message())
        return 2

    fm = FileManager(root.resolve())

    if "--tui" in flags:
        _wrap_quit(fm)  # real terminal: raw mode, live redraw on key events
        fm.start_live_title()
        try:
            fm.app.run_tui()
        except _Quit:
            pass
    elif "--native" in flags:
        _wrap_quit(fm)  # OS window: AppKit / GTK / Win32 per the built feature
        fm.live_title = True  # `run_native(title=...)` sets the initial one
        # Only safe to flip right here, right before the one call that
        # actually opens a real native window -- see `FileManager.
        # native_window_chrome`/`native_tray`'s own docs for why this reads
        # the *built* backend (`_NATIVE_BACKEND`), not the host OS.
        fm.native_window_chrome = _NATIVE_BACKEND == "macos"
        fm.native_tray = _NATIVE_BACKEND in ("gtk", "macos", "win")
        # Hover tooltips ride `QuiAppWaker.post_after`, which `run_native`
        # never delivers (see `FileManager.hover_tooltips_enabled`'s own
        # doc, and the "chrome: hover tooltips" section's) -- opt out here,
        # the same opt-in-right-before-`run_native` story the two flags
        # just above have, so no dead post ever gets queued.
        fm.hover_tooltips_enabled = False
        try:
            fm.app.run_native(title=fm.window_title)
        except _Quit:
            pass
    else:
        _run_headless(fm)  # Python owns the loop; prints the final screen
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
