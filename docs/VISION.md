# What quadraui-files is (read this first)

**quadraui-files is a test app for [quadraui](https://github.com/JDonaghy/quadraui).**
It's a real, usable file manager, but its job is to exercise quadraui's Python
bindings (`quadraui` on PyPI). Use it to find what's missing or awkward, and
to show the pitch: **write one set of Python descriptors and run it as a
terminal UI (`--tui`) and as a native desktop window (`--native`)**. Only the
final `run_tui()` / `run_native()` call differs.

**The explicit goal is Finder parity, not just a Finder-flavored file
manager.** Chase the real thing's browsing behavior as closely as the backend
allows -- multi-select, Get Info, richer view modes, drag-and-drop, a context
menu that covers what Finder's does -- rather than stopping at a passable
look-alike. Each gap this surfaces, in the app or in quadraui itself, is the
point: pushing for real fidelity is what puts quadraui through its paces and
will legitimately need multiple upstream issues. See "Finder parity backlog"
below for what's missing today.

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
The backlog below is scoped and sequenced the same way: land each item on
macOS TUI, then carry it to the other backends, rather than chasing every
platform at once.

## Finder parity backlog

Core browsing fidelity, roughly in priority order. Visual/chrome polish
(spacing, animation, exact typography) stays secondary to these -- a feature
Finder has that this app doesn't is a bigger gap than one that merely looks
slightly off.

1. **Multi-select** in the details grid (Shift/Cmd+click, Shift+Up/Down).
   Today `details_table`'s `selected_idx` is a single `int | None` -- check
   whether `DataTable`'s own protocol can even carry a set of selected rows
   before writing any app-side selection-state code; if it can't, that's the
   first upstream issue this backlog produces.
2. **A context menu that covers what Finder's does.** Today's is Open /
   Reveal / Move to Trash only. Missing: New Folder, Duplicate, Copy/Paste,
   Rename, Get Info.
3. **Get Info** (Cmd+I): a panel or dialog with size, kind, created/modified
   dates, permissions.
4. **Additional view modes.** Today's details grid is Finder's "as List"
   view; add an icon grid view (Finder's default) toggle. Column view
   (Miller columns) is a stretch goal, lower priority than the first three.
5. **Richer preview.** Today's preview pane is plain text lines; add image
   thumbnails so it earns the name "Quick Look-style."
6. **Drag-and-drop** -- move/copy within a listing, onto sidebar places,
   between tabs. Likely native-backend-only until/unless quadraui exposes
   something equivalent for the TUI; expect this to surface a design
   question upstream before it's a one-line app fix.
7. **Color tags/labels** (Finder's colored dots). Lowest priority --
   macOS-specific metadata (extended attributes), no Explorer/Nautilus
   equivalent to anchor a cross-platform design on.

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
