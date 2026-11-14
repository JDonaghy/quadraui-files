# quadraui-files

A cross-backend **file manager** built on [quadraui](https://github.com/JDonaghy/quadraui)'s
Python bindings (`quadraui-py`). One set of descriptors drives the whole UI; the **same
Python code** runs in the terminal (TUI) and as a **native desktop window** — only the
final `run_*` call differs. The flagship "prototype in your terminal, ship a native GUI
for free" demo. Seeded from quadraui-py's `examples/file_manager.py`.

**Read [`docs/VISION.md`](docs/VISION.md) first** -- what this app is for (a
quadraui test bed), the Finder/Explorer-style UX it's aiming at, and how gaps
get filed.

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

quadraui-py is on PyPI as `quadraui`, pinned exactly in `pyproject.toml`
(currently `0.10.1`, the first release with deferred actions, native chrome,
and the `quadraui.app.hot_reload` building blocks `--reload` runs on). Prebuilt
wheels install in seconds — no Rust toolchain. Bump the pin to pick up new
quadraui features. The Linux wheel is TUI-only, so `run_native` is macOS/
Windows-only in practice.

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
- This repo is worked interactively, not through the coord pipeline: file
  quadraui gaps on JDonaghy/quadraui and app follow-ups on this repo's issues.
- Commit and push before your final message.
