# What quadraui-files is (read this first)

**quadraui-files is a test app for [quadraui](https://github.com/JDonaghy/quadraui).**
It's a real, usable file manager, but its job is to exercise quadraui's Python
bindings (`quadraui` on PyPI). Use it to find what's missing or awkward, and
to show the pitch: **write one set of Python descriptors and run it as a
terminal UI (`--tui`) and as a native desktop window (`--native`)**. Only the
final `run_tui()` / `run_native()` call differs.

It also tests a workflow claim: quadraui plus plain Python should let one
developer get a lot done fast, with hot reload (`--reload`). There's no
coordinator pipeline for this repo. Work happens interactively, and gaps are
filed as GitHub issues.

## What it should feel like

A **desktop file manager**, like Finder, Explorer or Nautilus. Not Midnight
Commander or ranger. This holds even in the terminal.

- **Left pane: the OS's own sidebar, not a folder tree.** It shows the places
  the host OS's file manager shows:
  - macOS: Finder's Favorites (Applications, Desktop, Documents, Downloads,
    home), iCloud Drive, and Locations (volumes; the boot volume browses `/`).
  - Windows: Explorer's Quick access pins and This PC drives.
  - Linux: Nautilus's places and mounted devices.

  The host OS decides which set appears, not the backend, so the TUI on a Mac
  shows Finder's places. Sections fold shut. Picking a place shows it in the
  current tab.
- **Right pane: browses like Explorer, with tabs.**
  - Each tab has its own Back/Forward history.
  - Opening a folder navigates in place; it doesn't open a new tab.
  - An address bar of clickable breadcrumbs sits above a details grid
    (Name / Size / Modified / Kind).
  - Up selects the folder you came from. `t` opens a new tab and `w` closes
    one; the last tab stays open.
- **Preview pane** on the right for the selected file. `p` toggles it.
- **Startup location.** With no PATH argument it opens on the home folder. With
  one (including `.`), it opens there, and the sidebar highlights the matching
  place if there is one.
- **Keyboard-first in the TUI, mouse works everywhere.**
- **Safe file operations.** Deleting moves to the Trash, with undo where the OS
  supports it. Sidebar places and drive roots can't be renamed or trashed.

Priority order: **macOS TUI first**, then macOS native, then Windows/Linux.

## How to work on it

- Everything is in `src/quadraui_files/app.py` (see `CLAUDE.md` for the
  architecture rules). Run `.venv/bin/quadraui-files [PATH] --tui --reload`
  and edit while it runs. `__init__` and `cli.py` changes need a restart.
- **If quadraui can't do something cleanly, file an issue on
  JDonaghy/quadraui** with a minimal Python repro. Then work around it in the
  app, with a comment pointing at the issue, or wait for the next release.
  Bump the exact pin in `pyproject.toml` to pick up fixes.
- App-level follow-ups are tracked as issues on this repo.
- Black-box tests (`tests/`, headless TUI backend, assertions on the rendered
  screen) are the acceptance bar. See `CLAUDE.md`.
