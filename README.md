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

## Status / roadmap

| Tranche | Scope | State |
|---|---|---|
| **T0** | Folder tree + file-list tabs + navigation (lazy-loaded, cross-backend) | ✅ seeded baseline |
| **T1** | Open / reveal / move-to-trash, context menu, delete-confirm dialog, undo toast | ✅ on the Python-driven path ([known limits](#known-limits)) |
| **T2** | Filter/search box, F2 rename, column sort | planned |
| **Preview** | Read-only preview pane for the selected file | planned |
| **T3** | OS-theme match, keybindings, tooltips, notifications | planned |
| **T4** | Window title + dirty-dot + tray + cursor shapes (native) | planned |

## Testing — black-box is the acceptance bar

Every behavior-changing PR ships a **black-box test** that drives the running app
(headless TUI backend) and asserts on its rendered `screen()` — see `tests/`. That
suite is the CI oracle. Native-backend behavior (the window/tray and native file ops)
is verified manually.

## Known limits

`QuiApp` holds its one mutable borrow for the whole dispatch of an event, so a handler
or render callback cannot call back into it — the overlay surfaces
(`show_message_dialog` / `show_context_menu` / `show_toast`) and the OS actions
(`open_path` / `reveal_in_file_manager` / `move_to_trash`) have to be invoked from
top-level script code instead. The file actions therefore *queue* a request in the
handler and `FileManager.step` performs it right after `app.step()` returns.

`run_tui()` / `run_native()` block for their entire run and never hand control back to
top-level Python between events (a tick handler is dispatched the same way a handler is,
and hits the same borrow wall), so in a real terminal/native session the queued dialog,
menu, toast and OS call never fire. T1's actions are exercised end to end through the
headless-driven path (the tests, `--dump`, the default headless run); giving them a
real-backend home needs a deferred-action hook in quadraui-py itself.

The toast's **Undo** button is an affordance only — restoring a file out of the OS trash
is not implemented.

## quadraui dependency

quadraui-py lags PyPI, so the binding is built from the quadraui repo at a **pinned
develop commit** (see `pyproject.toml`). Bump that SHA to pick up new quadraui features.

## License

MIT
