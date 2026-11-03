# quadraui-files

A cross-backend **file manager** built on [quadraui](https://github.com/JDonaghy/quadraui)'s
Python bindings (`quadraui-py`). One set of descriptors drives the whole UI; the **same
Python code** runs in the terminal (TUI) and as a **native desktop window** — only the
final `run_*` call differs. The flagship "prototype in your terminal, ship a native GUI
for free" demo. Seeded from quadraui-py's `examples/file_manager.py`.

## Architecture

- `src/quadraui_files/app.py` — the whole app: a `FileManager` that owns a `QuiApp`, a
  lazily-scanned `Node` model, a `render()` callback that returns a **layout tree**
  descriptor, and a `_handle()` event handler. Plain Python attributes hold what changes;
  the handler mutates them; `render()` rebuilds the tree every frame.
- `src/quadraui_files/cli.py` — the `quadraui-files` console entry (`PATH`, `--tui`,
  `--native`, `--dump`).

## Key design rules (a diff can violate these)

- **Descriptors are immutable once inserted.** There is no "update a slot" call — to
  change what's shown, clear the slot and re-insert with new fields (see `app.py`'s
  render dance). Do not try to mutate a descriptor in place.
- **Never call back into `QuiApp` from inside a handler/render callback** — it rejects
  the reentrant borrow. Mutate Python state and let the next `render()` reflect it.
- **The same descriptor code must run on every backend.** No backend-specific branches in
  the render path; only the final `run_tui()` / `run_native()` call differs.
- **Safe operations only.** Destructive file ops go through the trash
  (`move_to_trash`), never a hard/recursive delete. Local filesystem only.

## quadraui dependency

quadraui-py lags PyPI, so it's built from the quadraui repo at a **pinned develop commit**
(`pyproject.toml`'s `quadraui @ git+…@<sha>#subdirectory=quadraui-py`). Installing needs a
Rust toolchain + maturin. Bump that SHA to pick up new quadraui features; don't switch to
a PyPI version until quadraui-py is released with the features this app uses.

## Testing — black-box is the acceptance bar

**Every behavior-changing PR ships a black-box test** that drives the *running app*
(headless TUI backend) and asserts on its rendered `screen()` / `screen_contains()` — see
`tests/`. That suite is the Test-stage + CI oracle. Build the harness once (done,
`tests/conftest.py`); add tests incrementally, one or a few per behavior change. Keep the
core smoke set (`tests/test_smoke.py`) green.

- Run scoped to your change: `pytest tests/test_<area>.py`. The full suite is fast.
- **Native-backend behavior is verified manually, not in CI.** Window title / dirty-dot /
  tray, native file dialogs, and the OS-level effects of `open_path`/`reveal`/`move_to_trash`
  can't be asserted headless — wire them + a headless caps/no-op assertion, and note the
  manual-verification story in the PR. Do not block a PR waiting to assert a native effect.

## Conventions

- Python 3.10+, type hints.
- `gh` is on the deny-list — the coordinator owns GitHub; use plain `git`.
- Commit and push before your final message.
