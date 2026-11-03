# quadraui-files

A cross-backend **file manager** built on [quadraui](https://github.com/JDonaghy/quadraui)'s
Python bindings. One set of descriptors drives the whole UI; the **same Python code**
runs in your terminal (TUI) and as a **native desktop window** — only the final `run_*`
call differs per platform. The flagship *"prototype in your terminal, ship a native GUI
for free"* demo.

Seeded from quadraui-py's `examples/file_manager.py` and grown into a standalone app.

## Run

```bash
pip install -e ".[dev]"          # builds quadraui-py from the pinned quadraui commit (needs Rust + maturin)
quadraui-files                   # headless: Python drives the loop, prints the final screen
quadraui-files ~/some/dir --tui  # real terminal
quadraui-files ~/some/dir --native   # native OS window (macOS/GTK/Windows per the build)
quadraui-files ~/some/dir --dump # descriptor dump
```

## Status / roadmap

| Tranche | Scope | State |
|---|---|---|
| **T0** | Folder tree + file-list tabs + navigation (lazy-loaded, cross-backend) | ✅ seeded baseline |
| **T1** | Open / reveal / move-to-trash, context menu, delete-confirm dialog, undo toast | planned |
| **T2** | Filter/search box, F2 rename, column sort | planned |
| **Preview** | Read-only preview pane for the selected file | planned |
| **T3** | OS-theme match, keybindings, tooltips, notifications | planned |
| **T4** | Window title + dirty-dot + tray + cursor shapes (native) | planned |

## Testing — black-box is the acceptance bar

Every behavior-changing PR ships a **black-box test** that drives the running app
(headless TUI backend) and asserts on its rendered `screen()` — see `tests/`. That
suite is the CI oracle. Native-backend behavior (the window/tray and native file ops)
is verified manually.

## quadraui dependency

quadraui-py lags PyPI, so the binding is built from the quadraui repo at a **pinned
develop commit** (see `pyproject.toml`). Bump that SHA to pick up new quadraui features.

## License

MIT
