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
pip install -e ".[dev]"          # builds quadraui-py from the pinned quadraui commit (needs Rust + maturin)
quadraui-files                   # headless: Python drives the loop, prints the final screen
quadraui-files ~/some/dir --tui  # real terminal
quadraui-files ~/some/dir --native   # native OS window (macOS/GTK/Windows per the build)
quadraui-files ~/some/dir --dump # descriptor dump
```

The virtualenv is not optional: `quadraui` is only ever installed into it (it is built
from source, not pulled from PyPI), so `pytest` must run with that env active —

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
already import `quadraui`, falls back to an in-tree `.venv`, and otherwise builds a
virtualenv shared across worktrees and keyed by the pinned quadraui commit (the first
build is a several-minute Rust compile; later runs reuse it). Provisioning a real in-tree
virtualenv (`python3.12 -m venv .venv`, as under [Run](#run)) overwrites the bootstrap
with the generated activate script, which is fine — a provisioned venv needs no
bootstrap. `git` then reports `.venv/bin/activate` as modified until
`git checkout .venv/bin/activate` restores it; nothing else under `.venv/` is tracked.

## Status / roadmap

| Tranche | Scope | State |
|---|---|---|
| **T0** | Folder tree + file-list tabs + navigation (lazy-loaded, cross-backend) | ✅ seeded baseline |
| **T1** | Open / reveal / move-to-trash, context menu, delete-confirm dialog, undo toast | ✅ headless + `--tui` ([known limits](#known-limits)) |
| **T2** | Filter/search box, F2 rename, column sort | planned |
| **Preview** | Read-only preview pane for the selected file | planned |
| **T3** | OS-theme match, keybindings, tooltips, notifications | planned |
| **T4** | Window title + dirty-dot + tray + cursor shapes (native) | planned |

## Testing — black-box is the acceptance bar

Every behavior-changing PR ships a **black-box test** that drives the running app
(headless TUI backend) and asserts on its rendered `screen()` — see `tests/`. That
suite is the CI oracle, and `scripts/test.sh` is the entry point CI runs. Native-backend
behavior (the window/tray and native file ops) is verified manually.

## Known limits

`QuiApp` holds its one mutable borrow for the whole dispatch of an event, so a handler
or render callback cannot call back into it — the overlay surfaces
(`show_message_dialog` / `show_context_menu` / `show_toast`) and the OS actions
(`open_path` / `reveal_in_file_manager` / `move_to_trash`) are reached through the
deferred-action handle `QuiApp.actions()` returns instead. `FileManager` obtains that
handle once in `__init__` and the handler calls it directly; the event pump drains the
queue right after the dispatch that filled it.

`run_tui()` drains that queue, so **T1's actions work in a real terminal**.
`run_native()`'s GTK/AppKit/Win32 loops do not drain it yet: an action queued while a
native window is open sits there until the window closes. So in `--native`, the context
menu, confirm dialog, toast and OS calls do not appear — that is a quadraui-py gap, not
a descriptor difference, and the same Python drives both backends unchanged.

The toast's **Undo** button is an affordance only — nothing in quadraui can restore a
path out of the OS trash, so clicking it reports that rather than pretending to.

## quadraui dependency

quadraui-py lags PyPI, so the binding is built from the quadraui repo at a **pinned
develop commit** (see `pyproject.toml`). Bump that SHA to pick up new quadraui features.

## License

MIT
