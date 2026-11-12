# quadraui-files

A cross-backend **file manager** built on [quadraui](https://github.com/JDonaghy/quadraui)'s
Python bindings. One set of descriptors drives the whole UI; the **same Python code**
runs in your terminal (TUI) and as a **native desktop window** — only the final `run_*`
call differs per platform. The flagship *"prototype in your terminal, ship a native GUI
for free"* demo.

Seeded from quadraui-py's `examples/file_manager.py` and grown into a standalone app.

## Run

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"          # pulls the pinned quadraui wheel from PyPI (prebuilt, no Rust)
quadraui-files                   # headless: Python drives the loop, prints the final screen
quadraui-files ~/some/dir --tui  # real terminal
quadraui-files ~/some/dir --native   # native OS window (macOS/Windows wheels; Linux is TUI-only)
quadraui-files ~/some/dir --tui --reload  # hot-reload edits to the app's own source
quadraui-files ~/some/dir --dump # descriptor dump
```

The virtualenv is not optional: `quadraui` is only ever installed into it (never
into the system Python), so `pytest` must run with that env active —

```bash
. .venv/bin/activate && pytest -q
```

That command also works in a bare checkout, with nothing provisioned, because
`.venv/bin/activate` is **tracked in git** as a bootstrap: sourcing it resolves an
environment that can import `quadraui` + `pytest` and puts it first on `PATH`, the way a
real activate script would. Equivalently, `scripts/test.sh` runs the suite directly and
forwards its arguments to `pytest`:

```bash
sh scripts/test.sh                       # whole suite, -q
sh scripts/test.sh tests/test_actions.py # one file
```

Both go through `scripts/bootstrap-env.sh`, which uses the active environment when it can
already import `quadraui`, falls back to an in-tree `.venv`, and otherwise creates a
virtualenv shared across worktrees and keyed by the pinned quadraui version (a prebuilt
wheel install — seconds, no Rust compile). Provisioning a real in-tree
virtualenv (`python3.12 -m venv .venv`, as under [Run](#run)) overwrites the bootstrap
with the generated activate script, which is fine — a provisioned venv needs no
bootstrap. `git` then reports `.venv/bin/activate` as modified until
`git checkout .venv/bin/activate` restores it; nothing else under `.venv/` is tracked.

## Status / roadmap

| Tranche | Scope | State |
|---|---|---|
| **T0** | Folder tree + file-list tabs + navigation (lazy-loaded, cross-backend) | ✅ seeded baseline |
| **T1** | Open / reveal / move-to-trash, context menu, delete-confirm dialog, undo toast | ✅ all backends ([known limits](#known-limits)) |
| **T2** | Filter/search box, F2 rename, column sort | ✅ all backends ([known limits](#known-limits)) |
| **Preview** | Read-only preview pane for the selected file | ✅ all backends |
| **T3** | OS-theme match, keybindings, notifications | ✅ all backends |
| **Hover tooltips** | Delayed show/auto-dismiss pointer-hover tooltips on the toolbar, tree and details rows | ✅ all backends; native manual verification pending |
| **T4** | Window title + dirty-dot + tray + cursor shapes (native) | ✅ landed; native manual verification pending |

Hover tooltips work on every backend, TUI, headless and native alike. They're driven by
the app's own delayed-show/auto-dismiss timers through `QuiAppWaker.post_after`, which
`run_native` swaps onto the live GTK/AppKit/Win32 backend before handing control to its
event loop — see `app.py`'s "chrome: hover tooltips" section doc.

## Testing — black-box is the acceptance bar

Every behavior-changing PR ships a **black-box test** that drives the running app
(headless TUI backend) and asserts on its rendered `screen()` — see `tests/`. That
suite is the CI oracle, and `scripts/test.sh` is the entry point CI runs. Native-backend
behavior (the window/tray and native file ops) is verified manually.

## Known limits

`QuiApp` holds its one mutable borrow for the whole dispatch of an event, so a handler
or render callback cannot call back into it — the overlay surfaces
(`show_message_dialog` / `show_context_menu` / `show_toast`) and the OS actions
(`open_path` / `reveal_in_file_manager` / `move_to_trash` / `restore_from_trash`) are
reached through the deferred-action handle `QuiApp.actions()` returns instead.
`FileManager` obtains that handle once in `__init__` and the handler calls it directly;
every pump — `QuiApp.step`, `run_tui()`, and `run_native()`'s GTK/AppKit/Win32 loops —
drains the queue right after the dispatch that filled it, so the dialog, menu, toast and
OS calls land on **every** backend from the same unchanged Python.

The toast's **Undo** button restores the trashed path for real, via
`restore_from_trash`. It is one-shot per delete: a second restore of the same path finds
nothing in the trash and fails *inside* the pump, where the app cannot catch it, so a
repeat click is refused ("nothing left to undo") instead of queued. On **macOS** there
is no programmatic trash-restore API to delegate to, so the button is not offered there
at all (`UNDO_SUPPORTED` in `app.py`) — a host capability, not a backend branch.

A right-click would be the natural way to raise the context menu, but the pinned
quadraui's `Tree`/`DataTable` row-click events don't report which mouse button fired
them, so `Menu` is the keyboard stand-in.

Arrow keys act on whichever pane has key focus. Opening a folder (Enter, `o`,
the context menu's Open) hands key focus to the opened tab's details table —
"opened it, now you're in it" — and a row click or header click focuses it too.
With the tree focused, Up/Down walk the folder cursor and Right/Left
expand/collapse it; with a details table focused, Up/Down move its row
selection, Right drills into the selected folder row, and Left steps up to the
parent listing (focusing that folder's tab when one is still open). Left on the
root listing hands key focus back to the tree, so a keyboard session can always
leave the grid the same way it got in.

Press `/` for a live filter box over the active details table (Esc clears it, Enter
keeps it applied and closes the box), `F2` to inline-rename the selected file or
cursored folder (Enter commits a real rename on disk, Esc cancels), and click a details
column header (Name/Size/Modified/Kind) to sort by it, click again to reverse — the active
header shows a `▲`/`▼` marker. A rename is rejected (with a status-bar message, not a
crash) if the typed name contains a path separator or starts with `.`: this app's model
never lists dotfiles, so renaming onto one would just make the entry vanish on the next
refresh.

A single click on a details-table row selects it and loads it into the **preview
pane**; opening it with the OS's default app (or, for a folder, drilling in) needs a
double-click, Enter/`o` once the table has focus, or the context menu's Open — a plain
click never opens anything, so browsing the listing doesn't fire off an app per row. The
preview pane is a third region to the right of the details table behind its own
resizable divider: a one-line header names the selected file (with its size and modified
time, space permitting) and carries a `×` close control; below it, text content renders
read-only, pinned to the file's head, while binary or unreadable files show a short
`N bytes · <type>` placeholder instead. Press `p` (or click the header's `×`) to hide the
pane and give its width back to the details table; press `p` again to bring it back at
the same divider ratio.

## quadraui dependency

quadraui-py is released on PyPI as `quadraui`; this app pins it exactly (see
`pyproject.toml`, currently 0.10.1). Bump the version to pick up new quadraui features.

## License

MIT
