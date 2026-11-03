"""Console entry point: `quadraui-files [PATH] [--tui|--native|--dump]`.

The only platform-specific line is the `run_*` call — the same `FileManager`
descriptor code drives every backend.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .app import FileManager, _dump_steps, _run_headless, _wrap_quit, _Quit


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = [a for a in argv if not a.startswith("--")]
    flags = {a for a in argv if a.startswith("--")}
    root = Path(args[0]) if args else Path.cwd()

    if "--dump" in flags:
        _dump_steps(root.resolve())
        return 0

    fm = FileManager(root.resolve())

    if "--tui" in flags:
        _wrap_quit(fm)  # real terminal: raw mode, live redraw on key events
        try:
            fm.app.run_tui()
        except _Quit:
            pass
    elif "--native" in flags:
        _wrap_quit(fm)  # OS window: AppKit / GTK / Win32 per the built feature
        try:
            fm.app.run_native(title="quadraui file manager")
        except _Quit:
            pass
    else:
        _run_headless(fm)  # Python owns the loop; prints the final screen
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
