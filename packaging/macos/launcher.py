"""Entry point frozen into `Quadraui Files.app`.

A Finder/Dock/`open` launch has no terminal and no flags, so this always
asks `cli.main` for the native window. Pass a folder after `--args` to open
on it: `open -a "Quadraui Files" --args ~/src`. With no folder it opens on
the home folder, the way Finder does.
"""

import sys

from quadraui_files.cli import main

# Older macOS appends a `-psn_<serial>` process-serial-number argument to
# LaunchServices launches. It isn't a path.
args = [a for a in sys.argv[1:] if not a.startswith("-psn_")]
if "--native" not in args:
    args.append("--native")

raise SystemExit(main(args))
